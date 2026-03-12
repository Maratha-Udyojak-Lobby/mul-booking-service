from datetime import date, time, timedelta
from typing import Optional
import os

import jwt
from fastapi import FastAPI, Depends, HTTPException, Query, Header, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.database import get_db, init_db
from app.models import (
    Appointment, AppointmentCreate, AppointmentUpdate,
    AppointmentResponse, AppointmentListResponse, AppointmentStatus,
    Reservation, ReservationCreate, ReservationResponse,
    ReservationListResponse, ReservationStatus, SlotAvailability,
)

init_db()

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "mul-super-secret-key-change-in-production")
JWT_ALGORITHM  = os.getenv("JWT_ALGORITHM", "HS256")

app = FastAPI(
    title="MUL Booking Service",
    version="1.0.0",
    description="Appointments and reservations management",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_user_id(authorization: Optional[str]) -> Optional[int]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    try:
        payload = jwt.decode(parts[1], JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return int(payload.get("sub", 0)) or None
    except jwt.InvalidTokenError:
        return None


def _build_slots(booked_times: list, open_hour: int = 9, close_hour: int = 18, slot_minutes: int = 30) -> list[str]:
    """Return list of HH:MM strings that are not already booked."""
    slots = []
    current = time(open_hour, 0)
    close  = time(close_hour, 0)
    while current < close:
        if current not in booked_times:
            slots.append(current.strftime("%H:%M"))
        h, m = divmod(current.hour * 60 + current.minute + slot_minutes, 60)
        current = time(h % 24, m)
    return slots


@app.on_event("startup")
async def startup_event():
    init_db()


@app.get("/", summary="Booking Service Root")
async def root() -> dict:
    return {"message": "MUL Booking Service is running"}


@app.get("/health", summary="Health Check")
async def health() -> dict:
    return {"status": "ok", "service": "booking-service"}


# ══════════════════════════════════════════════════════════
#  APPOINTMENTS
# ══════════════════════════════════════════════════════════

@app.get("/api/v1/appointments/slots", summary="Get Available Appointment Slots", response_model=SlotAvailability)
async def get_slots(
    business_id: int = Query(...),
    date_str: str = Query(..., alias="date", description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> SlotAvailability:
    check_date = date.fromisoformat(date_str)
    booked = db.query(Appointment).filter(
        Appointment.business_id == business_id,
        Appointment.appointment_date == check_date,
        Appointment.status.notin_([AppointmentStatus.CANCELLED]),
    ).all()
    booked_times = [a.start_time for a in booked]
    available = _build_slots(booked_times)
    total_slots = len(_build_slots([]))
    return SlotAvailability(
        date=check_date,
        total_slots=total_slots,
        booked_slots=len(booked_times),
        available_slots=len(available),
        slots=available,
    )


@app.post("/api/v1/appointments", summary="Create Appointment", response_model=AppointmentResponse, status_code=201)
async def create_appointment(
    data: AppointmentCreate,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> AppointmentResponse:
    user_id = _get_user_id(authorization)

    # Conflict check — same business, same date, same start_time, not cancelled
    conflict = db.query(Appointment).filter(
        Appointment.business_id == data.business_id,
        Appointment.appointment_date == data.appointment_date,
        Appointment.start_time == data.start_time,
        Appointment.status.notin_([AppointmentStatus.CANCELLED]),
    ).first()
    if conflict:
        raise HTTPException(status_code=409, detail="This time slot is already booked")

    appointment = Appointment(**data.model_dump(), customer_id=user_id)
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return appointment


@app.get("/api/v1/appointments", summary="List Appointments", response_model=AppointmentListResponse)
async def list_appointments(
    business_id: Optional[int] = Query(None),
    appointment_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> AppointmentListResponse:
    user_id = _get_user_id(authorization)
    query = db.query(Appointment)
    if business_id:
        query = query.filter(Appointment.business_id == business_id)
    if appointment_date:
        query = query.filter(Appointment.appointment_date == date.fromisoformat(appointment_date))
    if user_id and not business_id:
        query = query.filter(Appointment.customer_id == user_id)
    items = query.order_by(Appointment.appointment_date, Appointment.start_time).all()
    return AppointmentListResponse(total=len(items), items=items)


@app.get("/api/v1/appointments/{appointment_id}", summary="Get Appointment", response_model=AppointmentResponse)
async def get_appointment(appointment_id: int, db: Session = Depends(get_db)) -> AppointmentResponse:
    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt


@app.patch(
    "/api/v1/appointments/{appointment_id}/reschedule",
    summary="Reschedule Appointment",
    response_model=AppointmentResponse,
)
async def reschedule_appointment(
    appointment_id: int,
    data: AppointmentUpdate,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> AppointmentResponse:
    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status in (AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED):
        raise HTTPException(status_code=400, detail=f"Cannot reschedule a {appt.status} appointment")

    new_date = data.appointment_date or appt.appointment_date
    new_time = data.start_time or appt.start_time

    # Conflict check for the new slot
    conflict = db.query(Appointment).filter(
        Appointment.id != appointment_id,
        Appointment.business_id == appt.business_id,
        Appointment.appointment_date == new_date,
        Appointment.start_time == new_time,
        Appointment.status.notin_([AppointmentStatus.CANCELLED]),
    ).first()
    if conflict:
        raise HTTPException(status_code=409, detail="The new time slot is already booked")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(appt, field, value)
    appt.status = AppointmentStatus.SCHEDULED
    db.commit()
    db.refresh(appt)
    return appt


@app.patch(
    "/api/v1/appointments/{appointment_id}/cancel",
    summary="Cancel Appointment",
    response_model=AppointmentResponse,
)
async def cancel_appointment(
    appointment_id: int,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> AppointmentResponse:
    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status == AppointmentStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Appointment is already cancelled")
    appt.status = AppointmentStatus.CANCELLED
    db.commit()
    db.refresh(appt)
    return appt


# ══════════════════════════════════════════════════════════
#  RESERVATIONS
# ══════════════════════════════════════════════════════════

@app.get("/api/v1/reservations/availability", summary="Check Table Availability")
async def check_availability(
    business_id: int = Query(...),
    date_str: str = Query(..., alias="date", description="YYYY-MM-DD"),
    party_size: int = Query(2, ge=1),
    db: Session = Depends(get_db),
) -> dict:
    check_date = date.fromisoformat(date_str)
    reserved = db.query(Reservation).filter(
        Reservation.business_id == business_id,
        Reservation.reservation_date == check_date,
        Reservation.status.notin_([ReservationStatus.CANCELLED]),
    ).count()
    # Assume 20 tables per business (configurable later)
    capacity = 20
    available = max(0, capacity - reserved)
    return {
        "business_id": business_id,
        "date": check_date,
        "party_size_requested": party_size,
        "reservations_count": reserved,
        "capacity": capacity,
        "available_tables": available,
        "is_available": available > 0,
    }


@app.post("/api/v1/reservations", summary="Create Reservation", response_model=ReservationResponse, status_code=201)
async def create_reservation(
    data: ReservationCreate,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> ReservationResponse:
    user_id = _get_user_id(authorization)

    # Basic capacity check
    reserved = db.query(Reservation).filter(
        Reservation.business_id == data.business_id,
        Reservation.reservation_date == data.reservation_date,
        Reservation.reservation_time == data.reservation_time,
        Reservation.status.notin_([ReservationStatus.CANCELLED]),
    ).count()
    if reserved >= 20:
        raise HTTPException(status_code=409, detail="No tables available at this time")

    reservation = Reservation(**data.model_dump(), customer_id=user_id)
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    return reservation


@app.get("/api/v1/reservations", summary="List Reservations", response_model=ReservationListResponse)
async def list_reservations(
    business_id: Optional[int] = Query(None),
    reservation_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> ReservationListResponse:
    user_id = _get_user_id(authorization)
    query = db.query(Reservation)
    if business_id:
        query = query.filter(Reservation.business_id == business_id)
    if reservation_date:
        query = query.filter(Reservation.reservation_date == date.fromisoformat(reservation_date))
    if user_id and not business_id:
        query = query.filter(Reservation.customer_id == user_id)
    items = query.order_by(Reservation.reservation_date, Reservation.reservation_time).all()
    return ReservationListResponse(total=len(items), items=items)


@app.get("/api/v1/reservations/{reservation_id}", summary="Get Reservation", response_model=ReservationResponse)
async def get_reservation(reservation_id: int, db: Session = Depends(get_db)) -> ReservationResponse:
    res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return res


@app.patch(
    "/api/v1/reservations/{reservation_id}/cancel",
    summary="Cancel Reservation",
    response_model=ReservationResponse,
)
async def cancel_reservation(
    reservation_id: int,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> ReservationResponse:
    res = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if res.status == ReservationStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="Reservation is already cancelled")
    res.status = ReservationStatus.CANCELLED
    db.commit()
    db.refresh(res)
    return res
