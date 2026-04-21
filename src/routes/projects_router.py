
import logging
from datetime import date, datetime

from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from mysql.connector import Error
from pydantic import ValidationError
from src.db.database import get_session
from src.models.entities import (Project, ProjectAdd, ProjectResponse,
                                 ProjectsResponse, ProjectTaskGet,
                                 ProjectUpdate, TaskResponse, TokenData)
from src.users import users
from src.utils import get_current_user

projects_router = APIRouter(prefix='/projects/{username}', tags=['projects'])

logger = logging.getLogger("users_logger")


@projects_router.post('/', status_code=status.HTTP_201_CREATED, response_model=ProjectResponse)
async def add_project(
        project: ProjectAdd,
        conn: Connection = Depends(get_session),
        current_user: TokenData = Depends(get_current_user)):

    try:
        async with conn.cursor(DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            params = (user_id, project.project_name, project.color)
            await cursor.callproc('add_project', params)

            await conn.commit()

            project_record = await cursor.fetchone()

            project_model = Project(**project_record)

            return ProjectResponse(**{
                'projectID': project_model.projectID,
                'message': f'{project_model.project_name} added successfully'})

    except Error as e:
        logger.error(f"Database operation error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while creating project.")


@projects_router.post('/{project_id}/duplicate', status_code=status.HTTP_201_CREATED, response_model=ProjectResponse)
async def duplicate_project(
        project_id: int,
        conn: Connection = Depends(get_session),
        current_user: TokenData = Depends(get_current_user)):

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            await cursor.callproc('duplicate_user_project',
                                  (user_id, project_id))
            await conn.commit()

            project_record = await cursor.fetchone()
            project_model = Project(**project_record)

            return ProjectResponse(**{
                'projectID': project_model.projectID,
                'message': f'{project_model.project_name} duplicated successfully'})

    except ValidationError as e:
        logger.error(f'Error when validating model {e}')
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="An error occurred while duplicating project.")

    except Error as e:
        logger.error(f"Database operation error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while duplicating project.")


# TODO: add a response model
@projects_router.get('/', response_model=ProjectsResponse, status_code=status.HTTP_200_OK)
async def get_user_projects(conn: Connection = Depends(get_session),
                            current_user: TokenData = Depends(
                                get_current_user),
                            filter_date=date.today()):

    SELECT_STMT = "SELECT name FROM todo_schema.status;"
    projects_map = {}
    try:

        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            await cursor.callproc('get_user_projects_tasks', (user_id, filter_date))
            results = await cursor.fetchall()
            
            for result in results:
                
                project_id = result.get('projectID')

                if result.get('projectID') not in projects_map:
                    projects_map[project_id] = ProjectTaskGet(
                        **result)

                current_project = projects_map[project_id]
                
                if result.get('taskID') is not None:
                    task = TaskResponse(**result)

                    task.color = current_project.color
                    task.project_name = current_project.project_name

                    end_date = task.end_date

                    # Check if it's actually an object before formatting to avoid crashes
                    if isinstance(end_date, datetime):
                        task.display_date = end_date.strftime("%#d %B")

                    elif isinstance(end_date, str):
                        # task date in as a string
                        dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")
                        task.display_date = dt.strftime("%-d %B")
                    
                    else:
                        task.display_date = "No due date"

                    tasks = current_project.tasks
                    tasks.append(task)
     
            return ProjectsResponse(projects=list(projects_map.values()))

    except ValidationError as e:
        logger.error(f'Error when validating model {e}')
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="An error occurred while fetching projects.")

    except Error as e:
        logger.error(f"Database operation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while fetching projects.")

# TODO: change to patch from put


@projects_router.put('/{project_id}', status_code=status.HTTP_200_OK, response_model=ProjectResponse)
async def update_project(
        project_id: int,
        project: ProjectUpdate,
        conn: Connection = Depends(get_session),
        current_user: TokenData = Depends(get_current_user)):

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')

            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            update_data = {
                key: value for key, value in project.model_dump().items() if value
            }
            set_clause = ', '.join(
                [f"{key}=%({key})s" for key in update_data])

            # Dynamic query base on the updated fields only
            update_stmt = f'UPDATE todo_schema.projects SET {set_clause} WHERE projectID = %(project_id)s AND userID = %(user_id)s'

            params = {**update_data,
                      'project_id': project_id, "user_id": user_id}

            await cursor.execute(update_stmt, params)

            await conn.commit()

            return ProjectResponse(**{
                'message': f'Project update successful',
                'projectID': project_id})

    except ValidationError as e:
        logger.error(f'Error when validating model {e}')
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="An error occurred while updating projects.")

    except Error as e:
        logger.error(f"Database operation error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=500, detail=f"An error occurred while updating projects.")


@projects_router.delete('/{project_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
        project_id: int,
        conn: Connection = Depends(get_session),
        current_user: TokenData = Depends(get_current_user)):

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            delete_stmt = "DELETE from projects WHERE projectID = %(project_id)s AND userID = %(user_id)s"

            await cursor.execute(
                delete_stmt, {'project_id': project_id, 'user_id': user_id})
            await conn.commit()

            return JSONResponse(content={'message': f'Project deleted successfully'})

    except Error as e:
        logger.error(f"Database operation error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An error occurred while deleting projects.")
