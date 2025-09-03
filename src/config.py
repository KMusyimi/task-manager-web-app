from pydantic_settings import BaseSettings  # type: ignore


class Settings(BaseSettings):
    SECRET_KEY: str
    REFRESH_KEY: str
    ALGORITHM: str = 'HS256'
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    REDIS_HOST: str
    REDIS_PORT: int
    DB_HOST: str
    DB_NAME: str
    DB_USER: str
    MYSQL_PASSWORD: str
    DB_PORT: int

    class Config:
        env_file = '.env'


settings = Settings()
