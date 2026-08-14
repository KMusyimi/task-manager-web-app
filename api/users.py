import logging
from api.db.database import DB_NAME
import bcrypt  # type: ignore
from typing import Optional
import redis.asyncio as redis  # type: ignore


from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import HTTPException, status
from mysql.connector import ProgrammingError
from passlib.context import CryptContext  # type: ignore
from api.db.redis_backend import (get_redis_context)
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

    async def authenticate_user(self, cursor: DictCursor, username: str, password: str) -> UserInDb:
        logger.info(f'Authenticating user')

        user = await self.get_user_in_db(cursor, username)
        logger.info(f'{username} {user} authenticate user')

        hashed_password = str(user.hashed_password)
        if not self.verify_password(password, hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={'WWW-Authenticate': 'Bearer'},
                detail="Invalid password. Check password")

        return user

    async def get_user_in_db(self, cursor: DictCursor, credentials: str) -> UserInDb:
        params = (credentials,)

        logger.debug(f'{params}  authenticate user')
        await cursor.callproc('get_user_in_db', params)
        result = await cursor.fetchone()

        if not result:
            logger.warning(
                f"Auth failed: User {credentials} not found in DB.")

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Authorization failed: User not found check your credentials"
            )

        return UserInDb(**result)

    async def check_user_exists(self, cursor: DictCursor, user: UserCreate) -> bool:
        try:
            params = (user.username, user.email)
            user_id = await self.get_user_id(cursor, params)
            return user_id is not None

        except HTTPException:
            return False

    async def get_user_id(self, cursor: DictCursor, *args) -> int:
        try:
            # Check if we received the nested tuple structure
            if args and isinstance(args[0], tuple):
                username = args[0][0]

            else:
                username = args[0]

            REDIS_KEY = f"user:{username}:id"
            logger.debug(f'{username} args {args}')
            # cached user id
            async with get_redis_context() as redis_client:
                c_user_id = await redis_client.get(REDIS_KEY)
                logger.info(f'fetching cached user:{username} successful')

            if c_user_id:
                return int(c_user_id)

            logger.info('fetching user id from database')

            user_record = await self.get_user_in_db(cursor=cursor, credentials=username)

            user_id = user_record.userID
            logger.info(f'fetch user record id {user_id} is found in db')


            await redis_client.set(REDIS_KEY, user_id)
            logger.info(f'caching user:{username} successful')
            return int(user_id)

        except ProgrammingError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database configuration error or stored procedure not found."
            )
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database response format is incorrect. 'userID' key is missing.")

    async def get_avatar_url(self, cursor: DictCursor, user_id: int) -> Optional[str]:
        logger.info(f'Getting user {user_id} profile url')

        SELECT_STMT = f"""SELECT profile_img_url FROM {DB_NAME}.user 
        WHERE userID = %(userID)s"""
        async with get_redis_context() as redis_client:
            redis_key = f"user:{user_id}:profile_url"
            cached_avatar_url = await redis_client.get(redis_key)

        if cached_avatar_url:
            logger.info(f'fetched cached user: {user_id} profile url')
            return cached_avatar_url

        logger.info(f'fetched cached user: {user_id} cache miss')

        await cursor.execute(SELECT_STMT, {'userID': user_id})

        logger.info(f'Getting user {user_id} profile url from database')
        result = await cursor.fetchone()

        if not result or not result.get('profile_img_url'):
            return None

        db_avatar_url = result['profile_img_url']
        
        await redis_client.setex(redis_key, 3600 * 24, db_avatar_url)
        logger.info(f'set cached user: {user_id} profile url')
        
        return db_avatar_url


users = Users()
