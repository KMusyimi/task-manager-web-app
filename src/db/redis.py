from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
import redis.asyncio as redis # type: ignore
from src.config import settings

JTI_EXPIRY = 3600

redis_client = None


@asynccontextmanager
async def redis_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global redis_client
    redis_client = redis.StrictRedis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=0
    )
    try:
        await redis_client.ping()
        print("Redis connection established.")
        yield

    except redis.exceptions.ConnectionError as e:
        print(f"Failed to connect to Redis: {e}")
        yield

    finally:
        print("Closing Redis connection...")
        if redis_client:
            await redis_client.close()
            print("Redis connection closed.")


async def add_jti_block_list(jti: str) -> None:
    if redis_client:
        await redis_client.setex(jti, JTI_EXPIRY, 'REVOKED')


async def is_token_blacklisted(jti: str) -> bool:
    if redis_client:
        result = await redis_client.get(jti)
    return result is not None


async def cache_user_id(user_id: int):
    pass
