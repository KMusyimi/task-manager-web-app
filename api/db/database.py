from contextlib import asynccontextmanager
import logging
import os
from asyncmy.pool import create_pool  # type: ignore
from fastapi import FastAPI
from api.config import settings
import ssl

DB_HOST = settings.DB_HOST
DB_NAME = settings.DB_NAME
DB_USER = settings.DB_USER
DB_PASSWORD = settings.DB_PASSWORD
DB_PORT = settings.DB_PORT
BUILD = settings.BUILD
AIVEN_CA_PATH = settings.AIVEN_CA_CERT_PATH

mySqlConf = {
    "host": DB_HOST,
    'db': DB_NAME,
    "user": DB_USER,
    "password": DB_PASSWORD,
    'port': DB_PORT
}
logger = logging.getLogger("users_logger")
db_pool = None

IS_LOCAL = BUILD == 'development'


async def get_ssl_context():
    if IS_LOCAL:
        return None

    ca_path = AIVEN_CA_PATH

    if not os.path.exists(ca_path):
        logger.error(f"SSL Certificate not found at {ca_path}")
        return None

    try:
        ssl_ctx = ssl.create_default_context(cafile=ca_path)
        
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_REQUIRED

        logger.info("SSL Context initialized successfully for Aiven.")
        return ssl_ctx
    except Exception as e:
        logger.error(f"Failed to create SSL context: {e}")
        raise


@asynccontextmanager
async def database_lifespan(_: FastAPI):
    global db_pool
    try:
        db_pool = await create_pool(**mySqlConf, minsize=5, maxsize=10, 
                                    pool_recycle=3600,
                                    ssl=await get_ssl_context())
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
