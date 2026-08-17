import io
import logging
import cloudinary  # type: ignore
import cloudinary.uploader  # type: ignore
import asyncio
from concurrent.futures import ThreadPoolExecutor
import redis.asyncio as redis  # type: ignore

from fastapi.responses import JSONResponse

from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from mysql.connector import Error
from api.auth import REFRESH_TOKEN_COOKIE_NAME, REFRESH_TOKEN_DOMAIN, auth_token_response
from api.compress_profile_img import process_profile_img
from api.db.database import DB_NAME, get_session, get_session_context
from api.config import settings
from api.db.redis_backend import (get_redis, get_redis_context)
from api.models.entities import (TokenData, UploadResponse, UserChangePassword,
                                 UserGet, UserTokenJTI, UserUpdate)
from api.users import users
from api.utils import (get_current_user, get_current_user_jti,
                       validate_auth_creds, validate_change_password)


JTI_EXPIRY = 3600
BUILD = settings.BUILD
CLOUD_NAME = settings.CLOUDINARY_CLOUD_NAME
API_KEY = settings.CLOUDINARY_API_KEY
API_SECRET = settings.CLOUDINARY_API_SECRET

IS_LOCAL = BUILD == 'development'

user_router = APIRouter(prefix='/users/{username}', tags=['users'])

logger = logging.getLogger("users_logger")

cloudinary.config(
    cloud_name=CLOUD_NAME,
    api_key=API_KEY,
    api_secret=API_SECRET,
    secure=True
)

executor = ThreadPoolExecutor(max_workers=5)


async def upload_to_cloudinary(file_bytes: bytes, user_id: int):
    """
        This runs in the background. We use io.BytesIO to
        turn the raw bytes back into a file-like object for Cloudinary.
    """
    redis_key = None
    target_public_id = f"profile/user_{user_id}/avatar"

    try:
        # Define synchronous Cloudinary upload
        def _sync_upload():
            return cloudinary.uploader.upload(
                io.BytesIO(file_bytes),
                public_id=target_public_id,
                overwrite=True,
                invalidate=True,  # Purges CDN edge cache instantly
                transformation=[
                    {
                        "width": 400,
                        "height": 400,
                        "crop": "fill",
                        "gravity": "face",
                        "quality": "auto",
                        "fetch_format": "auto"
                    }
                ]
            )

        # Offload thread-blocking I/O call cleanly
        result = await asyncio.to_thread(_sync_upload)

        cloudinary_version = result.get("version")
        img_url = result.get("secure_url")

        logger.info(
            f"Cloudinary upload successful for user {user_id}: {img_url}")

        async with get_session_context() as conn:
            async with conn.cursor(cursor=DictCursor) as cursor:
                # Updating database stored procedure
                logger.debug(f"database conn established changing profile")
                change_profile_params = (user_id, img_url, cloudinary_version)
                await cursor.callproc('change_profile_image', change_profile_params)
                await conn.commit()

        async with get_redis_context() as redis_client:
            redis_key = f"user:{user_id}:profile_url"
            await redis_client.delete(redis_key)
            # 24-hour cache
            await redis_client.setex(redis_key, 3600 * 24, img_url)
            logger.info(f'set cached user: {user_id} profile url')

    except Exception:
        if redis_key:
            try:
                await redis_client.delete(redis_key)

            except Exception as redis_err:
                logger.error(
                    f"Failed to clear redis key '{redis_key}': {redis_err}")


@user_router.get('/profile', status_code=status.HTTP_200_OK, response_model=UserGet)
async def get_user_profile(conn: Connection = Depends(get_session),
                           current_user: TokenData = Depends(get_current_user)):
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            avatar_url = await users.get_avatar_url(cursor=cursor, user_id=user_id)


            select_stmt = f"""SELECT email, avatar_version, phone_number, bio, role, department, avatar_color, DATE_FORMAT(create_date, '%%M %%Y') AS 'joined_in'  from {DB_NAME}.user WHERE userID = %(user_id)s"""

            await cursor.execute(select_stmt, {'user_id': user_id})
            user_record = await cursor.fetchone()
            
            
            user_map = {'userID': user_id,
                        'username': current_user.sub,
                        'email': user_record.get('email'),
                        'profile_img_url': avatar_url,
                        'avatar_version': user_record.get('avatar_version'),
                        'bio': user_record.get('bio'),
                        'role': user_record.get('role'),
                        'phone_number': user_record.get('phone_number'),
                        'department': user_record.get('department'),
                        'avatar_color': user_record.get('avatar_color'),
                        'joined_in': user_record.get('joined_in')}

            return UserGet(**user_map)

    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while fetching profile.")


@user_router.post('/upload-profile', status_code=status.HTTP_200_OK, response_model=UploadResponse)
async def upload_profile_image(background_tasks: BackgroundTasks,
                               conn: Connection = Depends(get_session),
                               file_bytes: bytes = Depends(
                                   process_profile_img),
                               current_user: TokenData = Depends(get_current_user)):

    async with conn.cursor(cursor=DictCursor) as cursor:
        # Fetch user ID
        params = (current_user.sub, '')
        user_id = await users.get_user_id(cursor, params)

        if not user_id:
            logger.error(
                f"User {current_user.sub} not found for avatar upload.")
            return

    background_tasks.add_task(upload_to_cloudinary,
                              file_bytes=file_bytes, user_id=user_id)

    return {
        "success": True,
        "message": "Profile image uploaded successfully"
    }


@user_router.put('/edit-profile', status_code=status.HTTP_200_OK)
async def edit_profile(user: UserUpdate,
                       current_user: TokenData = Depends(get_current_user),
                       _: bool = Depends(validate_auth_creds),
                       conn: Connection = Depends(get_session),
                       redis_client: redis.Redis = Depends(get_redis),
                       token_jti: UserTokenJTI = Depends(get_current_user_jti)):
    try:
        async with conn.cursor(DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            await users.authenticate_user(cursor, current_user.sub, user.password)

            # returning a key and value of the fields required to be updated
            update_data = {
                key: value for key, value in user.model_dump().items() if value and key != 'password'
            }

            params_list = ", ".join(
                [f"IN p_{key} VARCHAR(255)" for key in update_data.keys()])

            set_clause = ", ".join([f"{key} = p_{key}" for key in update_data])

            create_proc = f"""
                CREATE PROCEDURE edit_user_profile(IN user_id INT, {params_list})
                BEGIN
                    UPDATE {DB_NAME}.user SET {set_clause} WHERE userID = user_id;
                    SELECT username FROM {DB_NAME}.user WHERE userID = user_id;
                END;
            """

            # creating my dynamic proc
            await cursor.execute(create_proc)
            # maintain the exact same order
            args = [user_id] + list(update_data.values())

            await cursor.callproc('edit_user_profile', args)

            user_record = await cursor.fetchone()

            # DROP the procedure immediately
            await cursor.execute("DROP PROCEDURE IF EXISTS edit_user_profile")
            await conn.commit()

            new_username = user_record.get('username')

            if current_user.sub != new_username:
                await redis_client.delete(f"user:{current_user.sub}:id")

                # Warm the new cache
                await redis_client.setex(f"user:{new_username}:id", 3600, user_id)

                logger.info(
                    f'updated cached user: {current_user.sub} to {new_username}')

            for key, value in token_jti:
                KEY = f"{key}:{value}"
                await redis_client.setex(KEY, JTI_EXPIRY, 'REVOKED')
                logger.info(f'{KEY} successfully revoked')

    except Error as e:
        logger.error(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while editing profile.")

    token_data = {'sub': new_username, 'v': current_user.version}

    response = auth_token_response(
        token_data=token_data, msg='Profile updated successfully')

    return response


@user_router.post('/change-password')
async def change_user_password(user: UserChangePassword,
                               conn: Connection = Depends(get_session),
                               current_user: TokenData = Depends(
                                   get_current_user),
                               redis_client: redis.Redis = Depends(get_redis),
                               token_jti: UserTokenJTI = Depends(get_current_user_jti)):
    try:
        logger.info(f'Change password {user}')
        async with conn.cursor(DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            await validate_change_password(cursor=cursor, username=current_user.sub, user=user)

            hashed_pw = users.get_password_hash(user.new_pw)

            await cursor.callproc('change_user_password', (user_id, hashed_pw))
            row = await cursor.fetchone()

            await conn.commit()

            for key, value in token_jti:
                KEY = f"{key}:{value}"
                await redis_client.setex(KEY, JTI_EXPIRY, 'REVOKED')
                logger.info(f'{KEY} successfully revoked')

            new_version = row['token_v']

            # caching the user token version on password change
            CACHE_KEY = f"user:{current_user.sub}:token_v"
            await redis_client.setex(CACHE_KEY, 604800, new_version)

    except Error as e:
        logger.error(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while editing profile.")

    except Exception as e:
        await conn.rollback()
        logger.error(f"change password error: {e}")
        raise e

    token_data = {'sub': current_user.sub, 'v': new_version}

    response = JSONResponse(
        content={
            "message": 'Password change successfully. You have been logged out from all devices.'},
        status_code=status.HTTP_200_OK)

    # deleting the users httponly cookie
    response.set_cookie(key=REFRESH_TOKEN_COOKIE_NAME,
                        value='',
                        httponly=True,
                        secure=True,
                        samesite="lax" if IS_LOCAL else "none",
                        domain=REFRESH_TOKEN_DOMAIN if IS_LOCAL else None,
                        max_age=-1)

    logger.info(
        f"User {token_data['sub']} token version {token_data['v']} change password and logout successful")

    return response
