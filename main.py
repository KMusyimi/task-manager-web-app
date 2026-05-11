import logging
import os
import tracemalloc

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from mysql.connector import Error
import uvicorn
from api.app_lifespans import master_lifespan
from api.routes.users_router import user_router
from api.db.database import get_session
from pytz import timezone
from asyncmy.cursors import DictCursor  # type: ignore
from asyncmy.connection import Connection  # type: ignore
from api.routes.auth_router import auth_router
from api.routes.projects_router import projects_router 
from api.routes.tasks_router import task_router 


logger = logging.getLogger('uvicorn.access')

tracemalloc.start()
origins = [
    "http://localhost:5173",
    "http://localhost:8080",
]

app = FastAPI(docs_url="/api/py/docs", lifespan=master_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CacheStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        # 1 year cache for static UI elements
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

# serves my static files
app.mount('/static', CacheStaticFiles(directory='static'), name='static')

tz = timezone('Africa/Nairobi')

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(task_router)
app.include_router(user_router)


@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/api/recommendations")
async def getRecommendations(conn: Connection = Depends(get_session)):
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            getRecommendations = """SELECT id, title FROM recommendations ORDER BY id ASC LIMIT %(limit)s OFFSET %(offset)s"""
            await cursor.execute(getRecommendations, {
                'limit': 15, 'offset': 0})
            return await cursor.fetchall()

    except Error as e:
        raise HTTPException(
            status_code=500, detail=f"Something went wrong: {e}")
