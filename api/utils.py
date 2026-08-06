import logging
import random
import re
import string
from typing import Annotated, Union

from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import ValidationError
from pytz import timezone
from api.auth import verify_token
from api.db.database import DB_NAME, get_session
from api.db.redis_backend import (get_user_token_v, set_user_token_v)
from api.models.entities import (RefreshTokenData, TokenData, User,
                                 UserChangePassword, UserTokenJTI, UserUpdate)
from api.users import users

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token', auto_error=False)


def generate_otp() -> str:
    """Generates a random 6-digit OTP code."""
    return f"{random.randint(100000, 999999)}"

tz = timezone('Africa/Nairobi')
"""Validates if the provided email meets standard patterns."""
# Define a regex pattern for a valid email address
"""
    One or more allowed characters (A-Z,a-z,0-9,., _,-) before the @.
    A single @ symbol.
    One or more allowed characters for the domain name.
    A literal period (.).
    Two to four letters for the TLD (e.g., .com, .org).
"""

EMAIL_RGX_PATTERN = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
USERNAME_RGX_PATTERN = r"^[A-Za-z0-9_-]{5,20}$"
PASSWORD_RGX_PATTERN = r"(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[^\w\s]).{8,}"
logger = logging.getLogger("users_logger")


# TODO: move to auth.py


class TokenVerifier:
    def __init__(self, required_type: str) -> None:
        self.required_type = required_type

    async def __call__(self, conn: Connection = Depends(get_session), token: str = Depends(oauth2_scheme), refresh_token: Annotated[str | None, Cookie()] = None) -> dict:
        if self.required_type == 'access':
            if not token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid authentication credentials. Token {self.required_type.capitalize()}"
                )

            payload = verify_token(token, self.required_type)

            return payload

        else:
            if not refresh_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Access denied. Refresh token not found.",
                    headers={"WWW-Authenticate": "Bearer"})

            payload = verify_token(refresh_token, token_type='refresh')

        username = payload.get("sub")
        token_version = payload.get('v')

        if not isinstance(username, str):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload is invalid: missing user identification",
            )
        if token_version is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload is invalid: missing versioning",
            )

        await check_token_version(conn=conn, token_version=token_version, username=username)
        logger.info(f'user: {username} token version{token_version}')
        return payload


async def get_current_user(username: Union[str, None] = None, payload: dict = Depends(TokenVerifier('access'))):
    try:
        t_username = payload.get('sub')
        logger.info(f'getting user {t_username} access token')

        if username and t_username != username:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='Operation forbidden: The authenticated user does not match the requested resource.')

        token = TokenData(**payload)

    except ValidationError as e:
        logger.error(f'Error when validating token {str(e)}')
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f'Token claims missing or malformed. error: {str(e)}')

    return token


async def get_refresh_token(payload: dict = Depends(TokenVerifier('refresh'))) -> RefreshTokenData:
    t_username = payload.get('sub')
    logger.info(f'getting user {t_username} refresh token')
    try:
        refreshToken = RefreshTokenData(**payload)

    except ValidationError as e:
        logger.error(f'Error when validating token {e}')
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f'Refresh token claims missing or malformed {str(e)}.')

    return refreshToken


async def check_token_version(conn: Connection, token_version: int, username: str):
    # 1. Try fetching from Cache
    cached_version = await get_user_token_v(username=username)

    if cached_version is not None:
        if int(cached_version) != token_version:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User session invalid or password changed. Please login again."
            )
        # Cache hit and version matches -> Return early to avoid DB call
        return

    # 2. Cache Miss: Fallback to Database
    async with conn.cursor(DictCursor) as cursor:
        # Use parameterized query structure or default DB connection schema
        await cursor.execute(
            "SELECT token_v FROM user WHERE username = %s",
            (username,)
        )
        user_record = await cursor.fetchone()

        if not user_record or user_record['token_v'] != token_version:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User session invalid."
            )

        # 3. Re-hydrate Cache on valid DB lookup
        db_token_version = user_record['token_v']
        await set_user_token_v(username=username, version=db_token_version)


def get_current_user_jti(
    current_user: TokenData = Depends(get_current_user),
    refresh_user: RefreshTokenData = Depends(get_refresh_token)
) -> UserTokenJTI:
    """
    Extracts the JTI (JWT ID) from both the access and refresh tokens.
    """
    return UserTokenJTI(access_jti=current_user.jti,
                        refresh_jti=refresh_user.jti)


def _validate_with_regex(value: str, pattern: str, status_code: int, detail_message: str, is_pw: bool = False) -> bool:
    if not re.match(pattern, value):
        if is_pw:
            raise HTTPException(
                status_code=status_code,
                detail=detail_message,
                headers={"WWW-Authenticate": "Bearer"})
        else:
            raise HTTPException(
                status_code=status_code,
                detail=detail_message)
    return True


def validate_login_creds(form_data: OAuth2PasswordRequestForm = Depends()) -> OAuth2PasswordRequestForm:
    username = form_data.username

    is_valid_email = re.match(EMAIL_RGX_PATTERN, username)
    is_valid_username = re.match(USERNAME_RGX_PATTERN, username)

    if not (is_valid_email or is_valid_username):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            detail="Authorization failed. Invalid username or email format. Try again!!!")

    validate_password(password=form_data.password)

    return form_data


def validate_auth_creds(user: Union[User, UserUpdate]) -> bool:
    email = getattr(user, 'email', None)
    if email:
        validate_email(email)

    if isinstance(user, User):
        if user.username:
            validate_username(user.username)

    elif isinstance(user, UserUpdate):
        if user.username:
            validate_username(user.username)

    password = getattr(user, 'password', None)
    if password:
        validate_password(password)

    return True


def validate_password(password: str):
    return _validate_with_regex(
        is_pw=True,
        status_code=status.HTTP_401_UNAUTHORIZED,
        value=password,
        pattern=PASSWORD_RGX_PATTERN,
        detail_message="Authorization failed. Invalid password format. Try again!!!"
    )


def validate_username(username: str):
    return _validate_with_regex(
        status_code=status.HTTP_400_BAD_REQUEST,
        value=username,
        pattern=USERNAME_RGX_PATTERN,
        detail_message="Authorization failed. Invalid username format. Try again!!!"
    )


def validate_email(email: str):
    return _validate_with_regex(
        status_code=status.HTTP_400_BAD_REQUEST,
        value=email,
        pattern=EMAIL_RGX_PATTERN,
        detail_message="Authorization failed. Invalid email format. Try again!!!"
    )


def generate_random_str(length: int = 10):
    characters = string.ascii_letters + string.digits
    random_string = ''.join(random.choices(characters, k=length))
    return random_string


async def validate_change_password(cursor: DictCursor, user: UserChangePassword, username: str):
    current_pw = getattr(user, 'current_pw')
    new_pw = getattr(user, 'new_pw')
    confirm_pw = getattr(user, 'confirm_pw')
    
    await users.authenticate_user(cursor=cursor, username=username, password=current_pw)

    if new_pw != confirm_pw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New and confirmation password do not match."
        )
    if current_pw == new_pw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password cannot be the same as your current password."
        )

    _validate_with_regex(
        is_pw=True,
        status_code=status.HTTP_401_UNAUTHORIZED,
        value=new_pw,
        pattern=PASSWORD_RGX_PATTERN,
        detail_message="Authorization failed. Invalid new password format. Try again!!!")
