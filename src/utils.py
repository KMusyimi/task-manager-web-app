import logging
import random
import re
import secrets
import string
from typing import Annotated, Any, Union

from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import ValidationError
from pytz import timezone
from src.auth import verify_token
from src.db.database import get_session
from src.db.redis_backend import (get_user_token_v, is_token_blacklisted,
                                  set_user_token_v)
from src.models.entities import (RefreshTokenData, TokenData, User,
                                 UserChangePassword, UserTokenJTI, UserUpdate)
from src.users import users

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')
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


def create_random_session_string() -> str:
    # Generates a random URL-safe string
    return secrets.token_hex(32)


async def get_current_user(username: Union[str, None] = None, token: str = Depends(oauth2_scheme), conn: Connection = Depends(get_session), token_type: str = 'access'):
    try:
        payload = verify_token(token, token_type)

        if username is not None and 'sub' in payload:
            token_sub = payload['sub']
            if token_sub != username:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail='Operation forbidden: The authenticated user does not match the requested resource.')

    except HTTPException as e:
        raise e

    except Exception as e:
        logger.error(f'invalid {e}')
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials."
        ) from e

    token_data = await get_token_data(conn=conn, payload=payload)

    return TokenData.model_validate(token_data)


async def get_refresh_token(refresh_token: Annotated[str | None, Cookie()] = None, conn: Connection = Depends(get_session)) -> RefreshTokenData:
    logger.info('Refreshing user token')
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access denied. Refresh token not found.",
            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = verify_token(refresh_token, token_type='refresh')
    except HTTPException:
        raise

    except Exception as e:
        logger.error(f'invalid credentials {e}')
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials."
        ) from e

    token_data = await get_token_data(conn=conn, payload=payload)

    return RefreshTokenData.model_validate(token_data)


async def check_token_version(conn: Connection, token_data: Union[TokenData, RefreshTokenData]):

    token_version = token_data.version
    cached_version = await get_user_token_v(username=token_data.sub)

    if cached_version is not None:
        if int(cached_version) != token_version:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Password changed. Please login again.")
        return
    # database fallback
    async with conn.cursor(DictCursor) as cursor:
        await cursor.execute("SELECT token_v FROM todo_schema.user WHERE username = %s", (token_data.sub,))
        user_record = await cursor.fetchone()

        if not user_record or user_record['token_v'] != token_version:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,  detail="Session invalid.")

        await set_user_token_v(username=token_data.sub, version=user_record['token_v'])


async def get_token_data(conn: Connection, payload: dict[str, Any]):
    try:
        if 'refresh' not in payload:
            token_data = TokenData(**payload)
            cache_key = f"access_jti:{token_data.jti}"

        else:
            token_data = RefreshTokenData(**payload)
            cache_key = f"refresh_jti:{token_data.jti}"

        await check_token_version(conn=conn, token_data=token_data)

        if await is_token_blacklisted(cache_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or revoked token",
                headers={'WWW-Authenticate': "Bearer"})

    except ValidationError as e:
        logger.error(f'Error when validating token {e}')
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Token claims missing or malformed')

    return token_data


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
    is_authorized = await users.is_authenticated_user(cursor=cursor, username=username, password=current_pw)

    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={'WWW-Authenticate': 'Bearer'},
            detail="Incorrect password. Try again!!!")

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
