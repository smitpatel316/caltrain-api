from pydantic import BaseModel, Field
from typing import Optional


class Stop(BaseModel):
    id: str = Field(alias="stop_id")
    name: str = Field(alias="stop_name")
    lat: float = Field(alias="stop_lat")
    lon: float = Field(alias="stop_lon")
    zone_id: Optional[str] = Field(None, alias="zone_id")
    location_type: Optional[int] = Field(0, alias="location_type")

    class Config:
        populate_by_name = True


class StopResponse(BaseModel):
    stops: list[Stop]
    last_updated: str
