import logging
import tracemalloc

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from mysql.connector import Error
from src.app_lifespans import master_lifespan
from src.routes.users_router import user_router
from src.db.database import get_session
from pytz import timezone
from asyncmy.cursors import DictCursor  # type: ignore
from asyncmy.connection import Connection  # type: ignore
from src.routes.auth_router import auth_router
from src.routes.projects_router import projects_router 
from src.routes.tasks_router import task_router 


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
    def __init__(self, *args, **kwargs):
        self.cache_max_age = kwargs.pop("cache_max_age", 31536000)
        super().__init__(*args, **kwargs)

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = f"public, max-age={self.cache_max_age}, immutable"
        return response


app.mount('/static', CacheStaticFiles(directory='static'), name='static')

tz = timezone('Africa/Nairobi')

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(task_router)
app.include_router(user_router)


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

