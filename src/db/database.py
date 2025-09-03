from contextlib import asynccontextmanager
from fastapi import FastAPI
from asyncmy.pool import create_pool  # type: ignore
from src.config import settings


mySqlConf = {
    "host": settings.DB_HOST,
    'db': settings.DB,
    "user": settings.USER,
    "password": settings.PASSWORD,
    'port': settings.PORT
}

db_pool = None


@asynccontextmanager
async def database_lifespan(app: FastAPI):
    global db_pool
    try:
        db_pool = await create_pool(**mySqlConf, minsize=1, maxsize=10)
        print("Database connection pool created.")
        yield
    finally:
        if db_pool:
            db_pool.close()
            await db_pool.wait_closed()
            print("Database connection pool closed.")


async def get_session():
    if db_pool is None:
        raise RuntimeError(
            "Database pool not initialized. The 'lifespan' event must run first.")

    async with db_pool.acquire() as conn:
        yield conn
