from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    DB_SERVER: str
    DB_NAME: str
    USERNAME: str
    PASSWORD: str
    CAMERAS: dict = {
        "camera1": {
            "rtsp": "rtsp://admin:$adraPASS@192.168.50.150:554/",
            "bbox": {"x_min": 724, "y_min": 295, "x_max": 1291, "y_max": 956},
            "counting_line_x": 1130
        },
        "camera2": {
            "rtsp": "rtsp://admin:$adraPASS@192.168.50.150:554/",
            "bbox": {"x_min": 2713, "y_min": 234, "x_max": 3368, "y_max": 898},
            "counting_line_x": 2710
        }
    }
    # # for cam1
    # VIDEOS: dict = {
    #     "video": {
    #         "path": "./sample/cam1_2.mp4",
    #         "bbox": {"x_min": 724, "y_min": 295, "x_max": 1291, "y_max": 956},
    #         "counting_line_x": 1130
    #     }
    # }
    # DEFAULT_BBOX: dict = {"x_min": 724, "y_min": 295, "x_max": 1291, "y_max": 956}

    # for cam2
    VIDEOS: dict = {
        "video": {
            "path": "./sample/cam1_2.mp4",
            "bbox": {"x_min": 2713, "y_min": 234, "x_max": 3368, "y_max": 898},
            "counting_line_x": 2710
        }
    }
    DEFAULT_BBOX: dict = {"x_min": 2713, "y_min": 234, "x_max": 3368, "y_max": 898}

    DEFAULT_COUNTING_LINE_X: int = 2710
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_QUEUE_MAXLEN: int = 1000
    FRAME_RATE: int = 25
    QUALITY_THRESHOLD: float = 50.0  # کاهش آستانه کیفیت
    FRAMES_PATH: str = "output/frames"
    LOG_PATH: str = "output/logs/barcode_log.csv"
    CROPPED_IMAGES_PATH: str = "output/cropped_images"
    SYNC_INTERVAL: int = 60

    # Demand-driven processing settings
    PROCESSING_MODE: str = "demand_driven"  # "demand_driven" or "queue_based"

    # Frame extraction settings
    FRAME_EXTRACTION_TIMEOUT: int = 10  # seconds for FFmpeg timeout
    FRAME_CACHE_EXPIRE: int = 30  # seconds for Redis frame cache
    MAX_EXTRACTION_RETRIES: int = 3  # max retries for frame extraction

    # Production monitoring settings
    PRODUCTION_IDLE_THRESHOLD: float = 30.0  # seconds without ingot = idle
    PRODUCTION_SPEED_MONITOR: bool = True  # enable production speed monitoring

    # Camera connection settings
    CAMERA_RECONNECT_INTERVAL: float = 10.0  # seconds between reconnection attempts
    CAMERA_CONNECTION_TIMEOUT: float = 15.0  # seconds for connection timeout
    MAX_RECONNECT_ATTEMPTS: int = 5  # max reconnection attempts before giving up

    # System monitoring settings
    HEALTH_CHECK_INTERVAL: float = 60.0  # seconds between health checks
    PERFORMANCE_METRICS_WINDOW: int = 100  # number of recent measurements to keep
    ENABLE_SYSTEM_MONITORING: bool = True  # enable system resource monitoring

    # AI processing settings
    AI_CONFIDENCE_THRESHOLD: float = 0.7  # minimum confidence for detections
    AI_INFERENCE_TIMEOUT: float = 5.0  # seconds for AI inference timeout
    ENABLE_AI_CONFIDENCE_LOGGING: bool = True  # log low confidence warnings

    # Database sync settings
    DB_SYNC_BATCH_SIZE: int = 100  # records per sync batch
    DB_SYNC_RETRY_ATTEMPTS: int = 3  # max retry attempts for DB operations
    DB_CONNECTION_POOL_SIZE: int = 5  # database connection pool size

    # Logging settings
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    ENABLE_STRUCTURED_LOGGING: bool = True  # enable JSON structured logs
    LOG_FILE_ROTATION: bool = True  # enable log file rotation
    MAX_LOG_FILE_SIZE: str = "100MB"  # max size before rotation
    LOG_RETENTION_DAYS: int = 30  # days to keep log files

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()