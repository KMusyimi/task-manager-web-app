from datetime import datetime
from typing import List, Optional

from fastapi_camelcase import CamelModel  # type: ignore
from pydantic import AliasGenerator, BaseModel, ConfigDict, EmailStr, Field, computed_field
from pydantic.alias_generators import to_camel


class BaseModelConfig(BaseModel):
    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            validation_alias=to_camel,
            serialization_alias=to_camel,
        ),
        populate_by_name=True,
    )

class RequestLog(BaseModelConfig):
    req_id: str
    method: str
    route: str
    ip: str
    url: str
    host: str
    body: dict
    headers: dict


class ErrorLog(BaseModel):
    req_id: str
    error_message: str


class DBRecommendationModel(BaseModel):
    id: int
    title: int
    create_date: Optional[datetime] = None


class TokenData(BaseModel):
    sub: str = Field(..., description="Username")
    iat: int = Field(..., description="Issued at timestamp")
    jti: str = Field(...,
                     description="Unique identifier for this specific token")
    version: int = Field(..., alias="v",
                         description="Security version for global logout")


class RefreshTokenData(TokenData):
    refresh: bool
    exp: int = Field(..., description="Expiration timestamp")


class UserTokenJTI(BaseModel):
    access_jti: Optional[str]
    refresh_jti: Optional[str]


class User(BaseModelConfig):
    username: str
    email: Optional[EmailStr] = None


class UserCreate(User):
    password: str


class UserUpdate(User):
    username:  Optional[str] = None
    password: str


class UserGet(User):
    userID: int
    profile_img_url: Optional[str] = None


class UserInDb(User):
    userID: int
    email: Optional[EmailStr] = None
    profile_img_url: Optional[str] = None
    token_v: Optional[int] = None
    password: Optional[str] = None
    hashed_password: Optional[str] = None


class UploadResponse(BaseModelConfig):
    message: str
    success: bool


class UserChangePassword(BaseModelConfig):
    current_pw: str
    new_pw: str
    confirm_pw: str


class TasksGet(CamelModel):
    taskID: int
    project_name: str
    title: str
    description: str
    color: str
    priority: str
    status: str
    start_date: datetime
    end_date: datetime


class TaskResponse(TasksGet):
    display_date: Optional[str] = Field(default_factory=str)


class TaskDetails(TasksGet):
    taskID: int
    # assigned: str
    project_name: str
    title: str
    start_date: datetime
    end_date: datetime
    priority: str
    status: str
    description: str
    complete_date: Optional[datetime] = None
    updated_date: Optional[datetime] = None
    cancel_date: Optional[datetime] = None


class TaskInDB(TasksGet):
    userID: int
    taskID: int
    project_name: str
    title: str
    description: str
    start_date: datetime
    end_date: Optional[datetime] = None
    status: str
    priority: str
    complete_date: Optional[datetime] = None
    updated_date: Optional[datetime] = None
    cancel_date: Optional[datetime] = None


class Project(BaseModelConfig):
    projectID: int
    project_name: str
    color: str

class ProjectAdd(Project):
    projectID: Optional[int] = None
    project_name: str


class ProjectUpdate(ProjectAdd):
    project_name: Optional[str] = None
    color: Optional[str] = None


class ProjectResponse(BaseModelConfig):
    projectID: int
    message: str


class TaskAdd(CamelModel):
    title: str
    description: str
    priorityID: int
    statusID: int
    start_date: datetime
    end_date: datetime

class ProjectTaskGet(Project):
    tasks: List[TaskResponse] = Field(default_factory=list)
    
class ProjectsResponse(BaseModelConfig):
    projects: List[ProjectTaskGet] = Field(default_factory=list)
