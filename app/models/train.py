from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class VehiclePosition(BaseModel):
    lat: float
    lon: float
    bearing: Optional[float] = None
    speed: Optional[float] = None


class StopTimeUpdate(BaseModel):
    stop_id: str
    stop_sequence: int
    arrival_delay_minutes: Optional[int] = None
    departure_delay_minutes: Optional[int] = None
    schedule_relationship: str = "SCHEDULED"


class NextTrain(BaseModel):
    trip_id: str
    train_number: str
    type: str  # local, limited, express, weekend, south_county
    color: str  # hex color
    direction: str  # northbound or southbound
    scheduled_departure: str  # ISO timestamp
    predicted_departure: str  # ISO timestamp
    delay_minutes: int
    stops_skipped: list[str] = []
    vehicle_position: Optional[VehiclePosition] = None
    alerts: list[str] = []
    route_id: str
    route_short_name: str


class NextTrainResponse(BaseModel):
    next_trains: list[NextTrain]
    best_train: Optional[NextTrain] = None
    last_updated: str


class Preset(BaseModel):
    id: Optional[int] = None
    name: str
    origin_stop_id: str
    destination_stop_id: Optional[str] = None
    direction: str  # northbound or southbound
    preferred_types: list[str] = ["local", "limited", "express"]


class PresetCreate(BaseModel):
    name: str
    origin_stop_id: str
    destination_stop_id: Optional[str] = None
    direction: str
    preferred_types: list[str] = ["local", "limited", "express"]


class HealthResponse(BaseModel):
    status: str
    last_gtfs_refresh: Optional[str] = None
    last_rt_update: Optional[str] = None
    database_ok: bool = False
