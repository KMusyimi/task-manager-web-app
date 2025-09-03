from fastapi import HTTPException, status
from passlib.context import CryptContext
from src.models.entities import User, UserInDB
from mysql.connector import ProgrammingError
from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore


class Users():
    def __init__(self, pwd_context: CryptContext = CryptContext(schemes=["bcrypt"], deprecated="auto")) -> None:
        self.pwd_context = pwd_context

    def get_password_hash(self, password: str) -> str:
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return self.pwd_context.verify(plain_password, hashed_password)

    async def authenticate_user(self, cursor: DictCursor, username: str, password: str) -> UserInDB | None:
        user = await self.get_user_in_db(cursor, username)
        if not user or not self.verify_password(password, user.hashed_password):
            return None
        return user

    async def get_user_in_db(self, cursor: DictCursor, credentials: str) -> UserInDB | None:
        params = (credentials,)
        await cursor.callproc('get_user_in_db', params)
        result = await cursor.fetchone()
        if not result:
            return None
        return UserInDB(**result)

    async def check_user_exists(self, cursor: DictCursor, user:User) -> bool:
        params = (user.username, user.email)
        user_id = await self.get_user_id(cursor, params)
        return user_id is not None

    async def get_user_id(self, cursor: DictCursor, *args) -> int | None:
        try:
            await cursor.callproc('get_user_id', *args)
            user = await cursor.fetchone()
            return user['userID'] if user else None

        except ProgrammingError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database configuration error or stored procedure not found."
            )
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database response format is incorrect. 'userID' key is missing.")

    async def register_user(self, conn: Connection, cursor: DictCursor, user: User) -> int:
        try:
            hashed_password = users.get_password_hash(user.password)
            params = (user.username, user.email, hashed_password)
            await cursor.callproc('create_user', params)
            await conn.commit()
            user = await cursor.fetchone()
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Database response format is incorrect. 'userID' key is missing.")
            return user['userID']
        except ProgrammingError as e:
            await conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Database error during user registration: {e}"
            )
        except Exception:
            await conn.rollback()
            raise


users = Users()
