import logging
from fastapi import FastAPI, HTTPException, Depends, Request, Form
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, inspect
from sqlalchemy.orm import Session
from database import SessionLocal, engine, Base
from models import Room, ExpenseType, Data, User
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from typing import List, Optional, Dict
from urllib.parse import quote
import models, schemas
from schemas import UserBase, RoomCreate, RoomUpdate

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# одключение к SQLite (файл базы данных)
DATABASE_URL = "sqlite:///./rooms.db"  # Файл базы данных будет создан в текущей директории
BASE_URL = "http://127.0.0.1:8000"  

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
metadata = MetaData()
# Создание базы данных
Base.metadata.create_all(bind=engine)

app = FastAPI()

# Function to drop and recreate the table
def reset_database():
    inspector = inspect(engine)
    if 'data' in inspector.get_table_names():
        models.Data.__table__.drop(engine)
    if 'rooms' in inspector.get_table_names():
        models.Room.__table__.drop(engine)
    models.Base.metadata.create_all(bind=engine)

# Reset the database schema
reset_database()

# Зависимость для подключения к базе данных
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Pydantic схема для валидации входных данных
class RoomCreate(BaseModel):
    name: str
    expense_type: ExpenseType
    participants: List[str] = []

class RoomUpdate(BaseModel):
    name: Optional[str] = None
    expense_type: Optional[ExpenseType] = None
    participants: Optional[List[str]] = None
    invoices: Optional[List[int]] = None

#Логика для кнопки, выступает в роли POST
@app.post("/api/submit_form/")
async def submit_form_create_room( 
    name: str = Form(...),
    expense_type: str = Form(...),
    participants: str = Form(...),
    total_amount: Optional[float] = Form(None)  # Опциональное поле для суммы
):
    # Проверка входных данных
    if not name or not expense_type or not participants:
        raise HTTPException(status_code=400, detail="Все поля должны быть заполнены")

    # Логика проверки обязательности поля `total_amount` для типа "единоразовая"
    if expense_type == "единоразовая" and total_amount is None:
        raise HTTPException(status_code=400, detail="Для единоразовой траты необходимо указать сумму общей затраты")

    # Convert expense_type to ExpenseType enum
    try:
        expense_type_enum = ExpenseType(expense_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid expense type")

    # Split participants into a list
    participants_list = participants.split(",")

    # Create the room
    db = SessionLocal()
    try:
        db_participants = []
        for participant in participants_list:
            user = db.query(User).filter(User.name == participant).first()
            if not user:
                user = User(name=participant)
                db.add(user)
                db.commit()
                db.refresh(user)
            db_participants.append(user)

        db_room = Room(
            name=name,
            expense_type=expense_type_enum,
            participants=db_participants,
            invoices=[]  # Initialize invoices as an empty list
        )
        db.add(db_room)
        db.commit()
        db.refresh(db_room)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal Server Error")
    finally:
        db.close()

    # Генерация уникальной ссылки на комнату
    room_id = name.replace(" ", "_").lower()  # Генерация ID на основе имени
    room_url = f"{BASE_URL}/room/{quote(room_id)}"

    # Возвращение ссылки клиенту
    return JSONResponse(content={
        "message": "Комната успешно создана",
        "room_url": room_url
    })

#Создание комнаты
@app.post("/api/rooms/", response_model=schemas.RoomResponse)
def create_room(room: RoomCreate, db: Session = Depends(get_db)):
    # Create users if they do not exist
    db_participants = []
    for participant_id in room.participants:
        user = db.query(User).filter(User.id == participant_id).first()
        if not user:
            user = User(id=participant_id, name=f"User {participant_id}")
            db.add(user)
            db.commit()
            db.refresh(user)
        db_participants.append(user)

    db_room = Room(
        name=room.name,
        expense_type=room.expense_type,
        participants=db_participants,
        invoices=[]
    )
    db.add(db_room)
    db.commit()
    db.refresh(db_room)
    return db_room

@app.get("/api/room/{room_id}")
async def get_room(room_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return {
        "name": room.name,
        "expense_type": room.expense_type.value,
        "participants": room.participants,
        "invoices": room.invoices
    }

@app.put("/api/room/{room_id}", response_model=dict)
def update_room(room_id: int, room: schemas.RoomUpdate, db: Session = Depends(get_db)):
    db_room = db.query(Room).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="Room not found")

    if room.name is not None:
        db_room.name = room.name
    if room.expense_type is not None:
        db_room.expense_type = room.expense_type
    if room.participant_ids is not None:
        db_participants = db.query(User).filter(User.id.in_(room.participant_ids)).all()
        if not db_participants:
            raise HTTPException(status_code=400, detail="Participants not found")
        db_room.participants = db_participants
    if room.invoices is not None:
        db_room.invoices = room.invoices

        # Sync users from invoices
        for invoice_id in room.invoices:
            invoice = db.query(Data).filter(Data.id == invoice_id).first()
            if invoice:
                for user_id in invoice.user_sums.keys():
                    user = db.query(User).filter(User.id == user_id).first()
                    if not user:
                        user = User(id=user_id, name=f"User {user_id}")
                        db.add(user)
                        db.commit()
                        db.refresh(user)
                    if user not in db_room.participants:
                        db_room.participants.append(user)

    # Sync additional_props as users in the room
    if hasattr(room, 'additional_props'):
        for user_id in room.additional_props:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                user = User(id=user_id, name=f"User {user_id}")
                db.add(user)
                db.commit()
                db.refresh(user)
            if user not in db_room.participants:
                db_room.participants.append(user)

    db.commit()
    db.refresh(db_room)
    return db_room

@app.delete("/api/room/{room_id}", response_model=dict)
def delete_room(room_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    db.delete(room)
    db.commit()
    return {"message": "Room deleted successfully"}

@app.post("/api/invoice/", response_model=schemas.DataResponse)
def create_invoice(invoice: schemas.DataCreate, db: Session = Depends(get_db)):
    creator = db.query(User).filter(User.id == invoice.creator_id).first()
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    user_ids = invoice.user_sums.keys()
    users = []
    for user_id in user_ids:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            user = User(id=user_id, name=f"User {user_id}")
            db.add(user)
            db.commit()
            db.refresh(user)
        users.append(user)

    # Ensure all users in the invoice are participants in the room
    room = db.query(Room).filter(Room.id == invoice.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    for user in users:
        if user not in room.participants:
            room.participants.append(user)

    new_invoice = models.Data(
        name=invoice.name,
        description=invoice.description,
        date=invoice.date,
        total=invoice.total,
        user_sums=invoice.user_sums,
        creator=creator,
        status=False
    )
    db.add(new_invoice)
    db.commit()
    db.refresh(new_invoice)
    return new_invoice

@app.get("/api/invoice/{invoice_id}", response_model=schemas.DataResponse)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    try:
        invoice = db.query(models.Data).filter(models.Data.id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        return invoice
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/invoice/{invoice_id}", response_model=schemas.DataResponse)
def update_invoice(invoice_id: int, invoice: schemas.DataCreate, db: Session = Depends(get_db)):
    try:
        db_invoice = db.query(models.Data).filter(models.Data.id == invoice_id).first()
        if not db_invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        db_invoice.name = invoice.name
        db_invoice.description = invoice.description
        db_invoice.date = invoice.date
        db_invoice.total = invoice.total
        db_invoice.user_sums = invoice.user_sums
        db_invoice.creator_name = invoice.creator_name

        db.commit()
        db.refresh(db_invoice)
        return db_invoice
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/invoice/{invoice_id}", response_model=schemas.DataResponse)
def delete_invoice(invoice_id: int, db: Session = Depends(get_db)):
    try:
        invoice = db.query(models.Data).filter(models.Data.id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        db.delete(invoice)
        db.commit()
        return invoice
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/invoice/{invoice_id}/request-close", response_model=schemas.DataResponse)
def request_close_invoice(invoice_id: int, db: Session = Depends(get_db)):
    try:
        invoice = db.query(models.Data).filter(models.Data.id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        if invoice.status:
            raise HTTPException(status_code=400, detail="Invoice is already closed")

        # Here you can add logic to notify the creator about the closure request
        # For simplicity, we just return the invoice
        return invoice
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/api/invoice/{invoice_id}/confirm-close", response_model=schemas.DataResponse)
def confirm_close_invoice(invoice_id: int, db: Session = Depends(get_db)):
    try:
        invoice = db.query(models.Data).filter(models.Data.id == invoice_id).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        if invoice.status:
            raise HTTPException(status_code=400, detail="Invoice is already closed")

        invoice.status = True
        db.commit()
        db.refresh(invoice)
        return invoice
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/room/{room_id}/total_invoices", response_model=float)
def get_total_invoices(room_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    total_sum = 0.0
    for invoice_id in room.invoices:
        invoice = db.query(Data).filter(Data.id == invoice_id).first()
        if invoice:
            total_sum += invoice.total
    
    return total_sum

@app.get("/api/user/{user_id}/total_invoices", response_model=float)
def get_total_invoices_by_user(user_id: int, db: Session = Depends(get_db)):
    invoices = db.query(Data).filter(Data.creator_id == user_id).all()
    
    total_sum = sum(invoice.total for invoice in invoices)
    
    return total_sum

@app.get("/api/room/{room_id}/user/{user_id}/total_invoices", response_model=float)
def get_total_invoices_by_user_in_room(room_id: int, user_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    total_sum = 0.0
    for invoice_id in room.invoices:
        invoice = db.query(Data).filter(Data.id == invoice_id, Data.creator_id == user_id).first()
        if invoice:
            total_sum += invoice.total
    
    return total_sum

@app.get("/api/room/{room_id}/balance/{user1_id}/{user2_id}", response_model=float)
def get_balance_between_users_in_room(room_id: int, user1_id: int, user2_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    user1_balance = 0.0
    user2_balance = 0.0

    for invoice_id in room.invoices:
        invoice = db.query(Data).filter(Data.id == invoice_id).first()
        if invoice:
            user_sums = invoice.user_sums
            if user1_id in user_sums:
                user1_balance += user_sums[user1_id]
            if user2_id in user_sums:
                user2_balance += user_sums[user2_id]

    total_balance = user1_balance - user2_balance
    return total_balance

from collections import defaultdict

@app.get("/api/room/{room_id}/balances", response_model=Dict[int, Dict[int, float]])
def get_balances_in_room(room_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    debts = defaultdict(lambda: defaultdict(float))
    participants = {user.id: user for user in room.participants}
    
    # Collect all invoices in the room
    for invoice_id in room.invoices:
        invoice = db.query(Data).filter(Data.id == invoice_id).first()
        if not invoice or not invoice.user_sums:
            continue
        
        creator_id = invoice.creator_id
        user_sums = invoice.user_sums
        
        # Each user owes the creator their amount in user_sums
        for user_id, amount in user_sums.items():
            if user_id != creator_id:
                debts[user_id][creator_id] += amount
            else:
                # Optionally handle the creator's own amount if necessary
                pass

    # Simplify debts by netting reciprocal debts
    simplified_debts = defaultdict(dict)
    
    for debtor_id in participants:
        for creditor_id in participants:
            if debtor_id == creditor_id:
                continue
            amount_owed = debts.get(debtor_id, {}).get(creditor_id, 0)
            reverse_amount = debts.get(creditor_id, {}).get(debtor_id, 0)
            net_amount = amount_owed - reverse_amount
            if net_amount > 0:
                simplified_debts[debtor_id][creditor_id] = net_amount

    # Remove entries with no debts
    result = {
        debtor_id: creditors for debtor_id, creditors in simplified_debts.items() if creditors
    }

    return result

@app.get("/api/users/{user_id}", response_model=UserBase)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@app.on_event("startup")
def clean_creator_names():
    # Clean up creator names before starting the server
    db = SessionLocal()
    try:
        invoices = db.query(models.Data).all()
        for invoice in invoices:
            if ':' in invoice.creator_name:
                # Extract the creator's name before the colon
                creator_name = invoice.creator_name.split(':')[0].strip()
                invoice.creator_name = creator_name
        db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
