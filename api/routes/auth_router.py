from email.mime.text import MIMEText
import logging
from datetime import datetime
import random
import smtplib

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
from api.db.database import DB_NAME, get_session
from api.config import settings
from api.db.redis_backend import add_jti_block_list, delete_verification_code, get_verification_code, set_cache_user_id, set_user_token_v, set_verification_code
from api.models.entities import RefreshTokenData, TokenData, User, UserCreate, UserTokenJTI, VerifyCodeRequest
from api.users import users
from api.utils import (get_current_user, get_current_user_jti,
                       get_refresh_token, validate_auth_creds,
                       validate_login_creds)

# TODO: user routes
logger = logging.getLogger('users_logger')
auth_router = APIRouter(prefix='/auth', tags=['auth'])

tz = timezone('Africa/Nairobi')
BUILD = settings.BUILD
IS_LOCAL = BUILD == 'development'


def send_verification_email(email: str, code: str):
    """Synchronous email sender intended for background tasks"""
    # Replace these with your actual SMTP provider config (e.g., SendGrid, Mailgun, Gmail SMTP)
    SMTP_SERVER = "smtp.mailtrap.io"
    SMTP_PORT = 587
    SMTP_USER = "your_username"
    SMTP_PASSWORD = "your_password"

    msg = MIMEText(
        f"Your Tasker verification code is: {code}. It expires in 5 minutes.")
    msg["Subject"] = "Verify Your Tasker Account"
    msg["From"] = "noreply@tasker.com"
    msg["To"] = email

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(msg["From"], [msg["To"]], msg.as_string())
    except Exception as e:
        print(f"Failed to send email: {e}")


@auth_router.post('/login', status_code=status.HTTP_200_OK)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm =
                                 Depends(validate_login_creds),
                                 conn: Connection = Depends(get_session)):
    logger.debug('[FUNC] login for access token')
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:

            login_user = await users.authenticate_user(
                cursor, form_data.username, form_data.password)

            current_version = login_user.token_v
            logger.info(
                f'User {login_user.username} current version {current_version}')

            if current_version:
                await set_user_token_v(login_user.username, current_version)

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
                      conn: Connection = Depends(get_session)):
    redis_key = f"verify:{user.email}"
    query = f"SELECT is_verified FROM {DB_NAME}.`user` WHERE email = %s LIMIT 1;"

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
                # TODO: Optionally update password/username here if needed before re-sending OTP
                logger.info(
                    f"Unverified user {user.email} re-initiated registration.")

                # Trigger fresh Redis OTP & return early to move user to verification step
                code = f"{random.randint(100000, 999999)}"
                await set_verification_code(redis_key, code)

                background_tasks.add_task(
                    send_verification_email, user.email, code)

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
            params = (user.username, user.email, hash_password)

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
            await set_cache_user_id(username=user.username, user_id=user_id)

            # Generate & Send OTP for New Account
            code = f"{random.randint(100000, 999999)}"
            await set_verification_code(redis_key, code)
            background_tasks.add_task(
                send_verification_email, user.email, code)

            logger.info(
                f"User {user.username} created successfully (unverified)")
            return {
                "message": "User registered successfully. Please verify your email.",
                "userID": user_id,
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
async def verify_code(payload: VerifyCodeRequest,conn=Depends(get_session)):
    redis_key = f"verify:{payload.email}"
    cached_code = await get_verification_code(redis_key)
    
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
    
    await delete_verification_code(redis_key)
    token_data = {'sub': user_record['username'], 'v': user_record['token_v']}
    
    response = auth_token_response(
        token_data=token_data, msg="You've been logged in successfully")

    logger.info(f'{token_data['sub']} login successful')
    return response
    
    
@auth_router.post('/logout', status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(current_user: TokenData = Depends(get_current_user),
                       conn: Connection = Depends(get_session), users_jti: UserTokenJTI = Depends(get_current_user_jti)):
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
            await add_jti_block_list(users_jti)

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
async def get_new_access_token(token: RefreshTokenData = Depends(get_refresh_token)):
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

            await set_user_token_v(username=token_sub, version=token_version)

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
