from fastapi import FastAPI, UploadFile, File, HTTPException
from threading import Thread, Event
import tempfile
import time
import os
import logging
from pydantic import BaseModel
from capture.producer import video_producer
from processing.frame_consumer import frame_consumer
from config.config import settings

# تنظیم لاگ‌گیری
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# دیکشنری برای ذخیره نخ‌ها و اطلاعات پردازش
active_processors = {}

class StopResponse(BaseModel):
    status: str
    processor_id: str

@app.post("/start/video")
async def start_video(file: UploadFile = File(...)):
    """
    آپلود و شروع پردازش یک فایل ویدیویی.
    """
    # بررسی پسوند فایل
    if not file.filename.endswith(('.mp4', '.avi', '.mov')):
        logger.error(f"Invalid file format: {file.filename}")
        raise HTTPException(status_code=400, detail="Only .mp4, .avi, or .mov files are allowed")

    try:
        # ذخیره فایل موقت
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_file:
            temp_file.write(await file.read())
            temp_path = temp_file.name

        # بررسی وجود فایل
        if not os.path.exists(temp_path):
            logger.error(f"Temporary file {temp_path} could not be created")
            raise HTTPException(status_code=500, detail="Failed to create temporary file")

        # تولید processor_id منحصربه‌فرد
        processor_id = f"video_{int(time.time())}"
        logger.info(f"Starting video processing for {processor_id} with file: {temp_path}")

        # ایجاد رویداد توقف
        stop_event = Event()

        # ایجاد نخ‌های producer و consumer
        producer_thread = Thread(
            target=video_producer,
            args=(temp_path, processor_id, stop_event),
            name=f"Producer-{processor_id}"
        )
        consumer_thread = Thread(
            target=frame_consumer,
            args=(processor_id, temp_path, 'video', stop_event),
            name=f"Consumer-{processor_id}"
        )

        # شروع نخ‌ها
        producer_thread.start()
        consumer_thread.start()

        # ذخیره اطلاعات پردازش
        active_processors[processor_id] = {
            "producer_thread": producer_thread,
            "consumer_thread": consumer_thread,
            "stop_event": stop_event,
            "temp_file": temp_path
        }

        return {"status": "video processing started", "processor_id": processor_id}

    except Exception as e:
        logger.error(f"Error starting video processing: {e}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.unlink(temp_path)  # حذف فایل موقت در صورت خطا
        raise HTTPException(status_code=500, detail=f"Failed to start video processing: {str(e)}")

@app.post("/stop/video/{processor_id}", response_model=StopResponse)
async def stop_video(processor_id: str):
    """
    توقف پردازش ویدیوی مشخص‌شده و پاکسازی منابع.
    """
    if processor_id not in active_processors:
        logger.error(f"Processor {processor_id} not found")
        raise HTTPException(status_code=404, detail=f"Processor {processor_id} not found")

    try:
        processor = active_processors[processor_id]
        stop_event = processor["stop_event"]
        temp_file = processor["temp_file"]

        # تنظیم رویداد توقف
        stop_event.set()
        logger.info(f"Stop event set for {processor_id}")

        # انتظار برای اتمام نخ‌ها
        producer_thread = processor["producer_thread"]
        consumer_thread = processor["consumer_thread"]
        producer_thread.join(timeout=5.0)
        consumer_thread.join(timeout=5.0)

        # حذف فایل موقت
        if os.path.exists(temp_file):
            os.unlink(temp_file)
            logger.info(f"Temporary file {temp_file} deleted")

        # حذف از active_processors
        del active_processors[processor_id]
        logger.info(f"Processor {processor_id} stopped and resources cleaned up")

        return {"status": "video processing stopped", "processor_id": processor_id}

    except Exception as e:
        logger.error(f"Error stopping processor {processor_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop processor: {str(e)}")

@app.on_event("shutdown")
async def cleanup():
    """
    پاکسازی منابع هنگام خاموش شدن برنامه.
    """
    for processor_id, processor in list(active_processors.items()):
        logger.info(f"Cleaning up processor {processor_id}")
        processor["stop_event"].set()
        processor["producer_thread"].join(timeout=5.0)
        processor["consumer_thread"].join(timeout=5.0)
        if os.path.exists(processor["temp_file"]):
            os.unlink(processor["temp_file"])
            logger.info(f"Temporary file {processor['temp_file']} deleted")
    active_processors.clear()
    logger.info("All processors cleaned up")