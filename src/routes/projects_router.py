
from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from mysql.connector import Error
from src.db.database import get_session
from src.models.entities import (Project, ProjectGet, ProjectTasksCount,
                                 ProjectUpdate, User)
from src.users import users
from src.utils import get_current_user

projects_router = APIRouter(prefix='/projects/{username}', tags=['projects'])


@projects_router.post('/', response_model=ProjectGet)
async def add_project(username: str,
                      project: Project,
                      conn: Connection = Depends(get_session),
                      current_user: User = Depends(get_current_user)):

    if (current_user.username != username):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='Operation forbidden: The authenticated user does not match the requested resource.')

    try:
        # TODO: move to its own Projects Object
        async with conn.cursor(DictCursor) as cursor:
            params = (current_user.username, '')
            user_id = await users.get_user_id(cursor, params)

            if user_id is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User does not exist")

            params = (user_id, project.project_name, project.color)
            await cursor.callproc('add_project', params)
            await conn.commit()
            return await cursor.fetchone()

    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while creating project.")


@projects_router.post('/{project_id}/duplicate')
async def duplicate_project(username: str,
                            project_id: int,
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

            await cursor.callproc('duplicate_user_project',
                                  (user_id, project_id))
            await conn.commit()
            project = await cursor.fetchone()
            project_id = project['projectID']

            return JSONResponse(content={'message': f'Successfully duplicated project', 'projectID': project_id})

    except KeyError:
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="An error occurred while duplicating project.")

    except Error as e:
        await conn.rollback()
        print(f"Database error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while duplicating project.")


# TODO: add a response model
@projects_router.get('/', response_model=list[ProjectTasksCount])
async def get_user_projects(username: str,
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

            await cursor.callproc('get_user_projects', (user_id,))
            return await cursor.fetchall()

    except Error as e:
        print(f"Database error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An error occurred while fetching projects.")

# TODO: change to patch from put


@projects_router.put('/{project_id}')
async def update_project(username: str,
                         project_id: int,
                         project: ProjectUpdate,
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

            update_fields = ', '.join(
                f"{key}='{value}'" for key, value in project.model_dump().items() if value)
            # Dynamic query base on the updated fields only
            update_stmt = f'UPDATE todo_schema.projects SET {update_fields} WHERE projectID = %(project_id)s AND userID = %(user_id)s'

            await cursor.execute(update_stmt, {'project_id': project_id, 'user_id': user_id})

            await conn.commit()
            return JSONResponse(content={'message': f'Project updated successfully.', 'projectID': project_id})

    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to update project")


@projects_router.delete('/{project_id}')
async def delete_project(username: str,
                         project_id: int,
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

            delete_stmt = "DELETE from projects WHERE projectID = %(project_id)s AND userID = %(user_id)s"
            await cursor.execute(
                delete_stmt, {'project_id': project_id, 'user_id': user_id})
            await conn.commit()
            return JSONResponse(content={'message': f'Project deleted successfully.'})
    except Error as e:
        await conn.rollback()
        print(f"Database error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong: {e}")
