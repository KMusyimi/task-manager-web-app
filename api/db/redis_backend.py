import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import redis.asyncio as redis  # pyright: ignore[reportMissingImports]
from fastapi import FastAPI
from redis import exceptions  # pyright: ignore[reportMissingImports]
from api.config import settings


REDIS_URL = settings.REDIS_URL


logger = logging.getLogger("users_logger")

redis_client = None


@asynccontextmanager
async def redis_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global redis_client
    try:
        redis_client = redis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True
        )
        await redis_client.ping()
        logger.info("Redis connection established.")
        yield
        
    except exceptions.RedisError as e:
        logger.error(f"Redis initialization failed: {e}")
        redis_client = None
        yield
        
        
    finally:
        logger.info("Closing Redis connection...")
        if getattr(app.state, "redis", None):
            assert redis_client is not None
            await redis_client.close()
            logger.info("Redis connection closed.")


async def get_redis() -> AsyncGenerator[redis.Redis, None]:
    if redis_client is None:
        raise RuntimeError("Redis client is not initialized.")
    yield redis_client

# background task redis client context
get_redis_context = asynccontextmanager(get_redis)

