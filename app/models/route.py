from pydantic import BaseModel, Field
from typing import Optional


class Route(BaseModel):
    id: str = Field(alias="route_id")
    short_name: str = Field(alias="route_short_name")
    long_name: str = Field(alias="route_long_name")
    type: int = Field(alias="route_type")
    color: Optional[str] = Field(None, alias="route_color")
    text_color: Optional[str] = Field(None, alias="route_text_color")

    class Config:
        populate_by_name = True


class Trip(BaseModel):
    trip_id: str
    route_id: str
    service_id: str
    trip_headsign: Optional[str] = None
    direction_id: int = 0


class RouteResponse(BaseModel):
    routes: list[Route]
    last_updated: str
