import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import get_settings
from app.routers import trains, presets
from app.routers.siri import router as siri_router
from app.routers.holidays import router as holidays_router
from app.tasks import start_scheduler, stop_scheduler
from app.services.gtfs_static import gtfs_static
from app.utils.exceptions import (
    CaltrainAPIError,
    GTFSFetchError,
    GTFSParseError,
    GTRTParseError,
    DatabaseError,
    RateLimitExceededError,
    NetworkUnavailableError,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager.

    Handles startup and shutdown of application resources:
    - GTFS static data refresh
    - Background scheduler for periodic tasks
    """
    logger.info("Starting Caltrain API Server...")

    # Log configuration warnings
    config_warnings = settings.validate()
    for warning in config_warnings:
        logger.warning(f"Config: {warning}")

    # Initialize and refresh GTFS static data
    try:
        gtfs_static.refresh()
        logger.info("Initial GTFS static data loaded")
    except Exception as e:
        logger.warning(f"Initial GTFS load failed (will retry in background): {e}")

    # Start background scheduler for periodic refresh
    start_scheduler()

    yield

    # Shutdown
    logger.info("Shutting down Caltrain API Server...")
    stop_scheduler()
    logger.info("Caltrain API Server stopped")


# Create FastAPI application
app = FastAPI(
    title="Caltrain API",
    description="""
## Caltrain Transit API

Backend API providing real-time Caltrain transit information.

### Features
- **GTFS Static Data**: Scheduled stops, routes, and timetables
- **GTFS-RT Real-Time**: Live trip updates, vehicle positions, and service alerts
- **SIRI Stop Monitoring**: Real-time arrival predictions
- **Train Classification**: Local (gray), Limited (yellow), Express (red), Weekend (green), South County (orange)
- **User Presets**: Save favorite routes for quick access

### Rate Limits
Default: 60 requests/hour. Contact 511sfbaydeveloperresources@googlegroups.com to increase.

### Authentication
Set `FIVE_ELEVEN_API_KEY` environment variable with your token from 511.org/open-data/token
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# CORS middleware - configure allowed origins for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Set specific origins for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(CaltrainAPIError)
async def caltrain_api_exception_handler(request: Request, exc: CaltrainAPIError):
    """Handle custom CaltrainAPI exceptions."""
    logger.error(f"CaltrainAPIError: {exc.message}", extra={"details": exc.details})

    status_code = 500
    if isinstance(exc, RateLimitExceededError):
        status_code = 429
    elif isinstance(exc, NetworkUnavailableError):
        status_code = 503
    elif isinstance(exc, (GTFSFetchError, GTRTParseError)):
        status_code = 502
    elif isinstance(exc, GTFSParseError):
        status_code = 422
    elif isinstance(exc, DatabaseError):
        status_code = 500

    return JSONResponse(
        status_code=status_code,
        content={
            "error": exc.message,
            "type": exc.__class__.__name__,
            "details": exc.details,
        },
    )


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """Handle Pydantic validation errors."""
    logger.warning(f"Validation error: {exc}")

    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation error",
            "details": exc.errors(),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle FastAPI HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.exception(f"Unexpected error: {exc}")

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "type": exc.__class__.__name__,
        },
    )


# Include routers
app.include_router(trains.router)
app.include_router(presets.router)
app.include_router(siri_router)
app.include_router(holidays_router)


@app.get("/", tags=["info"])
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Caltrain API",
        "version": "1.0.0",
        "description": "Real-time Caltrain transit information",
        "documentation": {
            "swagger": "/docs",
            "redoc": "/redoc",
        },
        "endpoints": {
            "health": "/api/v1/health",
            "stops": "/api/v1/stops",
            "routes": "/api/v1/routes",
            "next_train": "/api/v1/next-train",
            "presets": "/api/v1/presets",
            "siri_stop_monitoring": "/api/v1/siri/stop-monitoring",
            "siri_arrivals": "/api/v1/siri/arrivals",
            "siri_vehicle": "/api/v1/siri/vehicle-monitoring",
        },
        "data_sources": {
            "511_org": "https://511.org/open-data/transit",
            "api_key": "https://511.org/open-data/token",
        },
    }


@app.get("/api/v1/health", tags=["health"])
async def health_check():
    """Health check endpoint with detailed status."""
    from app.services.gtfs_rt import gtfs_rt

    db_ok = gtfs_static.is_data_loaded() if hasattr(gtfs_static, 'is_data_loaded') else False

    try:
        stops = gtfs_static.get_stops()
        db_ok = len(stops) > 0
    except Exception:
        db_ok = False

    rt_ok = gtfs_rt.get_last_rt_update() is not None

    overall_status = "healthy" if (db_ok and rt_ok) else "degraded" if db_ok else "unhealthy"

    return {
        "status": overall_status,
        "database": {
            "ok": db_ok,
            "last_gtfs_refresh": gtfs_static.get_last_refresh_time(),
        },
        "realtime": {
            "ok": rt_ok,
            "last_rt_update": gtfs_rt.get_last_rt_update(),
        },
        "configuration": {
            "api_key_configured": bool(settings.five_eleven_api_key),
            "debug_mode": settings.debug,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.debug,
    )
