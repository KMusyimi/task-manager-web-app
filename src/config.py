from pydantic_settings import BaseSettings # type: ignore


class Settings(BaseSettings):
    SECRET_KEY: str
    REFRESH_KEY: str 
    ALGORITHM: str = 'HS256'
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    REDIS_HOST: str = 'localhost'
    REDIS_PORT: int = 6379
    DB_HOST:str = 'localhost'
    DB :str= "todo_schema"
    USER:str = 'root'
    PASSWORD:str = "Musyimi7."
    PORT:int = 3307
    
    
    class Config:
        env_file = '.env'


settings = Settings()
