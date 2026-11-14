from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import create_token, get_current_user, verify_password
from app.models import User
from app.services import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


def user_info(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "dept_id": user.dept_id,
        "dept_name": user.dept.name,
        "dept_code": user.dept.code,
    }


@router.post("/login")
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    user = (await session.execute(select(User).where(User.username == body.username))).unique().scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "账号或密码错误")
    audit.record(session, user, audit.LOGIN)
    await session.commit()
    return {"token": create_token(user), "user": user_info(user)}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return user_info(user)
