from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services.gtfs_static import gtfs_static
from app.services.gtfs_rt import gtfs_rt
from app.services.cache import cache


class NextTrainService:
    """Core service for computing next train(s)."""

    def __init__(self):
        self.gtfs_static = gtfs_static
        self.gtfs_rt = gtfs_rt

    def _parse_gtfs_time(self, time_str: str, date_str: str) -> datetime:
        """Parse GTFS time format (HH:MM:SS) to datetime."""
        parts = time_str.split(":")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])

        # Handle times past midnight (24:xx:xx, 25:xx:xx)
        if hours >= 24:
            hours -= 24
            day_offset = 1
        else:
            day_offset = 0

        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])

        result = datetime(year, month, day, hours, minutes, seconds, tzinfo=timezone.utc)
        result += timedelta(days=day_offset)

        return result

    def _get_trips_for_stop(
        self,
        stop_id: str,
        direction_id: Optional[int] = None,
        service_ids: Optional[list[str]] = None,
    ) -> list[dict]:
        """Get all trips that stop at a given stop."""
        with self.gtfs_static.engine.connect() as conn:
            from sqlalchemy import text

            query = """
                SELECT DISTINCT st.trip_id, st.arrival_time, st.departure_time, st.stop_sequence,
                       t.route_id, t.service_id, t.trip_headsign, t.direction_id
                FROM stop_times st
                JOIN trips t ON st.trip_id = t.trip_id
                WHERE st.stop_id = :stop_id
            """
            params = {"stop_id": stop_id}

            if direction_id is not None:
                query += " AND t.direction_id = :direction_id"
                params["direction_id"] = direction_id

            if service_ids:
                placeholders = ",".join([f":service_{i}" for i in range(len(service_ids))])
                query += f" AND t.service_id IN ({placeholders})"
                for i, sid in enumerate(service_ids):
                    params[f"service_{i}"] = sid

            query += " ORDER BY st.departure_time"

            result = conn.execute(text(query), params)
            rows = result.fetchall()

        return [
            {
                "trip_id": row.trip_id,
                "arrival_time": row.arrival_time,
                "departure_time": row.departure_time,
                "stop_sequence": row.stop_sequence,
                "route_id": row.route_id,
                "service_id": row.service_id,
                "trip_headsign": row.trip_headsign,
                "direction_id": row.direction_id,
            }
            for row in rows
        ]

    def _get_stops_skipped(self, trip_id: str, origin_sequence: int) -> list[str]:
        """Get list of stops that this express train skips after origin."""
        cached = cache.get(f"skipped_{trip_id}", ttl_seconds=3600)
        if cached is not None:
            return cached

        stop_times = self.gtfs_static.get_stop_times_for_trip(trip_id)
        skipped = []

        for st in stop_times:
            if st["stop_sequence"] > origin_sequence:
                stop_id = st["stop_id"]
                # Check if this stop is typically skipped by limited/express
                # For now, we'll rely on GTFS-RT stop_time_updates for actual skips
                pass

        return skipped

    def _build_next_train(
        self,
        trip_data: dict,
        origin_stop_id: str,
        date_str: str,
        route_info: dict,
    ) -> dict:
        """Build NextTrain dict from trip data."""
        trip_id = trip_data["trip_id"]
        scheduled_departure = self._parse_gtfs_time(
            trip_data["departure_time"], date_str
        )

        # Get RT update for delay
        trip_update = self.gtfs_rt.get_trip_update(trip_id)
        delay_minutes = 0
        predicted_departure = scheduled_departure

        if trip_update:
            # Find stop time update for origin
            for stu in trip_update.get("stop_time_updates", []):
                if stu["stop_id"] == origin_stop_id:
                    if stu["departure_delay"] is not None:
                        delay_minutes = stu["departure_delay"] // 60
                        predicted_departure = scheduled_departure + timedelta(minutes=delay_minutes)
                    break

        # Get vehicle position
        vehicle_pos = self.gtfs_rt.get_vehicle_position(trip_id)

        # Get alerts
        alerts = self.gtfs_rt.get_alerts_for_trip(trip_id)

        # Classify train type
        train_type, train_color = self.gtfs_rt.classify_train_type(
            trip_headsign=trip_data.get("trip_headsign", ""),
            route_short_name=route_info.get("route_short_name", ""),
        )

        # Get skipped stops
        stops_skipped = []
        if train_type in ["limited", "express"]:
            origin_seq = trip_data["stop_sequence"]
            stops_skipped = self._get_stops_skipped(trip_id, origin_seq)

        # Build route short name from route_id (e.g., "401" for local, "K" for BART-like)
        route_short_name = route_info.get("route_short_name", trip_data["route_id"])

        return {
            "trip_id": trip_id,
            "train_number": route_short_name,
            "type": train_type,
            "color": train_color,
            "direction": "northbound" if trip_data["direction_id"] == 0 else "southbound",
            "scheduled_departure": scheduled_departure.isoformat(),
            "predicted_departure": predicted_departure.isoformat(),
            "delay_minutes": delay_minutes,
            "stops_skipped": stops_skipped,
            "vehicle_position": {
                "lat": vehicle_pos["lat"],
                "lon": vehicle_pos["lon"],
            }
            if vehicle_pos and vehicle_pos.get("lat") is not None
            else None,
            "alerts": alerts,
            "route_id": trip_data["route_id"],
            "route_short_name": route_short_name,
        }

    def get_next_trains(
        self,
        origin_stop_id: str,
        destination_stop_id: Optional[str] = None,
        direction: Optional[str] = None,
        time_window_minutes: int = 120,
        preferred_types: Optional[list[str]] = None,
    ) -> dict:
        """Get next trains from origin stop.

        Returns dict with 'next_trains', 'best_train', and 'last_updated'.
        """
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y%m%d")
        current_time = now.time()

        # Map direction string to id
        direction_id = None
        if direction:
            direction = direction.lower()
            if direction in ["northbound", "n", "0"]:
                direction_id = 0
            elif direction in ["southbound", "s", "1"]:
                direction_id = 1

        # Get active service IDs for today
        service_ids = self.gtfs_static.get_service_ids_for_date(date_str)
        if not service_ids:
            # Fallback: use any service_id (for debugging)
            service_ids = ["WKEND", "WKDY"]

        # Get trips at origin stop
        trips = self._get_trips_for_stop(
            stop_id=origin_stop_id,
            direction_id=direction_id,
            service_ids=service_ids if service_ids else None,
        )

        # Get route info
        routes = {r["route_id"]: r for r in self.gtfs_static.get_routes()}

        # Filter and build next trains
        next_trains = []
        cutoff_time = now + timedelta(minutes=time_window_minutes)

        for trip in trips:
            route_id = trip["route_id"]
            route_info = routes.get(route_id, {})

            # Skip if route not found
            if not route_info:
                continue

            # Parse departure time
            try:
                scheduled_departure = self._parse_gtfs_time(
                    trip["departure_time"], date_str
                )
            except (ValueError, IndexError):
                continue

            # Skip if past cutoff
            if scheduled_departure > cutoff_time:
                continue

            # Skip if in the past (more than 2 min ago)
            if scheduled_departure < now - timedelta(minutes=2):
                continue

            # Build train info
            train = self._build_next_train(trip, origin_stop_id, date_str, route_info)

            # Filter by destination if specified
            if destination_stop_id:
                trip_update = self.gtfs_rt.get_trip_update(trip["trip_id"])
                stops_after_origin = [
                    stu["stop_id"]
                    for stu in (trip_update.get("stop_time_updates", []) if trip_update else [])
                    if stu.get("stop_sequence", 0) > trip["stop_sequence"]
                ]
                if destination_stop_id not in stops_after_origin:
                    # Also check static stop_times
                    all_stops_after = self.gtfs_static.get_stop_times_for_trip(trip["trip_id"])
                    destination_found = False
                    origin_seq = trip["stop_sequence"]
                    for st in all_stops_after:
                        if st["stop_sequence"] > origin_seq:
                            if st["stop_id"] == destination_stop_id:
                                destination_found = True
                                break
                    if not destination_found:
                        continue

            # Filter by preferred types
            if preferred_types:
                if train["type"] not in preferred_types:
                    continue

            next_trains.append(train)

        # Sort by predicted departure
        next_trains.sort(
            key=lambda t: datetime.fromisoformat(t["predicted_departure"]).timestamp()
        )

        # Limit to reasonable number
        next_trains = next_trains[:20]

        # Determine best train (first one that's not significantly delayed)
        best_train = None
        for train in next_trains:
            if train["delay_minutes"] <= 10:
                best_train = train
                break

        if not best_train and next_trains:
            best_train = next_trains[0]

        return {
            "next_trains": next_trains,
            "best_train": best_train,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }


# Singleton instance
next_train_service = NextTrainService()
