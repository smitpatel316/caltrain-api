# Caltrain API Server

**Real-time Caltrain transit information backend API**

A production-ready FastAPI backend providing real-time Caltrain transit data including scheduled GTFS information, GTFS-RT real-time updates, SIRI stop monitoring, and holiday schedule handling.

## Features

- **GTFS Static Data**: Fetches and parses official Caltrain static schedules (stops, routes, trips, stop times, calendar)
- **GTFS-RT Real-Time**: Parses TripUpdates, VehiclePositions, and ServiceAlerts from 511.org protobuf feeds
- **SIRI Stop Monitoring**: Real-time arrival predictions via SIRI-SM endpoint
- **Holiday Handling**: Automatic holiday schedule detection (weekend/holiday vs weekday service)
- **Train Classification**: Local (gray), Limited (yellow), Express (red), Weekend (green), South County (orange)
- **Rate Limiting**: Token bucket algorithm with exponential backoff to protect 511.org API
- **Comprehensive Error Handling**: Custom exceptions, proper HTTP status codes, detailed error messages
- **Background Tasks**: Automatic GTFS refresh every 24h and RT cache warming every 60s
- **SQLite Caching**: Persistent storage for parsed GTFS data and API responses

## Quick Start

### 1. Install Dependencies

```bash
cd caltrain-api
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env and set FIVE_ELEVEN_API_KEY=your_actual_token_here
```

Get your API key at: https://511.org/open-data/token

### 3. Run the Server

```bash
uvicorn app.main:app --reload
```

Server starts at `http://localhost:8000`

- API docs: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Health check: http://localhost:8000/api/v1/health

### 4. Docker Deployment

```bash
docker build -t caltrain-api .
docker run -p 8000:8000 --env-file .env caltrain-api
```

## API Endpoints

### Core Transit Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/stops` | List all Caltrain stops with lat/lon |
| GET | `/api/v1/routes` | List all Caltrain routes |
| GET | `/api/v1/next-train` | Get next train(s) from origin stop |
| GET | `/api/v1/health` | Health check with DB/RT status |

### Real-Time Endpoints (SIRI)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/siri/stop-monitoring` | Real-time arrivals at a stop |
| GET | `/api/v1/siri/arrivals` | Simplified arrivals list |
| GET | `/api/v1/siri/vehicle-monitoring` | Track specific vehicle |
| GET | `/api/v1/siri/services-at-stops` | Routes serving specified stops |

### Schedule & Holidays

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/schedule/today` | Today's schedule info |
| GET | `/api/v1/schedule/{date}` | Schedule for specific date |
| GET | `/api/v1/holidays/upcoming` | Upcoming holidays |
| GET | `/api/v1/holidays/check` | Check if date is a holiday |

### User Presets

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/presets` | List all presets |
| GET | `/api/v1/presets/{id}` | Get specific preset |
| POST | `/api/v1/presets` | Create new preset |
| DELETE | `/api/v1/presets/{id}` | Delete preset |

## Endpoint Details

### GET /api/v1/next-train

**Required Query Parameters:**
- `origin_stop_id` - The stop ID to depart from (e.g., `SF`, `MV`, `SJ`)

**Optional Query Parameters:**
- `destination_stop_id` - Filter trains that stop at this destination
- `direction` - `northbound` or `southbound` (or `0`/`1`)
- `time_window_minutes` - How far ahead to look (default: 120)
- `preferred_types` - Comma-separated: `local`, `limited`, `express`, `weekend`, `south_county`

**Example:**
```bash
# Get next trains from San Francisco to Millbrae
curl "http://localhost:8000/api/v1/next-train?origin_stop_id=SF&destination_stop_id=MB"

# Get only express trains from Mountain View
curl "http://localhost:8000/api/v1/next-train?origin_stop_id=MV&preferred_types=express"
```

**Response:**
```json
{
  "next_trains": [
    {
      "trip_id": "12345",
      "train_number": "401",
      "type": "Limited",
      "color": "#FFD700",
      "direction": "northbound",
      "scheduled_departure": "2026-03-30T08:15:00-07:00",
      "predicted_departure": "2026-03-30T08:18:00-07:00",
      "delay_minutes": 3,
      "stops_skipped": ["Millbrae"],
      "vehicle_position": {"lat": 37.5, "lon": -122.3},
      "alerts": []
    }
  ],
  "best_train": { ... },
  "last_updated": "2026-03-30T08:20:00-07:00"
}
```

### GET /api/v1/siri/arrivals

**Required Query Parameters:**
- `stop_id` - Stop ID to get arrivals for

**Example:**
```bash
curl "http://localhost:8000/api/v1/siri/arrivals?stop_id=SF&limit=5"
```

## Train Types & Colors

| Type | Color | Route Prefixes | Description |
|------|-------|----------------|-------------|
| Local | Gray (#808080) | 1xx | Stops at all stations |
| Limited | Yellow (#FFD700) | 4xx | Skips some local stops |
| Express | Red (#FF0000) | 5xx | Only stops at major stations |
| Weekend | Green (#00FF00) | 6xx | Weekend-specific service |
| South County | Orange (#FFA500) | 8xx | Extended service to Gilroy |

## Rate Limiting

The 511.org free API tier allows 60 requests/hour. This server implements:

- **Token Bucket Algorithm**: Tracks requests over sliding 1-hour window
- **Exponential Backoff**: Retries transient failures with increasing delays (2s, 4s, 8s, max 60s)
- **Cache TTLs**: RT data cached 60-90s, static data cached 1-24h
- **Graceful Degradation**: Falls back to Caltrans public GTFS if 511.org fails

**To request higher limits**: Email transitdata@511.org with your key, desired limit (e.g., 300/hr), and description.

## Holiday Schedule Handling

The server automatically detects:
- US Federal holidays (New Year's, MLK Day, Presidents Day, Memorial Day, etc.)
- Applies correct service type: `weekday`, `weekend`, or `special`
- Handles holiday-on-weekend observations

## Deployment

### Render.com (Recommended - Free Tier)

1. Fork this repo to GitHub
2. Create new Web Service on Render
3. Connect your GitHub repo
4. Set environment variables:
   - `FIVE_ELEVEN_API_KEY`: Your 511.org API key
   - `DEBUG`: `false` (for production)
5. Deploy!

### Fly.io

```bash
fly launch
fly secrets set FIVE_ELEVEN_API_KEY=your_key_here
fly deploy
```

### Railway

1. Create new project
2. Add environment variables
3. Deploy from GitHub

## Project Structure

```
caltrain-api/
├── app/
│   ├── main.py              # FastAPI app + exception handlers
│   ├── config.py            # Settings from environment
│   ├── models/              # Pydantic models
│   │   ├── stop.py
│   │   ├── route.py
│   │   └── train.py
│   ├── services/
│   │   ├── gtfs_static.py   # GTFS fetch/parse/SQLite storage
│   │   ├── gtfs_rt.py       # GTFS-RT protobuf parsing
│   │   ├── siri_service.py  # SIRI stop/vehicle monitoring
│   │   ├── holidays_service.py  # Holiday schedule detection
│   │   ├── next_train.py    # Core next-train logic
│   │   └── cache.py         # Disk-based TTL cache
│   ├── routers/
│   │   ├── trains.py        # /stops, /next-train, /routes
│   │   ├── presets.py       # User presets CRUD
│   │   ├── siri.py          # SIRI endpoints
│   │   └── holidays.py      # Holiday endpoints
│   ├── tasks.py             # APScheduler background jobs
│   └── utils/
│       ├── cache.py
│       ├── geofence_helpers.py
│       ├── rate_limiter.py  # Token bucket rate limiter
│       └── exceptions.py    # Custom exception classes
├── tests/                   # Unit and integration tests
├── data/                    # Cached GTFS + SQLite DB (gitignored)
├── requirements.txt
├── Dockerfile
├── pytest.ini
├── .env.example
└── README.md
```

## Testing

```bash
# Run all unit tests
pytest tests/ -v

# Run excluding integration tests
pytest tests/ -v -m "not integration"

# Run specific test file
pytest tests/test_holidays.py -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `FIVE_ELEVEN_API_KEY` | (required) | 511.org API key |
| `GTFS_REFRESH_HOURS` | 24 | Hours between GTFS refreshes |
| `CACHE_TTL_MINUTES` | 5 | Default cache TTL |
| `DEBUG` | false | Enable debug mode |
| `RATE_LIMIT_REQUESTS_PER_HOUR` | 60 | API rate limit |

## Error Responses

All errors return JSON with consistent format:

```json
{
  "error": "Human-readable error message",
  "type": "ExceptionClassName",
  "details": { ... }
}
```

Common HTTP status codes:
- 200: Success
- 400: Bad Request (missing/invalid parameters)
- 404: Not Found
- 422: Validation Error
- 429: Rate Limit Exceeded
- 500: Internal Server Error
- 502: Bad Gateway (upstream API error)
- 503: Service Unavailable

## Future Phases

- **Phase 2**: Native iOS App (SwiftUI + WidgetKit)
- **Phase 3**: Native Android App (Kotlin + Compose + Glance)

Both mobile apps will call this server's JSON API only - no direct 511.org calls.

## License

MIT License
