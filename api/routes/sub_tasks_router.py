
import json
import logging
from typing import List

from fastapi import APIRouter

from api.models.entities import CreateSubtaskList, SubTaskResponseSchema, ToggleSubtask, TokenData

from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import APIRouter, Depends, HTTPException, status

from api.utils import get_current_user
from api.db.database import DB_NAME, get_session
from api.users import users
from mysql.connector import Error


logger = logging.getLogger("users_logger")
sub_task_router = APIRouter(
    prefix='/projects/{username}/tasks/{task_id}/sub-tasks', tags=['SubTasks'])


@sub_task_router.post('/', status_code=status.HTTP_201_CREATED)
async def create_subtasks(task_id: int, payload: CreateSubtaskList, conn:  Connection = Depends(get_session), current_user: TokenData = Depends(get_current_user)):
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            subtasks_json_string = json.dumps(
                [subtask.model_dump() for subtask in payload.subtasks])

            st_params = (user_id, task_id, subtasks_json_string)

            await cursor.callproc('add_subtasks', st_params)
            await conn.commit()

            return {
                "status": "success",
                "message": f"Successfully added {len(payload.subtasks)} subtasks to task {task_id} for user {user_id}."
            }

    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong when creating sub task {str(e)}")


@sub_task_router.patch('/toggle', status_code=status.HTTP_200_OK)
async def complete_subtask(task_id: int,
                           payload: ToggleSubtask,
                           conn: Connection = Depends(get_session),
                           current_user: TokenData = Depends(get_current_user)):

    query = f"UPDATE {DB_NAME}.sub_tasks SET is_completed = %s WHERE userID = %s AND taskID = %s AND subTaskID = %s"

    logger.debug(f"Sub tasks route and this is {payload}")
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)


            await cursor.execute(query, (payload.is_completed, user_id, task_id,payload.subTaskID ))

            await conn.commit()

            return {
                "status": "success",
                "message": f"Successfully {'completed' if payload.is_completed else 'undone completed'} subtask {payload.subTaskID}."
            }

    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong when toggling sub task {str(e)}")


@sub_task_router.get('/', status_code=status.HTTP_200_OK, response_model=List[SubTaskResponseSchema])
async def get_sub_tasks(task_id: int, conn: Connection = Depends(get_session), current_user: TokenData = Depends(get_current_user)):
    query = f"""
        SELECT st.subTaskID, st.taskID, st.title, st.is_completed, st.position 
        FROM {DB_NAME}.sub_tasks st
        INNER JOIN {DB_NAME}.tasks t ON st.taskID = t.taskID
        WHERE st.taskID = %(task_id)s AND st.userID = %(user_id)s
        ORDER BY st.position ASC;
    """
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            await cursor.execute(query, {"task_id": task_id, "user_id": user_id})
            result = await cursor.fetchall()

            if not result:
                return []

            return result

    except Error as e:
        print(f"Database error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong when fetching sub task {str(e)}")




