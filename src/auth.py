import uuid
from datetime import datetime, timedelta
from jose import JWTError, jwt
from src.config import settings
from fastapi import HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pytz import timezone

SECRET_KEY = settings.SECRET_KEY
REFRESH_KEY = settings.REFRESH_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_MINUTES = settings.REFRESH_TOKEN_EXPIRE_MINUTES

oauth_scheme = OAuth2PasswordBearer(tokenUrl='token')
tz = timezone('Africa/Nairobi')


# TODO: refactor my code
def create_token(data: dict, key: str, expire_mins: timedelta):
    jti = str(uuid.uuid4())
    to_encode = data.copy()
    expire_at = datetime.now(tz) + expire_mins
    to_encode.update({'exp': expire_at, 'jti': jti})
    return jwt.encode(to_encode, key, algorithm=ALGORITHM)


def create_access_token(data: dict):
    expire_at = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return create_token(data, SECRET_KEY, expire_at)


def create_refresh_token(data: dict):
    expire_at = timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES)
    return create_token(data, REFRESH_KEY, expire_at)


def verify_token(token: str, token_type: str = 'access'):
    try:
        KEY: str = SECRET_KEY if token_type == 'access' else REFRESH_KEY
        return jwt.decode(token, KEY, algorithms=[ALGORITHM])

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={'WWW-Authenticate': "Bearer"})

