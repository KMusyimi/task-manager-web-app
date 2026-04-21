import logging
from datetime import datetime

from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from mysql.connector import Error
from pytz import timezone
from src.auth import (REFRESH_TOKEN_COOKIE_NAME, REFRESH_TOKEN_DOMAIN,
                      REFRESH_TOKEN_MAX_AGE, REFRESH_TOKEN_RENEWAL_THRESHOLD, auth_token_response,
                      create_access_token, create_refresh_token)
from src.db.database import get_session
from src.db.redis_backend import add_jti_block_list, set_cache_user_id, set_user_token_v
from src.models.entities import RefreshTokenData, TokenData, User, UserCreate, UserTokenJTI
from src.users import users
from src.utils import (get_current_user, get_current_user_jti,
                       get_refresh_token, validate_auth_creds,
                       validate_login_creds)

# TODO: user routes
auth_router = APIRouter(prefix='/auth', tags=['auth'])
tz = timezone('Africa/Nairobi')

logger = logging.getLogger('users_logger')


@auth_router.post('/login', status_code=status.HTTP_200_OK)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm =
                                 Depends(validate_login_creds),
                                 conn: Connection = Depends(get_session)):
    logger.debug('[FUNC] login for access token')
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:

            login_user = await users.authenticate_user(
                cursor, form_data.username, form_data.password)

            if not login_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials. Check username or password.",
                    headers={"WWW-Authenticate": "Bearer"})

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
async def create_user(user: UserCreate,
                      _: bool = Depends(validate_auth_creds),
                      conn: Connection = Depends(get_session)):
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            existing_user = await users.check_user_exists(
                cursor, user)

            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Username or email already exists")

            hash_password = users.get_password_hash(password=user.password)

            params = (user.username, user.email, hash_password)

            await cursor.callproc('create_user', params)

            await conn.commit()

            user_record = await cursor.fetchone()
            logger.info(user_record)
            if user_record is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database response format is incorrect. 'userID' key is missing.")

            user_id = user_record['userID']

            await set_cache_user_id(username=user.username, user_id=user_id)

            logger.info(f'User {user.username} created successfully')
            return {"message": "User created successfully", "userID": user_id}

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


@auth_router.post('/logout', status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(users_jti: UserTokenJTI = Depends(get_current_user_jti)):
    try:
        logger.info(f'{type(users_jti)}')
        await add_jti_block_list(users_jti)

        # TODO: check increment
        # UPDATE_STATEMENT = """UPDATE todo_schema.user SET hashed_password = %,
        #         token_version = token_version + 1 (hashed_password)s WHERE userID=%(user_id)
        #         RETURNING token_version"""

        # await conn.execute(UPDATE_STATEMENT, {'hashed_password': hashed_pw, 'user_id': user_id})
        response = JSONResponse(
            content={"message": "You've been logged out successfully."},
            status_code=status.HTTP_200_OK)
        # deleting the logout users httponly cookie
        response.set_cookie(key=REFRESH_TOKEN_COOKIE_NAME,
                            value='',
                            httponly=True,
                            secure=True,
                            samesite="lax",
                            domain=REFRESH_TOKEN_DOMAIN,
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
                samesite="lax",
                domain=REFRESH_TOKEN_DOMAIN,
                max_age=REFRESH_TOKEN_MAX_AGE
            )

        return response

    except Error as e:
        logger.error(f"Server refresh token error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh user token due to a server error")
