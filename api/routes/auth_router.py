import logging
from datetime import datetime
import random
import redis.asyncio as redis  # type: ignore

from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from mysql.connector import Error
from pytz import timezone
from api.auth import (REFRESH_TOKEN_COOKIE_NAME, REFRESH_TOKEN_DOMAIN,
                      REFRESH_TOKEN_MAX_AGE, REFRESH_TOKEN_RENEWAL_THRESHOLD, auth_token_response,
                      create_access_token, create_refresh_token)
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType  # type: ignore
from api.db.database import DB_NAME, get_session
from api.config import settings
from api.db.redis_backend import get_redis
from api.models.entities import RefreshTokenData, ResendCodeRequest, TokenData, User, UserCreate, UserTokenJTI, VerifyCodeRequest
from api.users import users
from api.utils import (get_current_user, get_current_user_jti,
                       get_refresh_token, validate_auth_creds,
                       validate_login_creds)

# TODO: user routes

logger = logging.getLogger('users_logger')
auth_router = APIRouter(prefix='/auth', tags=['auth'])

JTI_EXPIRY = 3600
tz = timezone('Africa/Nairobi')
BUILD = settings.BUILD
MAIL_USERNAME = settings.MAIL_USERNAME
MAIL_PASSWORD = settings.MAIL_PASSWORD
MAIL_FROM = settings.MAIL_FROM
MAIL_PORT = settings.MAIL_PORT
IS_LOCAL = BUILD == 'development'


conf = ConnectionConfig(
    MAIL_USERNAME=MAIL_USERNAME,
    MAIL_PASSWORD=MAIL_PASSWORD,
    MAIL_FROM=MAIL_FROM,
    MAIL_PORT=587,
    MAIL_SERVER="smtp.gmail.com",
    MAIL_FROM_NAME="Tasker App",
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)

current_year = datetime.now().year

html_content = """<!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tasker Verification Code</title>
    </head>
    <body style="margin: 0; padding: 0; background-color: #f4f5f7; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">

    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color: #f4f5f7; padding: 40px 10px;">
    <tr>
        <td align="center">
        <!-- Main Card Container -->
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width: 520px; background-color: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e5e7eb;">
            
            <!-- Header -->
            <tr>
            <td align="center" style="padding: 32px 32px 16px 32px; background-color: #ffffff;">
                <img src="https://res.cloudinary.com/dq4izno26/image/upload/v1786962582/logo_ddxrci.svg" width="48" height="48" alt="Tasker" style="display: block; width: 48px; height: 48px; border: 0;" />
                <h1 style="margin: 12px 0 0 0; font-size: 22px; font-weight: 700; color: #111827; letter-spacing: -0.5px;">Tasker</h1>
            </td>
            </tr>

            <!-- Body Content -->
            <tr>
            <td style="padding: 0 32px 32px 32px;">
                <h2 style="margin: 0 0 12px 0; font-size: 18px; font-weight: 600; color: #1f2937;">Verify your email address</h2>
                <p style="margin: 0 0 24px 0; font-size: 14px; line-height: 22px; color: #4b5563;">
                Thank you for signing in to <strong>Tasker</strong>. Enter the 6-digit verification code below to complete your request.
                </p>

                <!-- OTP Code Display Box -->
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                <tr>
                    <td align="center" style="background-color: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 8px; padding: 20px;">
                    <span style="font-family: 'Courier New', Courier, monospace; font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #5030E5; display: inline-block;">{otp_code}</span>
                    </td>
                </tr>
                </table>

                <!-- Notice & Expiry -->
                <p style="margin: 20px 0 0 0; font-size: 13px; line-height: 20px; color: #6b7280; text-align: center;">
                This code will expire in <strong>5 minutes</strong>. If you did not request this code, you can safely ignore this email.
                </p>
            </td>
            </tr>

            <!-- Security Footer Divider -->
            <tr>
            <td style="padding: 0 32px;">
                <div style="border-top: 1px solid #f1f5f9;"></div>
            </td>
            </tr>

            <!-- Footer Metadata -->
            <tr>
            <td style="padding: 24px 32px; background-color: #ffffff; text-align: center;">
                <p style="margin: 0 0 8px 0; font-size: 12px; color: #9ca3af;">
                Tasker Security &bull; Safe Authentication System
                </p>
                <p style="margin: 0; font-size: 11px; color: #d1d5db;">
                &copy; {current_year} Tasker Application. All rights reserved.
                </p>
            </td>
            </tr>

        </table>
        </td>
    </tr>
    </table>

    </body>
    </html>
"""


async def send_verification_email(email: str, otp_code: str):

    plain_text_fallback = (
        f"Your Tasker verification code is: {otp_code}\n\n"
        f"This code will expire in 5 minutes. If you did not request this, please ignore this email.\n\n"
        f"© {current_year} Tasker. All rights reserved."
    )

    formatted_html = html_content.format(
        otp_code=otp_code,
        current_year=current_year
    )

    message = MessageSchema(
        subject=f"Your Tasker Verification Code",
        recipients=[email],
        body=plain_text_fallback,
        alternative_body=formatted_html,
        subtype=MessageType.plain
    )

    fm = FastMail(conf)

    try:
        await fm.send_message(message)
        logger.info(f"Email sent successfully to {email}")
        return {"status": "success", "message": f"OTP sent to {email}"}

    except Exception as e:
        logger.error(f"Failed to send email via fastapi-mail: {e}")


async def generate_send_otp(email: str,
                            redis_client: redis.Redis,
                            background_tasks: BackgroundTasks) -> str:

    code = f"{random.randint(100000, 999999)}"

    # Store OTP code (5-min TTL) & set a 60-second cooldown lock
    await redis_client.setex(f"user:{email}:verify", 300, code)
    await redis_client.setex(f"resend_cooldown:{email}", 60, "locked")

    # Queue background email job
    background_tasks.add_task(send_verification_email, email, code)
    return code


@auth_router.post('/login', status_code=status.HTTP_200_OK)
async def login_for_access_token(background_tasks: BackgroundTasks,
                                 form_data: OAuth2PasswordRequestForm =
                                 Depends(validate_login_creds),
                                 redis_client: redis.Redis = Depends(
                                     get_redis),
                                 conn: Connection = Depends(get_session)):
    logger.debug('[FUNC] login for access token')

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            login_user = await users.authenticate_user(
                cursor, form_data.username, form_data.password)

            if not login_user.is_verified:
                # Auto-trigger a fresh code on login attempt (respecting rate limits)
                cooldown = await redis_client.get(f"resend_cooldown:{login_user.email}")
                if not cooldown:
                    await generate_send_otp(login_user.email, redis_client, background_tasks)

                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "code": "ACCOUNT_UNVERIFIED",
                        "message": "Account is not verified. A verification code has been sent.",
                        "email": login_user.email
                    })

            current_version = login_user.token_v
            logger.info(
                f'User {login_user.username} current version {current_version}')

            if current_version:
                redis_key = f"user:{login_user.username}:token_v"
                await redis_client.setex(redis_key, 604800, current_version)

                logger.info(f'{redis_key} successfully cached')

            token_data = {'sub': login_user.username, 'v': current_version}

            response = auth_token_response(
                token_data=token_data, msg="You've been logged in successfully")

            logger.info(f'{token_data['sub']} login successful')
            return response

    except Error as e:
        logger.error(f"Database operation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to login user due to a server error")


@auth_router.get("/users/me", status_code=status.HTTP_200_OK, response_model=User)
async def read_users_me(current_user: TokenData = Depends(get_current_user)):
    logger.info(f'user-> {current_user.sub}')
    return User(username=current_user.sub)


@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
async def create_user(user: UserCreate, background_tasks: BackgroundTasks,
                      _: bool = Depends(validate_auth_creds),
                      conn: Connection = Depends(get_session),
                      redis_client: redis.Redis = Depends(get_redis)):
    query = f"SELECT is_verified FROM {DB_NAME}.`user` WHERE email = %s LIMIT 1;"

    query_update = f"""
            UPDATE {DB_NAME}.`user` 
            SET hashed_password=%s, username=%s 
            WHERE email = %s;
        """

    redis_key = f"user:{user.username}:id"

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            # 1. Fetch user status by email
            await cursor.execute(query, (user.email,))
            result = await cursor.fetchone()

            if result:
                # User exists in MySQL
                if result.get("is_verified"):
                    # User is already verified Block registration
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Email already registered and verified."
                    )

                # User exists but is NOT verified Allow
                hash_password = users.get_password_hash(password=user.password)
                await cursor.execute(query_update, (hash_password, user.username, user.email))

                logger.info(
                    f"Unverified user {user.email} re-initiated registration.")

                await conn.commit()

                # Trigger fresh Redis OTP & return early to move user to verification step
                await generate_send_otp(email=user.email, redis_client=redis_client, background_tasks=background_tasks)

                logger.info(
                    'Account pending verification. A new code has been sent.')

                return {
                    "message": "Account pending verification. A new code has been sent.",
                    "is_verified": False,
                    "email": user.email
                }

            # Check if username or email is taken
            existing_user = await users.check_user_exists(
                cursor, user)

            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Username is already taken."
                )

            # Create Brand New User
            hash_password = users.get_password_hash(password=user.password)
            params = (user.username, user.email,
                      hash_password, user.profile_img_url)

            await cursor.callproc('create_user', params)

            # Fetch the result returned
            user_record = await cursor.fetchone()
            await conn.commit()

            if not user_record or 'userID' not in user_record:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to retrieve user ID after account creation."
                )

            user_id = user_record['userID']

            await redis_client.set(redis_key, user_id)
            logger.info(f'cached user:{user.username} ID successful')

            # Generate & Send OTP for New Account
            await generate_send_otp(email=user.email, redis_client=redis_client, background_tasks=background_tasks)

            logger.info(
                f"User {user.username} created successfully (unverified)")

            return {
                "message": "User registered successfully. Please verify your email.",
                "userID": user_id,
                "email": user.email,
                "is_verified": False
            }

    except Error as e:
        await conn.rollback()
        logger.error(f"Database registration error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register user due to a server error")

    except Exception as e:
        await conn.rollback()
        logger.error(f"Failed registration {e}")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to register user due to a server error")


@auth_router.post('/verify-code')
async def verify_code(payload: VerifyCodeRequest,
                      conn=Depends(get_session),
                      redis_client: redis.Redis = Depends(get_redis)):
    redis_key = f"user:{payload.email}:verify"
    cached_code = await redis_client.get(redis_key)

    logger.debug(f'payload {payload}')

    if not cached_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired or was never requested."
        )

    if cached_code != payload.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code."
        )

    query_update = f"""
        UPDATE {DB_NAME}.`user` 
        SET is_verified = 1 
        WHERE email = %s;
    """

    query_fetch_user = f"""
        SELECT username, token_v FROM {DB_NAME}.`user` 
        WHERE email = %s LIMIT 1;
    """

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            await cursor.execute(query_update, (payload.email,))

            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User account not found."
                )

            await conn.commit()

            await cursor.execute(query_fetch_user, (payload.email,))
            user_record = await cursor.fetchone()

    except Exception as e:
        await conn.rollback()
        logger.error(f"Error during email verification DB transaction: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user verification status."
        )

    await redis_client.delete(redis_key)
    token_data = {'sub': user_record['username'], 'v': user_record['token_v']}

    response = auth_token_response(
        token_data=token_data, msg="You've been logged in successfully")

    logger.info(f'{token_data['sub']} login successful')
    return response


@auth_router.post('/resend-code')
async def resend_verification_code(payload: ResendCodeRequest,
                                   background_tasks: BackgroundTasks,
                                   conn: Connection = Depends(get_session),
                                   redis_client: redis.Redis = Depends(get_redis)):
    query = f"SELECT is_verified FROM {DB_NAME}.`user` WHERE email = %s LIMIT 1;"

    async with conn.cursor(cursor=DictCursor) as cursor:
        await cursor.execute(query, (payload.email,))
        user_record = await cursor.fetchone()

    # Validate user existence
    if not user_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found.")

    # Check if already verified
    if user_record.get("is_verified"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is already verified. Please log in."
        )

    # Check for 60-second cooldown lock in Redis
    cooldown_key = f"resend_cooldown:{payload.email}"
    has_cooldown = await redis_client.get(cooldown_key)

    if has_cooldown:
        # time to live ttl
        ttl = await redis_client.ttl(cooldown_key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Please wait {ttl} seconds before requesting a new code."
        )

    # Generate & Send OTP for Account
    await generate_send_otp(email=payload.email, redis_client=redis_client, background_tasks=background_tasks)

    # Store new code in Redis (5-min expiration) & set 60s cooldown lock
    logger.info(f"Resent verification code to {payload.email}")
    return {"message": "A new verification code has been sent."}


@auth_router.post('/logout', status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(current_user: TokenData = Depends(get_current_user),
                       conn: Connection = Depends(get_session),
                       redis_client: redis.Redis = Depends(get_redis),
                       users_jti: UserTokenJTI = Depends(get_current_user_jti)):
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            UPDATE_STATEMENT = f"""UPDATE {DB_NAME}.user SET
                    token_v = token_v + 1 WHERE userID=%(user_id)s"""

            await cursor.execute(UPDATE_STATEMENT, {'user_id': user_id})

            if cursor.rowcount == 0:
                # Handle case where user_id wasn't found in DB
                raise ValueError(f"User with ID {user_id} not found.")
            logger.info(f'{type(users_jti)}')

            await conn.commit()

            for key, value in users_jti:
                KEY = f"{key}:{value}"
                await redis_client.setex(KEY, JTI_EXPIRY, 'REVOKED')
                logger.info(f'{KEY} successfully revoked')
            # await add_jti_block_list(users_jti)

            response = JSONResponse(
                content={"message": "You've been logged out successfully."},
                status_code=status.HTTP_200_OK)
            # deleting the logout users httponly cookie
            response.set_cookie(key=REFRESH_TOKEN_COOKIE_NAME,
                                value='',
                                httponly=True,
                                secure=True,
                                samesite="lax" if IS_LOCAL else "none",
                                domain=REFRESH_TOKEN_DOMAIN if IS_LOCAL else None,
                                max_age=-1)

            return response

    except Error as e:
        logger.error(f"Database operation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revoke user token due to a server error")


@auth_router.post('/refresh', status_code=status.HTTP_200_OK)
async def get_new_access_token(token: RefreshTokenData = Depends(get_refresh_token),
                               redis_client: redis.Redis = Depends(get_redis)):
    try:
        logger.debug(f'refresh token user token')
        token_data = {'sub': token.sub, 'v': token.version}

        new_access_token = create_access_token(
            payload=token_data)
        response = JSONResponse(content={'accessToken': new_access_token})

        exp_timestamp = datetime.fromtimestamp(
            token.exp, tz=tz)
        time_remaining = exp_timestamp - datetime.now(tz)

        # if the refresh token is less than the allowed token renew threshold issue a new token

        if time_remaining < REFRESH_TOKEN_RENEWAL_THRESHOLD:
            token_sub = token_data.get('sub')
            token_version = token_data.get('v')

            new_refresh_token = create_refresh_token(
                payload={**token_data, 'refresh': True})

            if not isinstance(token_sub, str) or not isinstance(token_version, int):
                logger.warning(
                    f"Invalid token payload structure: {token_data}")
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": "Missing or invalid 'sub' (str) or 'version' (int)"}
                )

            logger.info(
                f"Processing version {token_version} for user {token_sub}")

            KEY = f"user:{token_sub}:token_v"

            await redis_client.setex(KEY, 604800, token_version)
            logger.info(f'{KEY} successfully cached')

            response.set_cookie(
                key=REFRESH_TOKEN_COOKIE_NAME,
                value=new_refresh_token,
                httponly=True,
                secure=True,
                samesite="lax" if IS_LOCAL else "none",
                domain=REFRESH_TOKEN_DOMAIN if IS_LOCAL else None,
                max_age=REFRESH_TOKEN_MAX_AGE
            )

        return response

    except Error as e:
        logger.error(f"Server refresh token error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh user token due to a server error")
