import logging

from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from mysql.connector import Error, ProgrammingError
from src.auth import auth_token_response
from src.compress_profile_img import process_profile_img
from src.db.database import get_session
from src.db.redis_backend import (add_jti_block_list, delete_profile_url,
                                  set_profile_url,
                                  set_user_token_v, update_username)
from src.models.entities import (TokenData, UploadResponse, UserChangePassword,
                                 UserGet, UserTokenJTI, UserUpdate)
from src.users import users
from src.utils import (get_current_user, get_current_user_jti,
                       validate_auth_creds, validate_change_password)

user_router = APIRouter(prefix='/users/{username}', tags=['users'])

logger = logging.getLogger("users_logger")


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

            select_stmt = """SELECT email, profile_img_url from todo_schema.user WHERE userID = %(user_id)s"""
            
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


@user_router.post('/upload', status_code=status.HTTP_200_OK, response_model=UploadResponse)
async def upload_profile_image(profile_image: UploadFile = File(...),
                               conn: Connection = Depends(get_session),
                               current_user: TokenData = Depends(get_current_user)):

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            NEW_PROFILE_URL = await process_profile_img(profile_image, user_id)

            await users.delete_old_profile_url(cursor=cursor,
                                               username=current_user.sub)

            change_profile_params = (user_id, NEW_PROFILE_URL)

            await cursor.callproc('change_profile_image', change_profile_params)
            await conn.commit()

            await set_profile_url(username=current_user.sub, new_url=NEW_PROFILE_URL)

            return {
                "success": True,
                "message": "Profile image uploaded successfully"
            }

    except ProgrammingError as e:
        await conn.rollback()
        await delete_profile_url(username=current_user.sub)

        logger.error(f"Upload error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during profile image url update: {e}"
        )
    except Exception as e:
        await conn.rollback()
        await delete_profile_url(username=current_user.sub)

        logger.error(f"Upload error: {e}")
        raise e

    finally:
        await profile_image.close()


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
                    UPDATE todo_schema.user SET {set_clause} WHERE userID = user_id;
                    SELECT username FROM todo_schema.user WHERE userID = user_id;
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


@user_router.put('/change-password')
async def change_user_password(user: UserChangePassword,
                               conn: Connection = Depends(get_session),
                               current_user: TokenData = Depends(
                                   get_current_user),
                               token_jti: UserTokenJTI = Depends(get_current_user_jti)):
    try:
        logger.info(f'{user}')
        async with conn.cursor(DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            await validate_change_password(cursor=cursor, username=current_user.sub, user=user)

            hashed_pw = users.get_password_hash(user.new_pw)

            await conn.callproc('change_user_password', (user_id, hashed_pw))
            row = await cursor.fetchone()
            await conn.commit()

            await add_jti_block_list(token_jti)

            new_version = row['token_v']
            # caching the user token version on password change
            await set_user_token_v(current_user.sub, version=new_version)

            token_data = {'sub': current_user.sub, 'v': new_version}
            response = auth_token_response(
                token_data=token_data, msg='Password change successfully. You have been logged out from all devices.')

            logger.info(
                f"User {token_data['sub']} token version {token_data['v']} change password successful")

            return response

    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while editing profile.")

    except Exception as e:
        logger.error(f"change password error: {e}")
        raise e
    
