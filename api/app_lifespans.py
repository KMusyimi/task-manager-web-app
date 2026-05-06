from contextlib import AsyncExitStack, asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from api.sys_log import log_lifespan
from api.db.database import database_lifespan
from api.db.redis_backend import redis_lifespan


@asynccontextmanager
async def master_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(log_lifespan(app))
        await stack.enter_async_context(database_lifespan(app))
        await stack.enter_async_context(redis_lifespan(app))
        yield
