"""Booking service models — Appointments and Reservations."""

from datetime import datetime, date, time
from typing import Optional, List
from sqlalchemy import Column, Integer, String, Date, Time, DateTime, Boolean, Enum as SAEnum, Text
from sqlalchemy.ext.declarative import declarative_base
from pydantic import BaseModel
import enum

Base = declarative_base()


# ── Enums ────────────────────────────────────────────────────────────────────

class AppointmentStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW   = "no_show"


class ReservationStatus(str, enum.Enum):
    PENDING   = "pending"
    CONFIRMED = "confirmed"
    SEATED    = "seated"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW   = "no_show"


# ── ORM Models ────────────────────────────────────────────────────────────────

class Appointment(Base):
    __tablename__ = "appointments"

    id            = Column(Integer, primary_key=True, index=True)
    business_id   = Column(Integer, nullable=False, index=True)
    customer_id   = Column(Integer, nullable=True)              # auth-service user id
    customer_name = Column(String(200), nullable=False)
    customer_phone= Column(String(20), nullable=True)
    customer_email= Column(String(200), nullable=True)
    service_name  = Column(String(200), nullable=True)          # e.g. "Haircut", "Consultation"
    notes         = Column(Text, nullable=True)
    appointment_date = Column(Date, nullable=False, index=True)
    start_time    = Column(Time, nullable=False)
    end_time      = Column(Time, nullable=True)
    status        = Column(SAEnum(AppointmentStatus, name="appointmentstatus"),
                           default=AppointmentStatus.SCHEDULED)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Reservation(Base):
    __tablename__ = "reservations"

    id            = Column(Integer, primary_key=True, index=True)
    business_id   = Column(Integer, nullable=False, index=True)
    customer_id   = Column(Integer, nullable=True)
    customer_name = Column(String(200), nullable=False)
    customer_phone= Column(String(20), nullable=True)
    customer_email= Column(String(200), nullable=True)
    party_size    = Column(Integer, nullable=False, default=2)
    notes         = Column(Text, nullable=True)
    reservation_date = Column(Date, nullable=False, index=True)
    reservation_time = Column(Time, nullable=False)
    status        = Column(SAEnum(ReservationStatus, name="reservationstatus"),
                           default=ReservationStatus.PENDING)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AppointmentCreate(BaseModel):
    business_id: int
    customer_name: str
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    service_name: Optional[str] = None
    notes: Optional[str] = None
    appointment_date: date
    start_time: time
    end_time: Optional[time] = None


class AppointmentUpdate(BaseModel):
    appointment_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    service_name: Optional[str] = None
    notes: Optional[str] = None


class AppointmentResponse(BaseModel):
    id: int
    business_id: int
    customer_id: Optional[int]
    customer_name: str
    customer_phone: Optional[str]
    customer_email: Optional[str]
    service_name: Optional[str]
    notes: Optional[str]
    appointment_date: date
    start_time: time
    end_time: Optional[time]
    status: AppointmentStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AppointmentListResponse(BaseModel):
    total: int
    items: List[AppointmentResponse]


class ReservationCreate(BaseModel):
    business_id: int
    customer_name: str
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    party_size: int = 2
    notes: Optional[str] = None
    reservation_date: date
    reservation_time: time


class ReservationResponse(BaseModel):
    id: int
    business_id: int
    customer_id: Optional[int]
    customer_name: str
    customer_phone: Optional[str]
    customer_email: Optional[str]
    party_size: int
    notes: Optional[str]
    reservation_date: date
    reservation_time: time
    status: ReservationStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ReservationListResponse(BaseModel):
    total: int
    items: List[ReservationResponse]


class SlotAvailability(BaseModel):
    date: date
    total_slots: int
    booked_slots: int
    available_slots: int
    slots: List[str]                # list of available HH:MM time strings
