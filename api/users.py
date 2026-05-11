import logging
from api.db.database import DB_NAME
import bcrypt  # type: ignore
from typing import Optional


from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import HTTPException, status
from mysql.connector import ProgrammingError
from passlib.context import CryptContext
from api.db.redis_backend import (get_cache_user_id, get_profile_url,
                                  set_cache_user_id)
from api.models.entities import UserCreate, UserInDb

logger = logging.getLogger("users_logger")

# This 'tricks' passlib into thinking bcrypt is an older, compatible version
if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = type('about', (object,), {
                            '__version__': bcrypt.__version__})

class Users():
    def __init__(self, pwd_context: CryptContext = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__ident="2b")) -> None:
        self.pwd_context = pwd_context

    def get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str | None) -> bool:
        return self.pwd_context.verify(plain_password, hashed_password)

    async def authenticate_user(self, cursor: DictCursor, username: str, password: str) -> UserInDb | None:
        user = await self.get_user_in_db(cursor, username)
        logger.info(f'{username} {user} authenticate user')
        if user is None:
            return None

        hashed_password = str(user.hashed_password)

        return None if not self.verify_password(password, hashed_password) else user

    async def is_authenticated_user(self, cursor: DictCursor, username: str, password: str) -> bool:
        user = await self.authenticate_user(cursor=cursor, username=username, password=password)
        return False if user is None else True

    async def get_user_in_db(self, cursor: DictCursor, credentials: str) -> UserInDb | None:
        params = (credentials,)

        logger.debug(f'{params}  authenticate user')
        await cursor.callproc('get_user_in_db', params)
        result = await cursor.fetchone()

        return UserInDb(**result) if result else None

    async def check_user_exists(self, cursor: DictCursor, user: UserCreate) -> bool:
        params = (user.username, user.email)
        user_id = await self.get_user_id(cursor, params)
        return user_id is not None

    async def get_user_id(self, cursor: DictCursor, *args) -> int | None:
        try:
            # Check if we received the nested tuple structure
            if args and isinstance(args[0], tuple):
                username = args[0][0]

            else:
                username = args[0]

            logger.debug(f'{username} args {args}')
            # cached user id
            c_user_id = await get_cache_user_id(username=username)

            if c_user_id is None:
                logger.info('fetching user id from database')

                user_record = await self.get_user_in_db(cursor=cursor, credentials=username)

                if user_record is None:
                    logger.info('fetching user record not found')
                    return None

                user_id = user_record.userID
                logger.info(f'fetch user record id {user_id} is found in db')

                await set_cache_user_id(username=username, user_id=user_id)
                return user_id

            return c_user_id

        except ProgrammingError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database configuration error or stored procedure not found."
            )
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database response format is incorrect. 'userID' key is missing.")

    async def get_user_profile_url(self, cursor: DictCursor, username: str) -> Optional[str]:
        logger.info(f'Getting user {username} profile url')
        cached_profile_url = await get_profile_url(username=username)

        if cached_profile_url is None:
            logger.info(f'Getting user {username} profile url from database')

            SELECT_STMT = f"""SELECT profile_img_url FROM {DB_NAME}.user 
            WHERE username = %(username)s"""

            await cursor.execute(SELECT_STMT, {'username': username})

            result = await cursor.fetchone()

            if not result or not result.get('profile_img_url'):
                return None

            db_profile_url = result['profile_img_url']
            return db_profile_url

        return cached_profile_url


users = Users()
