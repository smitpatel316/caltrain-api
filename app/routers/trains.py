from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from app.models.train import NextTrainResponse, HealthResponse
from app.models.stop import StopResponse, Stop
from app.services.gtfs_static import gtfs_static
from app.services.gtfs_rt import gtfs_rt
from app.services.next_train import next_train_service

router = APIRouter(prefix="/api/v1", tags=["trains"])


@router.get("/stops", response_model=StopResponse)
async def get_stops(agency: str = Query("RG", description="Agency ID")):
    """Get list of all Caltrain stops with lat/lon."""
    stops_data = gtfs_static.get_stops(agency)
    stops = [Stop(**s) for s in stops_data]

    return StopResponse(
        stops=stops,
        last_updated=gtfs_static.get_last_refresh_time() or "",
    )


@router.get("/next-train", response_model=NextTrainResponse)
async def get_next_train(
    origin_stop_id: str = Query(..., description="Origin stop ID (e.g., Burlingame stop_id)"),
    destination_stop_id: Optional[str] = Query(None, description="Destination stop ID (optional)"),
    direction: Optional[str] = Query(None, description="northbound or southbound (or 0/1)"),
    time_window_minutes: int = Query(120, description="Time window in minutes"),
    preferred_types: Optional[str] = Query(
        None, description="Comma-separated: local,limited,express,weekend,south_county"
    ),
):
    """Get next train(s) from origin stop.

    Core endpoint that computes best next trains based on GTFS static schedule
    and GTFS-RT real-time updates.
    """
    # Parse preferred types
    types_list = None
    if preferred_types:
        types_list = [t.strip().lower() for t in preferred_types.split(",")]

    try:
        result = next_train_service.get_next_trains(
            origin_stop_id=origin_stop_id,
            destination_stop_id=destination_stop_id,
            direction=direction,
            time_window_minutes=time_window_minutes,
            preferred_types=types_list,
        )

        return NextTrainResponse(**result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error computing next train: {str(e)}")


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    db_ok = False
    try:
        stops = gtfs_static.get_stops()
        db_ok = len(stops) > 0
    except Exception:
        pass

    return HealthResponse(
        status="healthy" if db_ok else "degraded",
        last_gtfs_refresh=gtfs_static.get_last_refresh_time(),
        last_rt_update=gtfs_rt.get_last_rt_update(),
        database_ok=db_ok,
    )


@router.get("/routes")
async def get_routes():
    """Get all Caltrain routes."""
    routes = gtfs_static.get_routes()
    return {"routes": routes, "last_updated": gtfs_static.get_last_refresh_time() or ""}
