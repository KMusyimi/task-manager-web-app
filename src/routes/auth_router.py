from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from mysql.connector import Error, IntegrityError
from src.auth import create_access_token, create_refresh_token
from src.db.database import get_session
from src.db.redis import add_jti_block_list
from src.models.entities import (Token, TokenDetails, User)
from asyncmy.cursors import DictCursor  # type: ignore
from asyncmy.connection import Connection  # type: ignore
from src.users import users
from pytz import timezone
from src.utils import get_current_refresh_user, get_current_user, revoke_refresh_token

# TODO: user routes
auth_router = APIRouter(tags=['auth'])
tz = timezone('Africa/Nairobi')


@auth_router.post('/login', response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), 
                                 conn: Connection = Depends(get_session)):
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            login_user = await users.authenticate_user(
                cursor, form_data.username, form_data.password)

            if not login_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Incorrect username or password",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            access_token = create_access_token(
                data={'sub': login_user.username})

            refresh_token = create_refresh_token(
                data={'sub': login_user.username, 'refresh': True})

            response = JSONResponse(content={
                "user": login_user.username,
                "message": 'Login successful',
                "accessToken": access_token,
                "tokenType": "bearer"})
            # TODO: change secure to True
            response.set_cookie(key="refresh-Token",
                                value=refresh_token,
                                httponly=True,
                                secure=True,
                                samesite="lax",
                                domain='localhost',
                                max_age=3600 * 24 * 7)
            return response

    except (Error, IntegrityError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Something went wrong: {e}")


@auth_router.get("/users/me")
async def read_users_me(current_user: User = Depends(get_current_user)):
    return JSONResponse(content={"username": current_user.username})


@auth_router.post("/register")
async def create_user(user: User, conn: Connection = Depends(get_session)):
    try:
        async with conn.cursor(cursor=DictCursor) as cursor:
            existing_user = await users.check_user_exists(
                cursor, user)
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username or email already exists")

            user_id = await users.register_user(conn, cursor, user)

            return {"message": "User created successfully", "userID": user_id}

    except Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong: {e}")


@auth_router.post('/logout', status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(current_user: User = Depends(get_current_user), refresh_user: TokenDetails = Depends(get_current_refresh_user)):
    if not current_user or not refresh_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials."
        )
    try:
        await add_jti_block_list(jti=current_user.jti)

        await revoke_refresh_token(jti=refresh_user.jti)

        response = JSONResponse(
            content={"message": "You've been successfully logged out."}, status_code=status.HTTP_200_OK)
        # deleting the logout users httponly cookie
        response.set_cookie(key="refresh-Token",
                            value='',
                            httponly=True,
                            secure=True,
                            samesite="lax",
                            domain='localhost',
                            max_age=-1)
        return response

    except Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong: {e}")


@auth_router.post('/refresh')
async def get_new_access_token(token_details: TokenDetails = Depends(get_current_refresh_user)):
    try:
        exp_timestamp = datetime.fromtimestamp(
            token_details.expiring_date, tz=tz)
        current_timestamp = datetime.now(tz)
        time_remaining = exp_timestamp - current_timestamp

        twenty_four_hours = timedelta(hours=24)

        new_access_token = create_access_token(
            data={'sub': token_details.username})

        response = JSONResponse(content={'accessToken': new_access_token})

        if time_remaining < twenty_four_hours:
            new_refresh_token = create_refresh_token(
                data={'sub': token_details.username, 'refresh': True})

            response.set_cookie(key="refresh-Token",
                                value=new_refresh_token,
                                httponly=True,
                                secure=True,
                                samesite="lax",
                                domain='localhost',
                                max_age=3600 * 24 * 7)

        return response

    except Error as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Something went wrong: {e}")
