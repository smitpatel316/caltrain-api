import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.services.gtfs_static import gtfs_static
from app.services.gtfs_rt import gtfs_rt

settings = get_settings()
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def refresh_gtfs_static():
    """Background job to refresh static GTFS data."""
    logger.info("Starting scheduled GTFS static refresh...")
    try:
        success = gtfs_static.refresh()
        if success:
            logger.info("GTFS static refresh completed successfully")
        else:
            logger.warning("GTFS static refresh completed with issues")
    except Exception as e:
        logger.error(f"GTFS static refresh failed: {e}")


def warm_rt_cache():
    """Background job to warm RT cache."""
    logger.info("Warming GTFS-RT cache...")
    try:
        gtfs_rt.fetch_trip_updates()
        gtfs_rt.fetch_vehicle_positions()
        gtfs_rt.fetch_alerts()
        logger.info("GTFS-RT cache warm completed")
    except Exception as e:
        logger.error(f"GTFS-RT cache warm failed: {e}")


def start_scheduler():
    """Start background scheduler for periodic tasks."""
    # Refresh static GTFS every 24 hours
    scheduler.add_job(
        refresh_gtfs_static,
        IntervalTrigger(hours=settings.gtfs_refresh_hours),
        id="gtfs_static_refresh",
        name="Refresh static GTFS data",
        replace_existing=True,
    )

    # Warm RT cache every 60 seconds
    scheduler.add_job(
        warm_rt_cache,
        IntervalTrigger(seconds=60),
        id="rt_cache_warm",
        name="Warm GTFS-RT cache",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Background scheduler started")


def stop_scheduler():
    """Stop background scheduler."""
    scheduler.shutdown()
    logger.info("Background scheduler stopped")
