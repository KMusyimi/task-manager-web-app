
import logging
from typing import List


from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from mysql.connector import Error
from pydantic import ValidationError
from api.db.database import DB_NAME, get_session
from api.models.entities import (Project, ProjectAdd, ProjectGetResponse, ProjectSuccessResponse,
                                 ProjectUpdate, TokenData)
from api.users import users
from api.utils import get_current_user

projects_router = APIRouter(prefix='/projects/{username}', tags=['projects'])

logger = logging.getLogger("users_logger")


@projects_router.post('/', status_code=status.HTTP_201_CREATED, response_model=ProjectSuccessResponse)
async def add_project(
        project: ProjectAdd,
        conn: Connection = Depends(get_session),
        current_user: TokenData = Depends(get_current_user)):

    try:
        async with conn.cursor(DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            params = (user_id, project.project_name, project.color)
            await cursor.callproc('add_project', params)
            
            project_record = await cursor.fetchone()

            if not project_record:
                await conn.rollback()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to retrieve newly created project."
                )
                
            await conn.commit()


            project_model = Project(**project_record)

            return ProjectSuccessResponse(**{
                'projectID': project_model.projectID,
                'message': f'{project_model.project_name} added successfully'})

    except Error as e:
        logger.error(f"Database operation error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while creating project.")


@projects_router.post('/{project_id}/duplicate', status_code=status.HTTP_201_CREATED, response_model=ProjectSuccessResponse)
async def duplicate_project(
        project_id: int,
        conn: Connection = Depends(get_session),
        current_user: TokenData = Depends(get_current_user)):

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            await cursor.callproc('duplicate_user_project',
                                  (user_id, project_id))
            
            project_record = await cursor.fetchone()

            if not project_record:
                await conn.rollback()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to retrieve newly created project."
                )
                
            await conn.commit()


            project_model = Project(**project_record)
            
            return ProjectSuccessResponse(**{
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
@projects_router.get('/', response_model=List[ProjectGetResponse], status_code=status.HTTP_200_OK)
async def get_user_projects(conn: Connection = Depends(get_session),
                            current_user: TokenData = Depends(get_current_user)):
    try:

        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            await cursor.callproc('get_user_projects', (user_id,))

            results = await cursor.fetchall()
            return results

    except ValidationError as e:
        logger.error(f'Error when validating model {str(e)}')
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="An error occurred while fetching projects.")

    except Error as e:
        logger.error(f"Database operation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while fetching projects.")

# TODO: change to patch from put


@projects_router.put('/{project_id}', status_code=status.HTTP_200_OK, response_model=ProjectSuccessResponse)
async def update_project(
        project_id: int,
        project: ProjectUpdate,
        conn: Connection = Depends(get_session),
        current_user: TokenData = Depends(get_current_user)):

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')

            user_id = await users.get_user_id(cursor, params)

            update_data = {
                key: value for key, value in project.model_dump().items() if value
            }
            set_clause = ', '.join(
                [f"{key}=%({key})s" for key in update_data])

            # Dynamic query base on the updated fields only
            update_stmt = f'UPDATE {DB_NAME}.projects SET {set_clause} WHERE projectID = %(project_id)s AND userID = %(user_id)s'

            params = {**update_data,
                      'project_id': project_id, "user_id": user_id}

            await cursor.execute(update_stmt, params)

            await conn.commit()

            return ProjectSuccessResponse(**{
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

            delete_stmt = f"DELETE from {DB_NAME}.projects WHERE projectID = %(project_id)s AND userID = %(user_id)s"

            await cursor.execute(
                delete_stmt, {'project_id': project_id, 'user_id': user_id})
            await conn.commit()

            return JSONResponse(content={'message': f'Project deleted successfully'})

    except Error as e:
        logger.error(f"Database operation error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An error occurred while deleting projects.")



