
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mysql.connector import Error
from src.db.database import get_session
from src.db import master_lifespan
from pytz import timezone
from asyncmy.cursors import DictCursor  # type: ignore
from asyncmy.connection import Connection  # type: ignore
from src.routes.auth_router import auth_router
from src.routes.projects_router import projects_router 
from src.routes.tasks_router import task_router 


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


tz = timezone('Africa/Nairobi')

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(task_router)


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



# @app.get('/api/{userID}/tasks')
# async def getAllUserTasks(userID: int, page_num: int, page_size: int = 30, filter_date=date.today()):
#     try:
#         with closing(pool.get_connection()) as conn:
#             with closing(conn.cursor(dictionary=True)) as cursor:
#                 params = (userID, filter_date, page_num, page_size)
#                 cursor.callproc('get_all_user_tasks', params)
#                 results = next(cursor.stored_results())
#                 return results.fetchall()

#     except Error as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong: {e}")


# @app.get('/api/{userID}/project/{projectID}/tasks')
# async def getTasksByProjectID(userID: int, projectID: int, page_num: int, page_size: int = 10, filter_date=date.today()):
#     with closing(pool.get_connection()) as conn:

#         with closing(conn.cursor(dictionary=True)) as cursor:
#             params = (userID, projectID, filter_date, page_num, page_size)
#             cursor.callproc('getTasksByProjectID', params)
#             results = next(cursor.stored_results())
#             return results.fetchall()


# @app.put('/api/{userID}/project/{projectID}/task/{taskID}')
# async def completeTask(userID: int, projectID: int, taskID: int):
#     try:
#         with closing(pool.get_connection()) as conn:

#             with conn.cursor(dictionary=True) as cursor:
#                 params = (userID, projectID, taskID)
#                 cursor.callproc('completeTaskByID', params)
#                 try:
#                     conn.commit()
#                     result = next(cursor.stored_results())
#                     return result.fetchone()
#                 except StopIteration:
#                     conn.rollback()
#                     raise HTTPException(
#                         status_code=status.HTTP_404_NOT_FOUND, detail=f"Task {taskID} doesn't exist in project {projectID}.")

#     except Error as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong: {e}")
