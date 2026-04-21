from contextlib import asynccontextmanager
import logging
from asyncmy.pool import create_pool  # type: ignore
from fastapi import FastAPI
from src.config import settings

mySqlConf = {
    "host": settings.DB_HOST,
    'db': settings.DB_NAME,
    "user": settings.DB_USER,
    "password": settings.DB_PASSWORD,
    'port': settings.DB_PORT
}
logger = logging.getLogger("users_logger")
db_pool = None


@asynccontextmanager
async def database_lifespan(app: FastAPI):
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
        logger.error("Database pool not initialized. The 'lifespan' event must run first.")
        raise RuntimeError(
            "Database pool not initialized. The 'lifespan' event must run first.")

    async with db_pool.acquire() as conn:
        yield conn
