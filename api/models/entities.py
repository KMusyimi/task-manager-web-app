from datetime import datetime
import json
from typing import List, Optional

from pydantic import AliasGenerator, BaseModel, ConfigDict, EmailStr, Field, field_validator
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

class EmailRequest(BaseModel):
    email: EmailStr

class DBRecommendationModel(BaseModel):
    id: int
    title: int
    create_date: Optional[datetime] = None


class TokenData(BaseModel):
    sub: str = Field(..., description="current user")
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


class VerifyCodeRequest(BaseModel):
    email: EmailStr = Field(default="dev@tasker.test.com", description='create user email for verification')
    code: str
    

class ResendCodeRequest(BaseModel):
    email: EmailStr
    
class User(BaseModelConfig):
    username: str

    class Config:
        from_attributes = True


class UserCreate(User):
    email:EmailStr
    password: str
    is_verified:bool = Field(default=False)
    profile_img_url: Optional[str] = Field(
            default='https://res.cloudinary.com/dq4izno26/image/upload/v1785836280/person_ns4ntn.webp', description='Avatar image')

    class Config:
        from_attributes = True

class UserUpdate(User):
    username:  Optional[str] = None
    email: Optional[EmailStr] = None
    password: str
    bio:  Optional[str] = Field(default='', max_length=255,
                                description="Users bio")
    phone_number: Optional[str] = Field(default='', max_length=16,
                                        description="Users phone number")
    role: Optional[str] = Field(default='', max_length=25,
                                description="Users work role")
    department: Optional[str] = Field(default='', max_length=25,
                                      description="Users work department ")
    avatar_color: str = Field(default='#6B5FED', min_length=7, max_length=7,
                              description="Users fallback avatar color")
    avatar_version: int = Field(
        default=1, description="Users fallback avatar version")

    class Config:
        from_attributes = True


class UserGet(User):
    userID: int
    email: EmailStr
    profile_img_url: Optional[str] = Field(
        default='https://res.cloudinary.com/dq4izno26/image/upload/v1785836280/person_ns4ntn.webp', description='Avatar image')
    bio:  Optional[str] = Field(default='', max_length=255,
                                description="Users bio")
    phone_number: Optional[str] = Field(default='', max_length=16,
                                        description="Users phone number")
    role: Optional[str] = Field(default='', max_length=25,
                                description="Users work role")
    department: Optional[str] = Field(default='', max_length=25,
                                      description="Users work department ")
    avatar_color: str = Field(default='#6B5FED', min_length=7, max_length=7,
                              description="Users fallback avatar color")
    
    avatar_version: int = Field(
            default=1, description="Users fallback avatar version")

    joined_in: Optional[str] = Field(
        default='2025', description='The year users joined')


class UserInDb(User):
    userID: int
    email: EmailStr
    profile_img_url: Optional[str] = Field(
        default='https://res.cloudinary.com/dq4izno26/image/upload/v1785836280/person_ns4ntn.webp', description='Avatar image')
    token_v: Optional[int] = Field(
        default=0, description='User Token version')
    password: Optional[str] = None
    is_verified: bool = Field(default=False, description="User is verified or not")
    hashed_password: Optional[str] = None


class UploadResponse(BaseModelConfig):
    message: str
    success: bool


class UserChangePassword(BaseModelConfig):
    username: str
    current_pw: str
    new_pw: str
    confirm_pw: str


class TagSchema(BaseModel):
    name: str
    color: str


class TaskInDB(BaseModelConfig):
    projectID: Optional[int] = None
    taskID: Optional[int] = None
    project_name: Optional[str] = None
    title: Optional[str] = None
    tags: List[TagSchema] = Field(default_factory=list)
    description: Optional[str] = None
    position: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    complete_date: Optional[datetime] = None
    updated_date: Optional[datetime] = None
    cancel_date: Optional[datetime] = None

    @field_validator('tags', mode='before')
    @classmethod
    def decode_tags_json(cls, value):
        if value is None:
            return []

        # If the driver leaves it as a raw text string, parse it into a Python list
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return []

        # If it's already a parsed list/tuple from the database, return it as-is
        return value

    class Config:
        from_attributes = True


class SubTaskResponseSchema(BaseModelConfig):
    subTaskID: int
    taskID: int
    title: str
    is_completed: bool
    position: int

    class Config:
        from_attributes = True


class CreateSubtaskSchema(BaseModelConfig):
    title: str = Field(..., max_length=55,
                       description="The title of the subtask")


class KanbanReorderSchema(BaseModelConfig):
    taskID: int = Field(..., alias="taskId")
    destination_column_id: int = Field(..., alias="destinationColumnId")
    new_position: int = Field(..., alias="newPosition")

    class Config:
        populate_by_name = True


class CreateSubtaskList(BaseModelConfig):
    subtasks: List[CreateSubtaskSchema] = Field(...,
                                                min_length=1,
                                                max_length=25,
                                                description="List of subtasks to add")


class ToggleSubtask(BaseModelConfig):
    subTaskID: int
    is_completed: bool = Field(default_factory=bool,
                               description="Toggle subtasks to complete or undo")


class CreateTagsList(BaseModelConfig):
    tags: List[TagSchema] = Field(..., min_length=1,
                                  description="List of tasks tags to add")


class TaskCreateSchema(TaskInDB):
    projectID: int = Field(default=0)
    title: Optional[str] = Field(
        default="", max_length=55, description="The title of the task")
    description: Optional[str] = Field(
        default="", max_length=255, description="The description of the task")
    priorityID: int = Field(
        default=1, description="The priority id for kanban column the added task belongs to")
    columnID: int = Field(
        default=1, description="The column id for kanban column the added task belongs to")
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

    tags: List[TagSchema] = Field(
        default=[], max_length=10, description="List of tags to add")
    subtasks: List[CreateSubtaskSchema] = Field(default=[],
                                                max_length=25,
                                                alias="subtasks",
                                                description="List of subtasks to add")

    # Intercept bad string dates ("null" or "") and reset them to clean None
    @field_validator('description', 'start_date', 'end_date', mode='before')
    def sanitize_string_dates(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            clean_val = value.strip().lower()
            if clean_val in ('', 'null', 'undefined'):
                return None
        return value

    #  Intercept stringified lists ("" or "[]") and parse them into a native Python list
    @field_validator('subtasks', mode='before')
    def sanitize_subtasks_list(cls, value):
        if value is None or value == '':
            return []
        if isinstance(value, str):
            try:
                # If it's a stringified JSON array like '[]', parse it
                return json.loads(value)
            except json.JSONDecodeError:
                # If it's single text values or garbage text, return an empty array fallback
                return []
        return value


class TaskDeleteSchema(BaseModelConfig):
    projectID: int = Field(default=0)


class TaskGetList(TaskInDB):
    position: Optional[int] = None
    description: Optional[str] = None
    display_date: Optional[str] = None
    columnID: int

    task_key: str = Field(default="TSK-1000",
                          validation_alias="taskKey")
    tags: Optional[object] = None

    startDate: Optional[datetime] = None
    endDate: Optional[datetime] = None
    displayDate: Optional[str] = None
    total_subtasks: int = 0
    completed_subtasks: int = 0


class ColumnSegment(BaseModelConfig):
    columnID: int
    column_name: str
    page: int = Field(
        default=1, description="The current paginated index page for this column")
    size: int = Field(default=10, description="The chunk slice sizing limit")
    total: int = Field(
        default=0, description="Total absolute tasks matching this status query in DB")
    has_more: bool = Field(
        default=False, description="Flags if another chunk remains on the server")
    tasks: List[TaskGetList] = Field(default_factory=list)


class SegmentedTasksResponse(BaseModelConfig):
    projectID: Optional[int] = None
    segments: dict[str, ColumnSegment]


class TaskGetKanban(TaskInDB):
    position: Optional[int] = Field(default_factory=int)
    tags: Optional[object] = None
    display_date: Optional[str] = None
    task_key: str = Field(default="TSK-1000",
                          validation_alias="taskKey")
    total_subtasks: int = 0
    completed_subtasks: int = 0


class TasksResponseKanban(BaseModelConfig):
    columnID: int
    column_name: str
    tasks: List[TaskGetKanban] = Field(default_factory=list)


class Project(BaseModelConfig):
    projectID: int
    project_name: str
    color: str


class ProjectAdd(Project):
    projectID: Optional[int] = None
    project_name: str


class ProjectGetResponse(Project):
    task_count: int


class ProjectUpdate(ProjectAdd):
    project_name: Optional[str] = None
    color: Optional[str] = None


class ProjectSuccessResponse(BaseModelConfig):
    projectID: int
    message: str


class ProjectsResponse(BaseModelConfig):
    projects: List[ProjectGetResponse] = Field(default_factory=list)
