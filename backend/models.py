from sqlalchemy import Column, Integer, String, Enum, ForeignKey, Float, Date, JSON, Boolean, Table
from sqlalchemy.orm import relationship
from database import Base
import enum

class ExpenseType(enum.Enum):
    one_time = "one_time"
    long_term = "long_term"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)

    # Relationships
    rooms = relationship("Room", secondary="room_participants", back_populates="participants")
    invoices_created = relationship("Data", back_populates="creator")

# Association table for many-to-many relationship between Room and User
room_participants = Table(
    'room_participants',
    Base.metadata,
    Column('room_id', Integer, ForeignKey('rooms.id')),
    Column('user_id', Integer, ForeignKey('users.id'))
)

class Room(Base):
    __tablename__ = "rooms"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    expense_type = Column(Enum(ExpenseType), nullable=False)
    invoices = Column(JSON, default=[])  # Store invoice IDs as a JSON array

    # Participants relationship
    participants = relationship("User", secondary=room_participants, back_populates="rooms")

class Data(Base):
    __tablename__ = 'data'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String)
    date = Column(Date)
    total = Column(Float)
    user_sums = Column(JSON)
    creator_id = Column(Integer, ForeignKey('users.id'))
    status = Column(Boolean, default=False)
    
    # Creator relationship
    creator = relationship("User", back_populates="invoices_created")
