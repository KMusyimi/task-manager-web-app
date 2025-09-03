from datetime import date
from typing import List

from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from mysql.connector import Error
from src.db.database import get_session
from src.models.entities import Task, TaskSelect, User
from src.users import users
from src.utils import get_current_user

task_router = APIRouter(prefix='/projects/{username}', tags=['tasks'])


@task_router.post('{project_id}/tasks')
async def add_tasks(username: str, project_id: int, task: Task,
                    conn: Connection = Depends(get_session),
                    current_user: User = Depends(get_current_user)):

    if (current_user.username != username):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='Operation forbidden: The authenticated user does not match the requested resource.')
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.username, '')
            user_id = await users.get_user_id(cursor, params)
            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")
            params = (user_id, project_id, task.title, task.description,
                      task.start_date, task.end_date, task.status_id, task.priority_id)
            await cursor.callproc('add_task', params)

            await conn.commit()

            task = await cursor.fetchone()

            return JSONResponse(content={'message': 'Task successfully created', "task": task})

    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while adding project.")


@task_router.get('/tasks', response_model=List[TaskSelect])
async def get_all_tasks(username: str,
                        conn: Connection = Depends(get_session),
                        current_user: User = Depends(get_current_user),
                        filter_date=date.today()):

    if (current_user.username != username):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='Operation forbidden: The authenticated user does not match the requested resource.')
    try:
        async with conn.cursor(DictCursor) as cursor:
            params = (current_user.username, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            params = (user_id, filter_date)
            await cursor.callproc('get_all_user_tasks', params)
            return await cursor.fetchall()

    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while creating task.")


@task_router.get('/{project_id}/tasks', response_model=List[TaskSelect])
async def get_project_tasks(username: str,
                            project_id: int,
                            conn: Connection = Depends(get_session),
                            current_user: User = Depends(get_current_user),
                            filter_date=date.today()):

    if (current_user.username != username):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='Operation forbidden: The authenticated user does not match the requested resource.')
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.username, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            params = (user_id, project_id, filter_date)
            await cursor.callproc('get_tasks_project_id', params)
            return await cursor.fetchall()

    except Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong: {e}")


@task_router.put('/{project_id}/tasks/{task_id}')
async def update_task(username: str,
                      project_id: int,
                      task_id: int,
                      task: Task,
                      conn: Connection = Depends(get_session),
                      current_user: User = Depends(get_current_user)):

    if (current_user.username != username):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='Operation forbidden: The authenticated user does not match the requested resource.')
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.username, '')
            user_id = await users.get_user_id(cursor, params)
            
            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")
            
            update_stmt = f"UPDATE todo_schema.tasks SET {task} WHERE taskID = %(task_id)s AND userID = %(user_id)s AND projectID = %(project_id)s"
            print(update_stmt)
            # await cursor.execute(update_stmt, {'task_id': task_id, 'user_id': user_id, 'project_id': project_id})
            
            # await conn.commit()
            
            return JSONResponse(content={'message': f'Task {task_id} successfully updated'})
    
    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong when updating task")
