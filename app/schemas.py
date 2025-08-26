from pydantic import BaseModel, EmailStr
from typing import Optional
from enum import Enum

class PlanEnum(str, Enum):
    free = "free"
    pro = "pro"

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserBase(BaseModel):
    email: EmailStr
    name: str | None = None
    plan: PlanEnum = PlanEnum.free

class UserCreate(UserBase):
    password: str

class UserOut(UserBase):
    id: int
    class Config:
        from_attributes = True

class AnalysisCreate(BaseModel):
    title: str
    raw_log: str

class AnalysisOut(BaseModel):
    id: int
    title: str
    result: str
    created_at: str
    pdf_ready: bool = False
    class Config:
        from_attributes = True
