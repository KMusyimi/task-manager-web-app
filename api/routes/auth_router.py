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
    MAIL_PORT=MAIL_PORT,
    MAIL_SERVER="sandbox.smtp.mailtrap.io",
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True
)

current_year = datetime.now().year


async def send_verification_email(email: str, otp_code: str):

    html_content = f"""
    <!DOCTYPE html>
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
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width: 520px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05); border: 1px solid #e5e7eb;">
            
            <!-- Header with Embedded Logo -->
            <tr>
                <td align="center" style="padding: 32px 32px 16px 32px; background-color: #ffffff;">
                <img src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512' fill='%235030E5'><path d='M137.057 36.698c-2.614 0-5.23.162-7.827.52-25.68 3.542-67.16 25.9-97.54 52.824 10.785-5.202 24.81-11.394 39.464-16.28 13.623-4.54 27.76-8.077 41.006-8.306 1.893-.033 3.767.002 5.62.11 7.407.437 14.596 2.11 20.863 5.99 1.865 1.154 3.62 2.523 5.234 4.074 6.646-10.978 14.16-22.022 23.152-33.076-7.964-2.88-17.548-5.41-27.362-5.803-.87-.034-1.74-.052-2.61-.052zm237.886 0c-.87 0-1.742.018-2.61.053-9.815.395-19.4 2.925-27.362 5.804 8.993 11.054 16.507 22.098 23.153 33.076 1.615-1.55 3.37-2.92 5.234-4.074 6.267-3.88 13.456-5.553 20.864-5.99 1.853-.108 3.727-.143 5.62-.11 13.246.23 27.383 3.766 41.006 8.307 14.655 4.885 28.68 11.077 39.465 16.28-30.38-26.925-71.86-49.283-97.54-52.825-2.596-.358-5.213-.52-7.827-.52zm-179.45 1.02c-28.343 29.284-43.33 58.435-58.462 88.687.01 8.366.11 22.473 1.9 36.78 1.905 15.244 6.6 29.882 11.412 34.722l24.36 22.395H185v58.437l17.742 8.87 3.963-11.888-7.53-37.655 17.65-3.53 15.415 77.077c5.957 4.855 14.755 7.688 23.76 7.688s17.803-2.833 23.76-7.688l15.414-77.078 17.652 3.53-7.53 37.656 3.962 11.888L327 278.74V220.3h12.273l22.364-22.364c4.818-4.818 9.525-19.486 11.433-34.753 1.79-14.307 1.89-28.414 1.9-36.78-15.11-30.204-30.076-59.31-58.33-88.55-44.585 6.62-77.05 5.087-121.148-.137zm16.532 30.533c29.854 14.928 58.096 14.928 87.95 0l8.05 16.103c-34.146 17.073-69.904 17.073-104.05 0l8.05-16.102zM114.67 83.463c-10.478-.157-24.295 2.87-37.824 7.38-20.06 6.686-39.25 16.184-49.223 21.42.863 2.71 1.833 5.585 2.973 8.682C36.2 136.18 44.9 155.478 54.386 174.24c9.488 18.764 19.8 37.067 28.524 50.38 4.362 6.657 8.365 12.083 11.387 15.483.827.93 1.26 1.252 1.887 1.843 21.254-11.455 29.27-22.205 38.695-34.36-8.99-11.137-11.9-26.9-13.81-42.167C118.98 148.685 119 132.3 119 124.3v-2.125l.95-1.9c4.604-9.21 9.277-18.53 14.362-27.915-1.285-2.52-2.94-4.14-5.142-5.502-2.92-1.808-7.107-3.01-12.45-3.324-.667-.04-1.352-.064-2.05-.074zm282.66 0c-.698.01-1.383.035-2.05.074-5.343.314-9.53 1.516-12.45 3.324-2.2 1.363-3.857 2.982-5.142 5.502 5.085 9.386 9.758 18.704 14.363 27.914l.95 1.9v2.126c0 8 .02 24.384-2.07 41.117-1.91 15.266-4.82 31.03-13.81 42.167 9.425 12.154 17.442 22.904 38.696 34.36.626-.592 1.06-.914 1.887-1.844 3.022-3.4 7.025-8.826 11.387-15.483 8.723-13.313 19.036-31.616 28.523-50.38 9.488-18.762 18.186-38.06 23.79-53.296 1.14-3.097 2.11-5.973 2.974-8.683-9.974-5.234-29.162-14.732-49.223-21.42-13.53-4.51-27.346-7.535-37.824-7.378zm-203.68 54.695c3.49.06 6.937.312 10.287.727 8.934 1.105 17.267 3.408 24.286 6.838 7.02 3.43 13.198 7.86 16.138 15.252l-9.405 3.744c.567 5.67 1.005 11.785 1.188 17.922.375 12.586.037 24.885-3.723 34.84l-16.84-6.358c1.873-4.96 2.914-16.396 2.57-27.947-.237-7.954-.968-16.098-1.824-22.973-4.19-1.547-9.244-2.793-14.6-3.455-14.394-1.78-30.602.868-40.052 8.54l-11.348-13.972c11.352-9.216 25.78-12.845 39.824-13.15 1.17-.025 2.337-.027 3.5-.008zm124.7 0c1.163-.02 2.33-.017 3.5.008 14.043.305 28.472 3.934 39.824 13.15l-11.348 13.973c-9.45-7.673-25.658-10.32-40.053-8.54-5.355.662-10.41 1.907-14.6 3.454-.855 6.875-1.586 15.02-1.823 22.973-.345 11.55.697 22.987 2.57 27.947l-16.84 6.36c-3.76-9.957-4.098-22.255-3.723-34.842.183-6.137.62-12.25 1.188-17.922l-9.406-3.744c2.94-7.39 9.118-11.822 16.137-15.252 7.02-3.43 15.352-5.733 24.285-6.838 3.35-.414 6.8-.668 10.288-.727zm-140.582 27.32c9.89 1.982 19.044 2.465 27.94.122l4.585 17.405c-12.44 3.277-24.618 2.413-36.06.12l3.535-17.647zm156.464 0l3.536 17.65c-11.443 2.29-23.622 3.155-36.06-.122l4.585-17.406c8.895 2.342 18.05 1.86 27.94-.122zM149.484 221.57c-3.926 18.077-11.744 56.325-12.488 79.027-.338 10.32.083 22.752.97 36.025 9.928-15.62 19.44-33.406 29.034-54.307V237.67l-17.516-16.1zm210.11 3.865L345 240.028v42.285c9.74 21.218 19.397 39.22 29.49 55.01.838-13.487 1.126-26.103.526-36.502-1.178-20.39-9.878-54.958-15.422-75.385zM180.12 296.427c-27.3 57.515-55.76 93.404-93.753 125.43 25.12.802 41.352-8.37 56.606-25.72 17.816-20.268 33.22-52.94 52.918-91.825l-15.77-7.885zm151.76 0l-15.77 7.885c19.696 38.886 35.1 71.557 52.917 91.824 15.254 17.352 31.487 26.523 56.606 25.72-37.994-32.025-66.454-67.914-93.754-125.43zm-118.06 14.87l-.564 1.696-1.266-.633c-19.548 38.716-34.844 72.163-55.5 95.66-3.083 3.508-6.326 6.758-9.728 9.75 2.473 17.93 4.636 31.68 5.355 36.155 17.846 7.732 41.202 10.51 62.938 8.283-.035-.626-.055-1.26-.055-1.906v-143.11l-1.18-5.894zm84.36 0l-1.18 5.895v143.11c0 .645-.02 1.28-.055 1.906 21.757 2.23 45.136-.556 62.99-8.305.75-4.39 3.04-18.03 5.626-35.853-3.52-3.068-6.87-6.412-10.05-10.03-20.656-23.497-35.952-56.944-55.5-95.66l-1.266.633-.564-1.695zM233 332.854v11.363c5.93 4.487 14.373 7.086 23 7.086s17.07-2.6 23-7.086v-11.363c-7.23 3.03-15.153 4.45-23 4.45-7.847 0-15.77-1.42-23-4.45zm0 32v11.363c5.93 4.487 14.373 7.086 23 7.086s17.07-2.6 23-7.086v-11.363c-7.23 3.03-15.153 4.45-23 4.45-7.847 0-15.77-1.42-23-4.45zm0 32v63.45c0 20 46 20 46 0v-63.45c-7.23 3.03-15.153 4.45-23 4.45-7.847 0-15.77-1.42-23-4.45z'/></svg>" width="48" height="48" alt="Tasker Logo" style="display: block; width: 48px; height: 48px; border: 0;" />
                <h1 style="margin: 16px 0 0 0; font-size: 22px; font-weight: 700; color: #111827; letter-spacing: -0.5px;">Tasker</h1>
                </td>
            </tr>

            <!-- Body Content -->
            <tr>
                <td style="padding: 0 32px 32px 32px;">
                <h2 style="margin: 0 0 12px 0; font-size: 18px; font-weight: 600; color: #1f2937;">Verify your email address</h2>
                <p style="margin: 0 0 24px 0; font-size: 14px; line-height: 22px; color: #4b5563;">
                    Thank you for signing in to <strong>Tasker</strong>. Enter the 6-digit verification code below to complete your authentication request.
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

    formatted_html = html_content.format(
        otp_code=otp_code,
        current_year=current_year
    )

    message = MessageSchema(
        subject=f"{otp_code} is your Tasker verification code",
        recipients=[email],
        body=formatted_html,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    await fm.send_message(message)

    return {"status": "success", "message": f"OTP sent to {email}"}


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

            # Generate & Send OTP for New Account

            await generate_send_otp(email=login_user.email, redis_client=redis_client, background_tasks=background_tasks)

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
