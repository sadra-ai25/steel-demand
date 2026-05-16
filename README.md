# Steel Demand Monitoring System

![Python](https://img.shields.io/badge/Python-3.10-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-green) ![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-red) ![Redis](https://img.shields.io/badge/Redis-6.2-red) ![Docker](https://img.shields.io/badge/Docker-Compose-blue)

Demand-driven steel production monitoring system combining AI ingot counting and barcode reading in a unified pipeline. Processes RTSP camera streams and logs production data to SQL Server with real-time monitoring via REST API.

## Features

- **Demand-driven processing** — AI inference triggered only when production activity is detected, saving resources
- **Unified processor** — single pipeline handles both ingot counting and barcode reading per camera
- **Multi-camera support** — independently manage multiple RTSP camera streams
- **Redis frame cache** — frames are cached in Redis for decoupled producer/consumer processing
- **RabbitMQ queue** — reliable message passing between capture and processing stages
- **SQL Server integration** — production counts and barcode scans logged with timestamps
- **Health monitoring** — built-in system metrics, performance logging, and reconnect logic
- **Configurable thresholds** — AI confidence, idle detection, and frame interval all tunable via `.env`

## Tech Stack

| Component | Technology |
|---|---|
| AI Models | YOLOv8 (counting) + custom barcode detector |
| API Server | FastAPI + Uvicorn |
| Frame Cache | Redis 6.2 |
| Message Queue | RabbitMQ |
| Database | Microsoft SQL Server (pyodbc) |
| Containerization | Docker Compose |

## Architecture

```
RTSP Camera
      │
      ▼
 Camera Producer (Thread)
   - Captures frames at FRAME_INTERVAL
   - Caches in Redis with TTL
      │
      ▼
 Unified Processor (demand-driven)
   ├── Barcode Reader  →  barcode detected → SQL Server
   └── Ingot Counter   →  crossing line   → SQL Server
      │
      ▼
 FastAPI REST API  ←→  SQL Server / Redis
```

## Prerequisites

- Docker & Docker Compose
- YOLOv8 model weights in `src/ai/weights/`
- Microsoft SQL Server (reachable from container)
- ODBC Driver 17 for SQL Server

## Installation & Setup

```bash
# 1. Clone the repository
git clone https://github.com/sadra-ai25/steel-demand.git
cd steel-demand

# 2. Configure environment
cp .env.example .env   # edit with your actual values

# 3. Place model weights
mkdir -p src/ai/weights
cp /path/to/model.pt src/ai/weights/

# 4. Start services
docker compose up -d --build
```

## Configuration

| Key | Description | Example |
|---|---|---|
| `DB_SERVER` | SQL Server address | `192.168.1.100\sqlserver` |
| `DB_NAME` | Database name | `SteelDB` |
| `USERNAME` | SQL login | `sa` |
| `PASSWORD` | SQL password | `your_password_here` |
| `REDIS_HOST` | Redis hostname | `redis` |
| `REDIS_PORT` | Redis port | `6379` |
| `PROCESSING_MODE` | `demand_driven` or `continuous` | `demand_driven` |
| `AI_CONFIDENCE_THRESHOLD` | Minimum detection confidence | `0.7` |
| `FRAME_INTERVAL` | Capture every N seconds | `10` |
| `PRODUCTION_IDLE_THRESHOLD` | Seconds idle before pausing AI | `30.0` |
| `CAMERA_RECONNECT_INTERVAL` | Seconds between reconnect attempts | `10.0` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | System health, active processors, Redis/DB status |
| `POST` | `/start_camera/{camera_id}` | Start processing a camera stream |
| `POST` | `/stop_camera/{camera_id}` | Stop a specific camera processor |
| `GET` | `/status` | List all active processors and their state |
| `POST` | `/start_video` | Process a pre-recorded video file |

### Example: Start a Camera

```bash
curl -X POST http://localhost:5001/start_camera/cam1 \
  -H "Content-Type: application/json" \
  -d '{"rtsp_url": "rtsp://username:password@192.168.1.100:554/", "counting_line_x": 960}'
```

### Example: Health Check

```bash
curl http://localhost:5001/health
```

## Contributing

Pull requests are welcome. For major changes, please open an issue first.

## License

MIT
