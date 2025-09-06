from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    email: Optional[str] = None

class UserBase(BaseModel):
    name: str
    email: EmailStr

class UserCreate(UserBase):
    password: str

class UserOut(UserBase):
    id: int
    plan: str
    class Config:
        from_attributes = True

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class AnalysisIn(BaseModel):
    source_name: Optional[str] = None
    raw_log: str

class AnalysisOut(BaseModel):
    id: int
    source_name: Optional[str]
    result_summary: str
    score_risk: int
    created_at: datetime
    pdf_path: Optional[str]
    class Config:
        from_attributes = True

class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str
