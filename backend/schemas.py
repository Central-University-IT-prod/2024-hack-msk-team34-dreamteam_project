from pydantic import BaseModel
from typing import Dict, List, Optional
from datetime import date
from models import ExpenseType

class UserBase(BaseModel):
    id: int
    name: str

    class Config:
        orm_mode = True

class DataCreate(BaseModel):
    name: str
    description: Optional[str] = None
    date: Optional[date] = None
    total: float
    user_sums: Dict[int, float]  # Map user IDs to amounts
    creator_id: int

class DataResponse(DataCreate):
    id: int
    name: str
    description: Optional[str]
    date: Optional[date]
    total: float
    user_sums: Dict[int, float]
    creator: UserBase
    status: bool

    class Config:
        orm_mode = True

class RoomUpdate(BaseModel):
    name: Optional[str] = None
    expense_type: Optional[ExpenseType] = None
    participant_ids: Optional[List[int]] = None
    invoices: Optional[List[int]] = None

class RoomCreate(BaseModel):
    name: str
    expense_type: ExpenseType
    participant_ids: List[int] = []

class RoomResponse(BaseModel):
    id: int
    name: str
    expense_type: ExpenseType
    participants: List[UserBase]
    invoices: List[int]

    class Config:
        orm_mode = True

