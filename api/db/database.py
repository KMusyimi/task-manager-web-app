from contextlib import asynccontextmanager
import logging
from asyncmy.pool import create_pool  # type: ignore
from fastapi import FastAPI
from api.config import settings


DB_HOST = settings.DB_HOST
DB_NAME = settings.DB_NAME
DB_USER = settings.DB_USER
DB_PASSWORD = settings.DB_PASSWORD
DB_PORT = settings.DB_PORT

mySqlConf = {
    "host": DB_HOST,
    'db': DB_NAME,
    "user": DB_USER,
    "password": DB_PASSWORD,
    'port': DB_PORT
}
logger = logging.getLogger("users_logger")
db_pool = None


@asynccontextmanager
async def database_lifespan(_: FastAPI):
    global db_pool
    try:
        db_pool = await create_pool(**mySqlConf, minsize=1, maxsize=10)
        logger.info("Database connection pool created.")
        yield
    finally:
        if db_pool:
            db_pool.close()
            await db_pool.wait_closed()
            logger.info("Database connection pool closed.")


async def get_session():
    if db_pool is None:
        logger.error(
            "Database pool not initialized. The 'lifespan' event must run first.")
        raise RuntimeError(
            "Database pool not initialized. The 'lifespan' event must run first.")

    async with db_pool.acquire() as conn:
        yield conn
