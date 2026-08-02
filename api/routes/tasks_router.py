import asyncio
from datetime import date, datetime
import json
import logging
from typing import Dict, List, Optional, Union

from pydantic import ValidationError

from asyncmy.connection import Connection  # type: ignore
from asyncmy.cursors import DictCursor  # type: ignore
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from mysql.connector import Error
from api.db.database import DB_NAME, get_session
from api.models.entities import ColumnSegment, CreateTagsList, KanbanReorderSchema, SegmentedTasksResponse, TaskCreateSchema, TaskDeleteSchema, TaskGetList, TasksResponseKanban, TokenData
from api.users import users
from api.utils import get_current_user


logger = logging.getLogger("users_logger")
task_router = APIRouter(
    prefix='/projects/{username}/tasks', tags=['Tasks', 'Sub-Tasks'])


def get_display_date(end_date: Union[datetime, str, None]) -> str:
    # Check if it's actually an object before formatting to avoid crashes
    display_date = ''
    if isinstance(end_date, datetime):
        # Cross-platform safe: dt.day strips leading zeros natively
        display_date = f"{end_date.strftime('%B')} {end_date.day}"

    elif isinstance(end_date, str):
        # Parse the string format coming from MySQL
        dt = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")
        # Cross-platform safe string rendering
        display_date = f"{dt.strftime('%B')} {dt.day}"
    else:
        display_date = "No due date"

    return display_date


async def fetch_single_column_segment(
    cursor, user_id: int, project_id: Optional[int],
    column_id: int, column_name: str,
    size: int, offset: int, page: int
) -> ColumnSegment:

    safe_column_id = column_id if column_id is not None else 0

    if project_id is not None:
        proc_name = "get_user_tasks_by_project"
        proc_params = (user_id, project_id, safe_column_id, size, offset)
    else:
        proc_name = "get_user_all_tasks"
        proc_params = (user_id, safe_column_id, size, offset)

    try:

        logger.debug(f'Params - {proc_params}, {proc_name}, {type(project_id)}')
        await cursor.callproc(proc_name, proc_params)

        results = await cursor.fetchall()

        if not results:
            return ColumnSegment(
                columnID=column_id,
                column_name=column_name,
                page=page,
                size=size,
                total=0,
                has_more=False,
                tasks=[]
            )

        # Check if results contains a "null" mock row
        first_row = results[0]
        if first_row is None or (isinstance(first_row, dict) and first_row.get('taskID') is None):
            return ColumnSegment(
                columnID=column_id,
                column_name=column_name,
                page=page,
                size=size,
                total=0,
                has_more=False,
                tasks=[]
            )

        raw_total = first_row.get('total_count', 0)
        total_count = int(raw_total) if raw_total is not None else 0

        row_data = {}
        tasks_list = []

        for row in results:
            task_id = row.get('taskID')
            # skip any corrupt/empty row
            if not row or task_id is None:
                continue

            p_name = row.get('projectName') or row.get(
                'project_name') or "Unknown Project"

            row_data = {
                "projectID": row.get('projectID'),
                "taskID": row.get('taskID'),
                "projectName": p_name,
                "title": row.get('title'),
                "priority": row.get('priority'),
                "status": row.get('status'),
                "tags": row.get('tags_raw') or "",
                "columnID": row.get('columnID'),
                "task_key": row.get('taskKey', f"TSK-{row.get('taskID')}"),
                "startDate": row.get('start_date') or row.get('startDate'),
                "endDate": row.get('end_date') or row.get('endDate'),
                "is_completed": bool(row.get('is_completed', False)),
                "total_subtasks": row.get('total_subtasks') or 0,
                "completed_subtasks": row.get('completed_subtasks') or 0,
            }

            task = TaskGetList(**row_data)
            task.displayDate = get_display_date(end_date=task.endDate)
            tasks_list.append(task)

        has_more = (offset + len(tasks_list)) < total_count

        return ColumnSegment(
            columnID=column_id,
            column_name=column_name,
            page=page,
            size=size,
            total=total_count,
            has_more=has_more,
            tasks=tasks_list
        )

    except ValidationError as val_err:
        logger.error(
            f"Pydantic mapping failed on column segment {column_name}: {str(val_err)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Database record shape failed parsing validation bounds."
        )


@task_router.post('/', status_code=status.HTTP_201_CREATED)
async def add_tasks(task: TaskCreateSchema,
                    conn: Connection = Depends(get_session),
                    current_user: TokenData = Depends(get_current_user)):

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            logger.info('Create a new task')

            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            tags_json_string = json.dumps(
                [tag.model_dump() for tag in task.tags])

            t_params = (user_id, task.projectID, task.title, task.description, tags_json_string,
                        task.start_date, task.end_date, task.columnID, task.priorityID)
            await cursor.callproc('add_task', t_params)

            await conn.commit()

            result = await cursor.fetchone()

            new_task_id = result.get('newTaskID')

            subtasks_json_string = json.dumps(
                [subtask.model_dump() for subtask in task.subtasks])

            st_params = (user_id, new_task_id, subtasks_json_string)

            await cursor.callproc('add_subtasks', st_params)
            await conn.commit()

            return JSONResponse(content={
                "status": 'success',
                'message': f"Successfully added {len(task.subtasks)} subtasks to task {new_task_id} ", "taskID": new_task_id})

    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create task via database engine: {str(e)}")


@task_router.get('/list', status_code=status.HTTP_200_OK, response_model=SegmentedTasksResponse)
async def get_tasks_list(
    current_user: TokenData = Depends(get_current_user),
    conn: Connection = Depends(get_session),
    project_id: Optional[int] = None,
    column_id: Optional[int] = Query(
        None, description="The specific column segment to fetch"),
    filter_date: Optional[date] = None,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100)
):
    # active_filter_date = filter_date or date.today()
    offset = (page - 1) * size

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            await cursor.execute("SELECT columnID, column_name FROM kanban_columns ORDER BY columnID ASC;")
            db_columns = await cursor.fetchall()

            if not db_columns:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="No workflow configuration columns found in the system database."
                )

            if column_id is not None:
                col_data = next(
                    (c for c in db_columns if c.get("columnID") == column_id), None)

                if not col_data:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Requested column ID {column_id} does not exist in workflow configurations."
                    )

                segment_payload = await fetch_single_column_segment(
                    cursor=cursor,
                    user_id=user_id,
                    project_id=project_id,
                    column_id=col_data["columnID"],
                    column_name=col_data["column_name"],
                    size=size,
                    offset=offset,
                    page=page
                )

                return SegmentedTasksResponse(
                    projectID=project_id,
                    segments={str(column_id): segment_payload}
                )

            logger.debug(
                f"Executing query with parameters: "
                f"user_id={user_id} ({type(user_id)}), "
                f"project_id={project_id} ({type(project_id)}), "
                f"col_id={column_id} ({type(column_id)}), "
                f"filter_date={filter_date} ({type(filter_date)})"
            )

            segments_map: Dict[str, ColumnSegment] = {}

            # Execute sequentially over the single connection/cursor
            for col in db_columns:
                current_col_id = col["columnID"]
                current_col_name = col["column_name"]

                segment_payload = await fetch_single_column_segment(
                    cursor=cursor,
                    user_id=user_id,
                    project_id=project_id,
                    column_id=current_col_id,
                    column_name=current_col_name,
                    size=size,
                    offset=0,
                    page=1
                )
                segments_map[str(current_col_id)] = segment_payload

            return SegmentedTasksResponse(
                projectID=project_id,
                segments=segments_map or {}
            )

    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Segmented database operation failure: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while fetching column segment tasks."
        )


@task_router.get('/board', status_code=status.HTTP_200_OK, response_model=List[TasksResponseKanban])
async def get_tasks_board(conn: Connection = Depends(get_session),
                          current_user: TokenData = Depends(get_current_user),
                          project_id: Optional[int] = None):

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            if project_id is not None:
                proc_name = "get_kanban_by_project"
                proc_params = (user_id, project_id)
            else:
                proc_name = "get_kanban_all_projects"
                proc_params = (user_id,)

            await cursor.callproc(proc_name, proc_params)

            results = await cursor.fetchall()
            board_map = {}

            for row in results:
                col_id = row.get('columnID')
                task_id = row.get('taskID')

                if col_id not in board_map:
                    board_map[col_id] = {
                        "columnID": col_id,
                        "column_name": row.get('status'),
                        "tasks": []
                    }

                end_date = row.get('end_date')
                display_date = get_display_date(end_date=end_date)

                if task_id is not None:
                    board_map[col_id]["tasks"].append({
                        "projectID": row.get('projectID'),
                        "taskID": row.get('taskID'),
                        "project_name": row.get('project_name'),
                        "title": row.get('title'),
                        "description": row.get('description'),
                        "tags": row.get('tags'),
                        "position": row.get('position'),
                        "task_key": row.get('taskKey', f"TSK-{row.get('taskID')}"),
                        "is_completed": row.get('is_completed'),
                        "priority": row.get('priority'),
                        "start_date": row.get('start_date'),
                        "end_date": end_date,
                        "total_subtasks": row.get('total_subtasks'),
                        "completed_subtasks": row.get('completed_subtasks'),
                        "display_date": display_date
                    })

            return list(board_map.values())

    except Error as e:
        logger.error(f"Database operation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An error occurred while fetching kanban columns. {str(e)}")


@task_router.patch('/board/reorder')
async def reorder_board(payload: KanbanReorderSchema,
                        conn: Connection = Depends(get_session),
                        _: TokenData = Depends(get_current_user)):

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (payload.taskID, payload.destination_column_id,
                      payload.new_position)

            await cursor.callproc('reorder_kanban_tasks', params)
            await conn.commit()

            return {"status": "success", "message": "Task card shifted successfully"}

    except Error as e:
        await conn.rollback()
        logger.error(f"Database operation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An error occurred while reordering kanban column. {str(e)}")


@task_router.put('/{task_id}')
async def update_task(task_id: int,
                      task: TaskCreateSchema,
                      conn: Connection = Depends(get_session),
                      current_user: TokenData = Depends(get_current_user)):

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            update_data = {
                key: value for key, value in task.model_dump().items() if value
            }
            update_stmt = f"UPDATE {DB_NAME}.tasks SET {task} WHERE taskID = %(task_id)s AND projectID = %(project_id)s"
            print(update_stmt)
            # await cursor.execute(update_stmt, {'task_id': task_id, 'user_id': user_id, 'project_id': project_id})

            # await conn.commit()

            return JSONResponse(content={'message': f'Task {task_id} successfully updated'})

    except Error as e:
        print(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong when updating task {str(e)}")


@task_router.put('/{task_id}/tags', status_code=status.HTTP_200_OK)
async def update_tags(task_id: int,
                      payload: CreateTagsList,
                      conn: Connection = Depends(get_session),
                      current_user: TokenData = Depends(get_current_user)):

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            logger.info(f'Create new tags {payload}')

            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            tags_json_string = json.dumps(
                [tag.model_dump() for tag in payload.tags])
            logger.info(f'Create new tags {tags_json_string}')

            query = f"""
                UPDATE {DB_NAME}.tasks set tags = %s 
                WHERE userID = %s AND taskID = %s;
            """

            await cursor.execute(query, (tags_json_string, user_id, task_id))

            await conn.commit()

            return {
                "status": "success",
                "message": f"Successfully added {len(payload.tags)} tags to task {task_id} for user {user_id}."
            }

    except Error as e:
        logger.error(f"Database error: {e}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong when creating tags {str(e)}")


@task_router.delete('/{task_id}')
async def delete_task(task_id: int,
                      payload: TaskDeleteSchema,
                      conn: Connection = Depends(get_session),
                      current_user: TokenData = Depends(get_current_user)):

    query = f"DELETE from {DB_NAME}.tasks WHERE userID = %s AND taskID = %s AND projectID = %s"

    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            params = (current_user.sub, '')
            user_id = await users.get_user_id(cursor, params)

            await cursor.execute(query, (user_id, task_id, payload.projectID))

            await conn.commit()

            return {
                "status": "success",
                "message": f"Successfully deleted  task {task_id}."
            }

    except Error as e:
        logger.error(f"Database error: {str(e)}")
        await conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong when deleting task {str(e)}")
