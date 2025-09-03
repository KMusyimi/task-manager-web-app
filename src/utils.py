import re
import secrets
from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from pytz import timezone
from src.auth import verify_token
from src.db.redis import add_jti_block_list, is_token_blacklisted
from src.models.entities import TokenData, TokenDetails

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')
tz = timezone('Africa/Nairobi')


def create_random_session_string() -> str:
    return secrets.token_urlsafe(32)  # Generates a random URL-safe string


async def get_current_user(token: str = Depends(oauth2_scheme), token_type: str = 'access'):
    try:
        payload = verify_token(token, token_type)
    
    except HTTPException:
        raise
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials."
        ) from e
    
    try:
        jti = payload['jti']
        username = payload['sub']
    
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid authentication credentials'
        )

    if await is_token_blacklisted(jti):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or revoked token",
            headers={'WWW-Authenticate': "Bearer"}
        )

    return TokenData(username=username, jti=jti)
    


async def get_current_refresh_user(request: Request):
    try:
        refresh_token = get_refresh_token(request)
        payload = verify_token(refresh_token, token_type='refresh')
    
    except HTTPException:
        # Re-raise HTTPException from get_refresh_token or verify_token
        raise
    
    except Exception as e:
        # Catch any other unexpected errors during token processing
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials."
        ) from e

    try:
        jti = payload['jti']
        username = payload['sub']
        expiring_date = payload['exp']
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Token claims missing or malformed'
        )

    if await is_token_blacklisted(jti):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or revoked token",
            headers={'WWW-Authenticate': "Bearer"}
        )
    return TokenDetails(jti=jti, username=username, expiring_date=expiring_date)


async def revoke_refresh_token(jti: str):
    if jti is not None:
        await add_jti_block_list(jti=jti)


def get_refresh_token(request: Request) -> str:
    try:
        refresh_token = request.cookies["refresh-Token"]
        return refresh_token
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access denied. Refresh token not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def validate_email(email):
    """Validates if the provided email meets standard patterns."""
    # Define a regex pattern for a valid email address
    email_pattern = r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"
    # Use re.match to verify if the email fits the pattern
    return bool(re.match(email_pattern, email))


class DictToObject():
    def __init__(self, dictionary: dict) -> None:
        for key, value in dictionary.items():
            setattr(self, key, value)
