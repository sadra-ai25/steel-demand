from fastapi import APIRouter, UploadFile, File, HTTPException, Request, FastAPI
from threading import Thread, Event
import tempfile
import time
import os
import logging
from pydantic import BaseModel

# --- وارد کردن تمام توابع مورد نیاز از ماژول‌های دیگر
from capture.producer import camera_producer, video_producer
from processing.frame_consumer import frame_consumer
from processing.unified_processor import UnifiedProcessor
from config.config import settings
from utils.enhanced_logger import EnhancedLogger

# --- تنظیمات اولیه ---
router = APIRouter()
logger = logging.getLogger(__name__)
enhanced_logger = EnhancedLogger("API")

# --- مدل‌های پاسخ ---
class StatusResponse(BaseModel):
    status: str
    processor_id: str

class HealthResponse(BaseModel):
    status: str
    processing_mode: str
    active_processors: dict
    system_info: dict

# ===================================================================
# --- توابع منطقی (بخش مرکزی برنامه) ---
# ===================================================================

def start_camera_processor_logic(camera_id: str, app: FastAPI):
    """منطق اصلی برای راه‌اندازی یک پردازشگر دوربین."""
    active_processors = app.state.active_processors
    if camera_id in active_processors:
        logger.warning(f"Processor for camera {camera_id} is already running.")
        return

    # Check processing mode
    if settings.PROCESSING_MODE == "demand_driven":
        # Use unified processor (demand-driven)
        logger.info(f"Starting unified processor for camera: {camera_id}")
        stop_event = Event()

        processor = UnifiedProcessor(camera_id, 'camera')
        processor_thread = Thread(
            target=processor.start_processing,
            args=(stop_event,),
            name=f"UnifiedProcessor-{camera_id}"
        )

        processor_thread.start()

        active_processors[camera_id] = {
            "processor": processor,
            "processor_thread": processor_thread,
            "stop_event": stop_event,
            "type": "camera",
            "mode": "unified"
        }

        enhanced_logger.log_production_started(camera_id)
        logger.info(f"✅ Unified processor for camera {camera_id} started successfully.")

    else:
        # Use traditional producer-consumer (legacy)
        logger.info(f"Starting traditional producer-consumer for camera: {camera_id}")
        stop_event = Event()

        producer = Thread(target=camera_producer, args=(camera_id, stop_event), name=f"Producer-{camera_id}")
        consumer = Thread(target=frame_consumer, args=(camera_id, None, 'camera', stop_event), name=f"Consumer-{camera_id}")

        producer.start()
        consumer.start()

        active_processors[camera_id] = {
            "producer_thread": producer,
            "consumer_thread": consumer,
            "stop_event": stop_event,
            "type": "camera",
            "mode": "traditional"
        }
        logger.info(f"✅ Traditional processor for camera {camera_id} started successfully.")

def stop_processor_logic(processor_id: str, app: FastAPI):
    """منطق اصلی برای توقف هر نوع پردازشگر."""
    active_processors = app.state.active_processors
    if processor_id not in active_processors:
        logger.warning(f"Attempted to stop a non-existent processor: {processor_id}")
        return

    processor_info = active_processors[processor_id]

    logger.info(f"Setting stop event for processor {processor_id}")
    processor_info["stop_event"].set()

    # Handle different processor modes
    if processor_info.get("mode") == "unified":
        # Unified processor
        processor = processor_info.get("processor")
        if processor:
            processor.stop_processing()

        processor_thread = processor_info.get("processor_thread")
        if processor_thread:
            processor_thread.join(timeout=10.0)

        enhanced_logger.log_production_stopped(
            processor_id,
            "Manual stop requested",
            0.0
        )

    else:
        # Traditional producer-consumer
        producer_thread = processor_info.get("producer_thread")
        consumer_thread = processor_info.get("consumer_thread")

        if producer_thread:
            producer_thread.join(timeout=5.0)
        if consumer_thread:
            consumer_thread.join(timeout=5.0)

    # Clean up temporary files for video processing
    if processor_info.get("type") == "video":
        temp_file = processor_info.get("temp_file")
        if temp_file and os.path.exists(temp_file):
            os.unlink(temp_file)
            logger.info(f"Temporary file {temp_file} deleted.")

    del active_processors[processor_id]
    logger.info(f"Processor {processor_id} stopped and resources cleaned up.")

# ===================================================================
# --- توابع سازنده رویداد (برای اتصال در main.py) ---
# ===================================================================

def create_startup_handler(app: FastAPI):
    """یک تابع async برای رویداد startup ایجاد می‌کند."""
    async def startup():
        logger.info("Application startup: Initializing state and processors...")
        app.state.active_processors = {}
        for camera_id in settings.CAMERAS.keys():
            start_camera_processor_logic(camera_id, app)
        logger.info("All configured camera processors have been initiated.")
    return startup

def create_shutdown_handler(app: FastAPI):
    """یک تابع برای رویداد shutdown ایجاد می‌کند."""
    def shutdown():
        logger.info("Application shutdown: Stopping all active processors...")
        active_processors = getattr(app.state, "active_processors", {})
        for processor_id in list(active_processors.keys()):
            stop_processor_logic(processor_id, app)
        logger.info("All processors cleaned up successfully.")
    return shutdown

# ===================================================================
# --- Endpoints (مسیرهای API) ---
# ===================================================================

@router.post("/start/camera/{camera_id}", response_model=StatusResponse, tags=["Camera Management"])
async def start_camera(camera_id: str, request: Request):
    if camera_id not in settings.CAMERAS:
        raise HTTPException(status_code=404, detail=f"Camera ID '{camera_id}' not found in configuration.")
    if camera_id in request.app.state.active_processors:
        raise HTTPException(status_code=409, detail=f"Processor for camera '{camera_id}' is already running.")
    start_camera_processor_logic(camera_id, request.app)
    return {"status": "camera processing started", "processor_id": camera_id}

@router.post("/stop/camera/{camera_id}", response_model=StatusResponse, tags=["Camera Management"])
async def stop_camera(camera_id: str, request: Request):
    if camera_id not in request.app.state.active_processors or request.app.state.active_processors[camera_id].get("type") != "camera":
        raise HTTPException(status_code=404, detail=f"Camera processor '{camera_id}' not found.")
    stop_processor_logic(camera_id, request.app)
    return {"status": "camera processing stopped", "processor_id": camera_id}

@router.post("/start/video", response_model=StatusResponse, tags=["Video Management"])
async def start_video(request: Request, file: UploadFile = File(...)):
    if not file.filename.endswith(('.mp4', '.avi', '.mov')):
        raise HTTPException(status_code=400, detail="Only .mp4, .avi, or .mov files are allowed.")
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_file:
            temp_path = temp_file.name
            temp_file.write(await file.read())

        processor_id = f"video_{int(time.time())}"
        stop_event = Event()

        # Check processing mode
        if settings.PROCESSING_MODE == "demand_driven":
            # Use unified processor for video
            processor = UnifiedProcessor(processor_id, 'video', temp_path)
            processor_thread = Thread(
                target=processor.start_processing,
                args=(stop_event,),
                name=f"UnifiedVideoProcessor-{processor_id}"
            )

            processor_thread.start()

            request.app.state.active_processors[processor_id] = {
                "processor": processor,
                "processor_thread": processor_thread,
                "stop_event": stop_event,
                "temp_file": temp_path,
                "type": "video",
                "mode": "unified"
            }

            enhanced_logger.log_production_started(processor_id)

        else:
            # Use traditional producer-consumer for video
            producer = Thread(target=video_producer, args=(temp_path, processor_id, stop_event), name=f"Producer-{processor_id}")
            consumer = Thread(target=frame_consumer, args=(processor_id, temp_path, 'video', stop_event), name=f"Consumer-{processor_id}")

            producer.start()
            consumer.start()

            request.app.state.active_processors[processor_id] = {
                "producer_thread": producer,
                "consumer_thread": consumer,
                "stop_event": stop_event,
                "temp_file": temp_path,
                "type": "video",
                "mode": "traditional"
            }

        return {"status": "video processing started", "processor_id": processor_id}
    except Exception as e:
        logger.error(f"Error starting video processing: {e}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.unlink(temp_path)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stop/video/{processor_id}", response_model=StatusResponse, tags=["Video Management"])
async def stop_video(processor_id: str, request: Request):
    active_processors = request.app.state.active_processors
    if processor_id not in active_processors or active_processors[processor_id].get("type") != "video":
        raise HTTPException(status_code=404, detail=f"Video processor '{processor_id}' not found.")
    stop_processor_logic(processor_id, request.app)
    return {"status": "video processing stopped", "processor_id": processor_id}

@router.get("/health", response_model=HealthResponse, tags=["System Management"])
async def get_system_health(request: Request):
    """Get comprehensive system health status"""
    try:
        active_processors = getattr(request.app.state, "active_processors", {})

        # Build processor status
        processor_status = {}
        for proc_id, proc_info in active_processors.items():
            if proc_info.get("mode") == "unified":
                processor = proc_info.get("processor")
                if processor:
                    processor_status[proc_id] = {
                        "type": proc_info.get("type"),
                        "mode": proc_info.get("mode"),
                        "running": processor.running,
                        "production_status": enhanced_logger.get_production_status(proc_id),
                        "camera_status": enhanced_logger.get_camera_status(proc_id),
                        "ingot_count": enhanced_logger.get_last_ingot_count(proc_id),
                        "avg_processing_time": enhanced_logger.get_avg_processing_time(proc_id)
                    }
            else:
                processor_status[proc_id] = {
                    "type": proc_info.get("type"),
                    "mode": proc_info.get("mode", "traditional"),
                    "running": True,
                    "thread_alive": proc_info.get("processor_thread", proc_info.get("producer_thread")).is_alive()
                }

        # System information
        system_info = {
            "processing_mode": settings.PROCESSING_MODE,
            "frame_rate": settings.FRAME_RATE,
            "quality_threshold": settings.QUALITY_THRESHOLD,
            "production_idle_threshold": settings.PRODUCTION_IDLE_THRESHOLD,
            "health_check_interval": settings.HEALTH_CHECK_INTERVAL,
            "ai_confidence_threshold": settings.AI_CONFIDENCE_THRESHOLD
        }

        return {
            "status": "healthy" if processor_status else "no_active_processors",
            "processing_mode": settings.PROCESSING_MODE,
            "active_processors": processor_status,
            "system_info": system_info
        }

    except Exception as e:
        logger.error(f"Error getting system health: {e}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")

@router.get("/processors", tags=["System Management"])
async def list_processors(request: Request):
    """List all active processors with their status"""
    active_processors = getattr(request.app.state, "active_processors", {})

    processor_list = []
    for proc_id, proc_info in active_processors.items():
        processor_entry = {
            "processor_id": proc_id,
            "type": proc_info.get("type"),
            "mode": proc_info.get("mode", "traditional"),
            "status": "running"
        }

        if proc_info.get("mode") == "unified":
            processor = proc_info.get("processor")
            if processor:
                processor_entry.update({
                    "production_status": enhanced_logger.get_production_status(proc_id),
                    "camera_status": enhanced_logger.get_camera_status(proc_id),
                    "ingot_count": enhanced_logger.get_last_ingot_count(proc_id)
                })

        processor_list.append(processor_entry)

    return {"processors": processor_list, "total": len(processor_list)}