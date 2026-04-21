from datetime import timedelta

from pydantic_settings import BaseSettings  # type: ignore


class Settings(BaseSettings):
    SECRET_KEY: str
    REFRESH_KEY: str
    ALGORITHM: str = 'HS256'
    ACCESS_TOKEN_MAX_AGE: int
    REFRESH_TOKEN_MAX_AGE: int
    REFRESH_TOKEN_RENEWAL_THRESHOLD: timedelta = timedelta(hours=24)
    REFRESH_TOKEN_COOKIE_NAME: str
    REFRESH_TOKEN_DOMAIN: str
    REDIS_HOST: str
    REDIS_PORT: int
    DB_HOST: str
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str
    DB_PORT: int
    class Config:
        env_file = '.env'


settings = Settings()
