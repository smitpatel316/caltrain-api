"""
SIRI (Service Interface for Real Time Information) router.

Provides real-time stop monitoring and vehicle tracking via SIRI endpoints.
"""

from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from app.services.siri_service import siri_service

router = APIRouter(prefix="/api/v1/siri", tags=["siri"])


@router.get("/stop-monitoring")
async def get_stop_monitoring(
    stop_id: str = Query(..., description="Stop ID (e.g., 'SF', 'MV', 'SJ')"),
    maximum_stop_visits: int = Query(10, ge=1, le=100, description="Max arrivals to return"),
    preview_interval_minutes: int = Query(60, ge=10, le=240, description="Time window in minutes"),
):
    """Get real-time arrival predictions for a stop.

    Returns real-time (SIRI) predicted arrivals at the specified stop.
    Data is cached for 60 seconds to respect rate limits.
    """
    try:
        result = siri_service.get_stop_monitoring(
            stop_id=stop_id,
            maximum_stop_visits=maximum_stop_visits,
            preview_interval_minutes=preview_interval_minutes,
        )

        if not result:
            raise HTTPException(
                status_code=503,
                detail="SIRI data unavailable - check API key or try again later"
            )

        # Parse into clean arrival format
        arrivals = siri_service.parse_arrivals(result)

        return {
            "stop_id": stop_id,
            "arrivals": arrivals,
            "raw_response": result,
            "last_updated": siri_service.get_last_update(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching stop monitoring: {str(e)}")


@router.get("/vehicle-monitoring")
async def get_vehicle_monitoring(
    vehicle_id: Optional[str] = Query(None, description="Specific vehicle ID"),
    trip_id: Optional[str] = Query(None, description="Trip ID to track"),
    maximum_vehicles: int = Query(10, ge=1, le=50, description="Max vehicles to return"),
):
    """Get real-time vehicle location(s).

    Track a specific vehicle by ID or trip ID.
    Returns current position, heading, and speed data.
    """
    if not vehicle_id and not trip_id:
        raise HTTPException(
            status_code=400,
            detail="Either vehicle_id or trip_id is required"
        )

    try:
        result = siri_service.get_vehicle_monitoring(
            vehicle_id=vehicle_id,
            trip_id=trip_id,
            maximum_vehicles=maximum_vehicles,
        )

        if not result:
            raise HTTPException(
                status_code=503,
                detail="Vehicle monitoring unavailable - check API key or try again later"
            )

        return {
            "vehicle_id": vehicle_id,
            "trip_id": trip_id,
            "data": result,
            "last_updated": siri_service.get_last_update(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching vehicle monitoring: {str(e)}")


@router.get("/services-at-stops")
async def get_services_at_stops(
    stop_ids: str = Query(..., description="Comma-separated stop IDs (e.g., 'SF,MV,SJ')"),
    maximum_stops: int = Query(20, ge=1, le=100, description="Max stops to return"),
):
    """Get all routes/services that serve specified stops.

    Returns information about which transit lines serve each stop,
    useful for multi-modal trip planning.
    """
    try:
        stop_list = [s.strip() for s in stop_ids.split(",") if s.strip()]

        if not stop_list:
            raise HTTPException(status_code=400, detail="At least one stop_id is required")

        if len(stop_list) > 50:
            raise HTTPException(status_code=400, detail="Maximum 50 stops per request")

        result = siri_service.get_service_at_stops(
            stop_ids=stop_list,
            maximum_stops=maximum_stops,
        )

        if not result:
            raise HTTPException(
                status_code=503,
                detail="Services data unavailable - check API key or try again later"
            )

        return {
            "stop_ids": stop_list,
            "data": result,
            "last_updated": siri_service.get_last_update(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching services: {str(e)}")


@router.get("/arrivals")
async def get_arrivals(
    stop_id: str = Query(..., description="Stop ID"),
    limit: int = Query(10, ge=1, le=50, description="Max arrivals to return"),
):
    """Get simplified arrivals list for a stop.

    This is a convenience endpoint that returns a clean, parsed
    list of upcoming arrivals without raw SIRI data.
    """
    try:
        result = siri_service.get_stop_monitoring(
            stop_id=stop_id,
            maximum_stop_visits=limit,
        )

        if not result:
            return {"stop_id": stop_id, "arrivals": [], "message": "No data available"}

        arrivals = siri_service.parse_arrivals(result)

        return {
            "stop_id": stop_id,
            "arrivals": arrivals,
            "count": len(arrivals),
            "last_updated": siri_service.get_last_update(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching arrivals: {str(e)}")
