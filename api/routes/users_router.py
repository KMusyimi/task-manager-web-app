import io
import logging
import cloudinary  # type: ignore
import cloudinary.uploader  # type: ignore

from fastapi.responses import JSONResponse

from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import APIRouter, Depends, HTTPException, status
from mysql.connector import Error, ProgrammingError
from api.auth import REFRESH_TOKEN_COOKIE_NAME, REFRESH_TOKEN_DOMAIN, auth_token_response
from api.compress_profile_img import process_profile_img
from api.db.database import DB_NAME, get_session
from api.config import settings
from api.db.redis_backend import (add_jti_block_list, delete_profile_url,
                                  set_profile_url,
                                  set_user_token_v, update_username)
from api.models.entities import (TokenData, UploadResponse, UserChangePassword,
                                 UserGet, UserTokenJTI, UserUpdate)
from api.users import users
from api.utils import (get_current_user, get_current_user_jti,
                       validate_auth_creds, validate_change_password)
from fastapi import BackgroundTasks

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


async def upload_to_cloudinary(file_bytes: bytes, conn: Connection, username: str):
    """
        This runs in the background. We use io.BytesIO to 
        turn the raw bytes back into a file-like object for Cloudinary.
    """
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (username, '')

            user_id = await users.get_user_id(cursor, params)

            logger.info(f'Uploading to cloudinary')
            result = cloudinary.uploader.upload(
                io.BytesIO(initial_bytes=file_bytes),
                folder=f'profile/user_{user_id}/',
                public_id="avatar",
                overwrite=True,
                invalidate=True,
                transformation=[
                    {"width": 400, "height": 400, "crop": "fill", "gravity": "face",
                     "quality": "auto", "fetch_format": "auto"}
                ]
            )
            logger.info(
                f"Upload successful for user {user_id}: {result['secure_url']}")
            IMG_URL = result.get("secure_url")
            change_profile_params = (user_id, IMG_URL)

            await set_profile_url(username=username, new_url=IMG_URL)

            await cursor.callproc('change_profile_image', change_profile_params)
            await conn.commit()

    except ProgrammingError as e:
        await delete_profile_url(username=username)
        await conn.rollback()

        logger.error(f"Upload error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during profile image url update: {e}"
        )

    except Exception as e:
        await delete_profile_url(username=username)
        await conn.rollback()

        logger.error(f"Upload error: {e}")
        raise e


@user_router.get('/profile', status_code=status.HTTP_200_OK, response_model=UserGet)
async def get_user_profile(conn: Connection = Depends(get_session), current_user: TokenData = Depends(get_current_user)):
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            select_stmt = f"""SELECT email, profile_img_url from {DB_NAME}.user WHERE userID = %(user_id)s"""

            await cursor.execute(select_stmt, {'user_id': user_id})
            user_record = await cursor.fetchone()

            user_map = {'userID': user_id,
                        'username': current_user.sub,
                        'email': user_record['email'],
                        'profile_img_url': user_record['profile_img_url']}

            return UserGet(**user_map)

    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while fetching profile.")


@user_router.post('/upload-profile', status_code=status.HTTP_200_OK, response_model=UploadResponse)
async def upload_profile_image(background_task: BackgroundTasks,
                               file_bytes: bytes = Depends(
                                   process_profile_img),
                               conn: Connection = Depends(get_session),
                               current_user: TokenData = Depends(get_current_user)):
    background_task.add_task(
        upload_to_cloudinary, file_bytes, conn, current_user.sub)

    return {
        "success": True,
        "status": "processing",
        "message": "Profile image uploaded successfully"
    }


@user_router.put('/edit-profile', status_code=status.HTTP_200_OK)
async def edit_profile(user: UserUpdate,
                       current_user: TokenData = Depends(get_current_user),
                       _: bool = Depends(validate_auth_creds),
                       conn: Connection = Depends(get_session),
                       token_jti: UserTokenJTI = Depends(get_current_user_jti)):
    try:
        async with conn.cursor(DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            is_authorized = await users.is_authenticated_user(cursor, current_user.sub, user.password)
            logger.info(f'user-> {user} {is_authorized}')

            if not is_authorized:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    headers={'WWW-Authenticate': 'Bearer'},
                    detail="Incorrect password. Try again!!!")
            # returning a key and value of the fields required to be updated
            update_data = {
                key: value for key, value in user.model_dump().items() if value and key != 'password'
            }
            logger.info(update_data)

            params_list = ", ".join(
                [f"IN p_{key} VARCHAR(155)" for key in update_data.keys()])

            set_clause = ", ".join([f"{key} = p_{key}" for key in update_data])

            create_proc = f"""
                CREATE PROCEDURE edit_user_profile(IN user_id INT, {params_list})
                BEGIN
                    UPDATE {DB_NAME}.user SET {set_clause} WHERE userID = user_id;
                    SELECT username FROM {DB_NAME}.user WHERE userID = user_id;
                END;
            """

            # create my dynamic proc
            await cursor.execute(create_proc)
            # maintain the exact same order
            args = [user_id] + list(update_data.values())

            await cursor.callproc('edit_user_profile', args)

            user_record = await cursor.fetchone()

            await add_jti_block_list(token_jti)

            # 5. DROP the procedure immediately
            await cursor.execute("DROP PROCEDURE IF EXISTS edit_user_profile")
            await conn.commit()

            new_username = user_record.get('username')

            await update_username(user_id=user_id, old_username=current_user.sub, new_username=new_username)

            token_data = {'sub': new_username, 'v': current_user.version}

            response = auth_token_response(
                token_data=token_data, msg='Profile updated successfully')

            return response

    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while editing profile.")


@user_router.post('/change-password')
async def change_user_password(user: UserChangePassword,
                               conn: Connection = Depends(get_session),
                               current_user: TokenData = Depends(
                                   get_current_user),
                               token_jti: UserTokenJTI = Depends(get_current_user_jti)):
    try:
        logger.info(f'Change password{user}')
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

            await add_jti_block_list(token_jti)

            new_version = row['token_v']
            # caching the user token version on password change
            await set_user_token_v(current_user.sub, version=new_version)

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

    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while editing profile.")

    except Exception as e:
        await conn.rollback()
        logger.error(f"change password error: {e}")
        raise e
