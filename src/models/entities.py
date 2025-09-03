from datetime import datetime
from typing import Optional, Union

from fastapi_camelcase import CamelModel  # type: ignore
from pydantic import BaseModel


class DBRecommendationModel(BaseModel):
    id: int
    title: int
    create_date: datetime | None = None


class Token(CamelModel):
    access_token: str
    token_type: str


class TokenData(CamelModel):
    jti: str | None = None
    username: Union[str, None] = None


class TokenDetails(TokenData):
    jti: str
    username: str | None = None
    expiring_date: float


class User(CamelModel):
    username: str
    email: str = ''
    password: str


class UserInDB(User):
    userID: int
    username: str
    email: str | None = None
    password: str | None = None
    hashed_password: str


class Project(CamelModel):
    project_name: str
    color: str


class ProjectUpdate(Project):
    project_name: Optional[str] = None
    color: Optional[str] = None


class ProjectGet(CamelModel):
    projectID: int
    project_name: str
    color: str


class ProjectTasksCount(Project):
    projectID: int
    project_name: str
    color: str
    task_count: int


class Task(CamelModel):
    title: str
    description: str
    priorityID: int
    statusID: int
    start_date: datetime
    end_date: datetime


class TaskSelect(CamelModel):
    taskID: int
    project_name: str
    title: str
    priority: str
    status: str
    start_date: datetime
    end_date: datetime

# TODO: assign tasks to other users


class TaskDetails(TaskSelect):
    taskID: int
    # assigned: str
    project_name: str
    title: str
    start_date: datetime
    end_date: datetime
    priority: str
    status: str
    description: str
    complete_date: datetime | None
    updated_date: datetime | None
    cancel_date: datetime | None

# TODO: delete model


class TaskInDB(TaskSelect):
    userID: int
    taskID: int
    project_name: str
    title: str
    description: str
    start_date: datetime
    end_date: datetime | None
    status: str
    priority: str
    complete_date: datetime | None
    updated_date: datetime | None
    cancel_date: datetime | None
