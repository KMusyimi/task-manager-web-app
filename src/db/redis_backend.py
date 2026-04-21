import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import redis.asyncio as redis  # pyright: ignore[reportMissingImports]
from fastapi import FastAPI
from redis import exceptions  # pyright: ignore[reportMissingImports]
from src.config import settings
from src.models.entities import UserTokenJTI

JTI_EXPIRY = 3600

redis_client = None
logger = logging.getLogger("users_logger")


@asynccontextmanager
async def redis_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global redis_client
    redis_client = redis.StrictRedis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=0,
        decode_responses=True
    )
    try:
        await redis_client.ping()
        logger.info("Redis connection established.")
        yield

    except exceptions.ConnectionError as e:
        logger.error(f"Failed to connect to Redis: {e}")
        yield
    except exceptions.RedisError as e:
        logger.error(f"Redis error occurred: {e}")
        yield

    finally:
        logger.info("Closing Redis connection...")
        if redis_client:
            await redis_client.close()
            logger.info("Redis connection closed.")


async def add_jti_block_list(jti: UserTokenJTI) -> None:
    if not redis_client:
        logger.warning("Redis client not initialized; skipping cache lookup.")
        return None

    for key, value in jti:
        KEY = f"{key}:{value}"
        await redis_client.setex(KEY, JTI_EXPIRY, 'REVOKED')
        logger.info(f'{KEY} successfully revoked')


async def is_token_blacklisted(key: str) -> Optional[bool]:
    if not redis_client:
        logger.warning("Redis client not initialized; skipping cache lookup.")
        return None

    result = await redis_client.get(key)
    return result is not None

# TODO: catch userID


async def set_user_token_v(username: str, version: int) -> None:
    KEY = f"user:{username}:token_v"
    if not redis_client:
        logger.warning("Redis client not initialized; skipping cache lookup.")
        return None

    # Set expiration to match your longest-lived Refresh Token (e.g., 7 days)
    # setex(KEY, EXPIRY IN SECONDS, VALUE)
    await redis_client.setex(KEY, 604800, version)
    logger.info(f'{KEY} successfully cached')


async def get_user_token_v(username: str) -> Optional[str]:
    KEY = f"user:{username}:token_v"
    if not redis_client:
        logger.warning("Redis client not initialized; skipping cache lookup.")
        return None

    token_v = await redis_client.get(KEY)
    logger.info(f'{KEY} successfully')
    return token_v


async def set_cache_user_id(username: str, user_id: int):
    logger.info(f'caching user:{username} id {user_id} ')
    KEY = f"user:{username}:id"
    if not redis_client:
        logger.warning("Redis client not initialized; skipping cache lookup.")
        return None

    logger.info(f'caching user:{username} successful')
    return await redis_client.set(KEY, user_id)


async def get_cache_user_id(username: str) -> Optional[int]:
    """Retrieves the database userID via the username."""
    logger.info(f'fetching cached user:{username} id')
    KEY = f"user:{username}:id"
    if not redis_client:
        logger.warning("Redis client not initialized; skipping cache lookup.")
        return None

    logger.info(f'fetching cached user:{username} successful')
    return await redis_client.get(KEY)


async def clear_all_user_cache(username: str) -> None:
    if not redis_client:
        logger.warning("Redis client not initialized; skipping cache lookup.")
        return None
    
    # This finds all keys starting with 'user:{username}:' and deletes them
    keys = await redis_client.keys(f"user:{username}:*")
    
    if keys:
        await redis_client.delete(*keys)
    else:
        logger.info(f"Cache miss for user: {username}")
        return None


async def update_username(user_id: int, old_username: str, new_username: str):
    # 2. Invalidate the old cache key immediately
    logger.info(f'updating cached user: {old_username}')
    
    if not redis_client:
        logger.warning("Redis client not initialized; skipping cache lookup.")
        return None
    
    logger.info(f'deleting cached user: {old_username} to {new_username}')
    await redis_client.delete(f"user:{old_username}:id")

    # 3. Optional: Warm the new cache
    await redis_client.setex(f"user:{new_username}:id", 3600, user_id)
    logger.info(f'updated cached user: {old_username} to {new_username}')


async def get_profile_url(username: str) -> Optional[str]:
    logger.info(f'fetching cached user: {username} profile')
    
    if not redis_client:
        logger.warning("Redis client not initialized; skipping cache lookup.")
        return None

    redis_key = f"user:{username}:profile_url"
    url = await redis_client.get(redis_key)

    if url:
        logger.info(f'fetched cached user: {username} profile url')
        return url

    logger.info(f'fetched cached user: {username} cache miss')
    return None


async def set_profile_url(username: str, new_url: str) -> Optional[str]:
    logger.info(f'setting cached user: {username} profile')
    if not redis_client:
        logger.warning("Redis client not initialized; skipping cache lookup.")
        return None

    redis_key = f"user:{username}:profile_url"
    await redis_client.setex(redis_key, 3600 * 24, new_url)  # 24-hour cache
    logger.info(f'set cached user: {username} profile url')


async def delete_profile_url(username: str) -> Optional[str]:
    logger.info(f'deleting cached user: {username} profile url')
    if not redis_client:
        logger.warning("Redis client not initialized; skipping cache lookup.")
        return None

    redis_key = f"user:{username}:profile_url"
    await redis_client.delete(redis_key)
    logger.info(f'deleted cached user: {username} profile url')
