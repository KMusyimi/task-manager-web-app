import logging
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from pytz import timezone
from src.config import settings

SECRET_KEY = settings.SECRET_KEY
REFRESH_KEY = settings.REFRESH_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_MAX_AGE = settings.ACCESS_TOKEN_MAX_AGE

REFRESH_TOKEN_COOKIE_NAME = settings.REFRESH_TOKEN_COOKIE_NAME
REFRESH_TOKEN_MAX_AGE = settings.REFRESH_TOKEN_MAX_AGE  # 7 days/
REFRESH_TOKEN_DOMAIN = settings.REFRESH_TOKEN_DOMAIN
REFRESH_TOKEN_RENEWAL_THRESHOLD = settings.REFRESH_TOKEN_RENEWAL_THRESHOLD  # 24 hours

tz = timezone('Africa/Nairobi')
logger = logging.getLogger('uvicorn.access')

# TODO: refactor my code


def encode_token(payload: dict[str, object], key: str, expire_mins: timedelta):
    logger.info('encoding user token')
    to_encode = payload.copy()
    jti = str(uuid.uuid4())

    issued_at = datetime.now(tz)
    expire_at = datetime.now(tz) + expire_mins

    to_encode.update({'exp': expire_at, 'jti': jti, 'iat': issued_at})

    return jwt.encode(to_encode, key.encode(), algorithm=ALGORITHM)


def create_access_token(payload: dict[str, object]):
    logger.info(f'Creating access token for user {payload['sub']}')
    expire_at = timedelta(minutes=ACCESS_TOKEN_MAX_AGE)
    return encode_token(payload, SECRET_KEY, expire_at)


def create_refresh_token(payload: dict[str, object]):
    logger.info(f'Creating refresh token for user {payload['sub']}')
    expire_at = timedelta(minutes=REFRESH_TOKEN_MAX_AGE)
    return encode_token(payload, REFRESH_KEY, expire_at)


def verify_token(token: str, token_type: str = 'access'):
    try:
        logger.info(f'Decoding token {token_type}')
        KEY: str = SECRET_KEY if token_type == 'access' else REFRESH_KEY
        return jwt.decode(token, KEY.encode(), algorithms=[ALGORITHM], options={"verify_iat": True})

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={'WWW-Authenticate': "Bearer"})


def auth_token_response(token_data: dict[str, object], msg:str) -> JSONResponse:
    logger.debug(f'Auth token response')
    access_token = create_access_token(
        payload=token_data)

    refresh_token = create_refresh_token(
        payload={**token_data, 'refresh': True})

    user_sub = token_data.get('sub')
    if not isinstance(user_sub, str):
        # Handle the error case so 'response' is always defined
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid token data: 'sub' must be a string"}
        )
    
    logger.info(f'Processing auth token response for user {token_data['sub']}')

    response = JSONResponse(content={
        "username": user_sub,
        "message": msg,
        "accessToken": access_token,
        "tokenType": "bearer"})

    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        domain=REFRESH_TOKEN_DOMAIN,
        max_age=REFRESH_TOKEN_MAX_AGE
    )
    logger.info(f'User: {token_data['sub']} response success')
    return response
