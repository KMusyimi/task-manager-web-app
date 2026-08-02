from contextlib import asynccontextmanager
import logging
import os
from asyncmy.errors import OperationalError  # type: ignore
from asyncmy.pool import create_pool  # type: ignore
from fastapi import FastAPI, HTTPException, status
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

    ssl_ctx = ssl.create_default_context()

    if AIVEN_CA_PATH and os.path.exists(AIVEN_CA_PATH):
        try:
            ssl_ctx.load_verify_locations(cafile=AIVEN_CA_PATH)
            logger.info("Loaded custom Aiven CA certificate.")
        except Exception as e:
            logger.error(f"Failed to load custom CA file: {e}")
            raise
    else:
        # Allows connection encryption without failing if certificate path isn't present
        logger.warning(
            f"CA file not found at '{AIVEN_CA_PATH}'. Falling back to default TLS verification."
        )
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    return ssl_ctx


@asynccontextmanager
async def database_lifespan(_: FastAPI):
    global db_pool
    try:
        ssl_context = await get_ssl_context()
        db_pool = await create_pool(**mySqlConf, minsize=5, maxsize=10,
                                    pool_recycle=300,
                                    ssl=ssl_context)
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
            "Database pool not initialized. The 'lifespan' event must run first."
        )
        raise RuntimeError(
            "Database pool not initialized. The 'lifespan' event must run first."
        )

    async with db_pool.acquire() as conn:
        try:
            await conn.ping(reconnect=True)

        except (OperationalError, Exception) as e:
            logger.error(f"Database connection health check failed: {str(e)}")

            try:

                await conn.ensure_closed()
            except Exception:
                pass

            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database connection unavailable due to credential or network expiry."
            )

        yield conn
