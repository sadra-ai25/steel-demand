import subprocess
import ffmpeg
import pickle
import logging
import numpy as np
import cv2
import time
from rabbitmq.client import RedisClient
from config.config import settings
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

def evaluate_frame_quality(frame):
    """ارزیابی کیفیت فریم بر اساس میانگین روشنایی"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_brightness = np.mean(gray)
    return mean_brightness

def camera_producer(camera_id, stop_event=None):
    camera_info = settings.CAMERAS.get(camera_id)
    if not camera_info:
        logger.error(f"❌ Camera {camera_id} not found in configuration")
        return
    rtsp_url = camera_info["rtsp"]
    logger.info(f"▶️ Starting camera producer for {camera_id} with URL: {rtsp_url}")
    frame_width = 3840
    frame_height = 2160
    frame_size = frame_width * frame_height * 3
    interval = 1.0 / settings.FRAME_RATE
    frame_number = 1
    redis_client = None
    try:
        redis_client = RedisClient(settings.REDIS_HOST, settings.REDIS_PORT, settings.REDIS_DB)
        while stop_event is None or not stop_event.is_set():
            process = None
            try:
                logger.info(f"▶️ Attempting to start ffmpeg process for {camera_id}...")
                process = (
                    ffmpeg
                    .input(rtsp_url, rtsp_transport='tcp', skip_frame='nokey')
                    .filter('fps', fps=settings.FRAME_RATE)
                    .output('pipe:', format='rawvideo', pix_fmt='bgr24', vcodec='rawvideo', vsync='0')
                    .run_async(pipe_stdout=True, pipe_stderr=True) # pipe_stderr برای لاگ خطاهای ffmpeg
                )

                redis_client = RedisClient(
                    settings.REDIS_HOST, settings.REDIS_PORT, settings.REDIS_DB
                )
                buffer = bytearray()
                while process.poll() is None and (stop_event is None or not stop_event.is_set()):
                    data = process.stdout.read(frame_size)
                    if not data:
                        break
                    buffer.extend(data)
                    while len(buffer) >= frame_size:
                        raw_frame = buffer[:frame_size]
                        buffer = buffer[frame_size:]
                        frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((frame_height, frame_width, 3))
                        quality = evaluate_frame_quality(frame)
                        if quality < settings.QUALITY_THRESHOLD:
                            logger.debug(f"Frame {frame_number} discarded due to low quality: {quality}")
                            continue
                        _, buffer_img = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        compressed_frame = buffer_img.tobytes()
                        timestamp = time.time()
                        timeframe = datetime.fromtimestamp(timestamp, tz=ZoneInfo("Asia/Tehran"))
                        frame_data = {'frame': compressed_frame, 'timestamp': timestamp}
                        logger.info(f"Sending frame to queue: frame_queue_{camera_id}")
                        redis_client.publish(f"frame_queue_{camera_id}", pickle.dumps(frame_data))
                        publishtime = datetime.fromtimestamp(time.time(), tz=ZoneInfo("Asia/Tehran"))
                        time_diff = (publishtime - timeframe).total_seconds()
                        logger.info(f"📷 {camera_id} - Frame {frame_number} captured at {timeframe} | Published at {publishtime} | Delay: {time_diff:.3f}s | Quality: {quality:.2f}")
                        frame_number += 1
                        sleep = interval - time_diff
                        if sleep > 0:
                            time.sleep(sleep)
                process.terminate()
                redis_client.close()
                logger.warning(f"ffmpeg process for {camera_id} exited. Waiting to restart...")
            except Exception as e:
                logger.error(f"❌ Unhandled exception in producer loop for {camera_id}: {e}")
            
            finally:
                if process:
                    process.kill() # اطمینان از بسته شدن کامل پروسه
                # قبل از تلاش مجدد، کمی صبر کن
                if not (stop_event and stop_event.is_set()):
                    logger.info(f"Waiting 10 seconds before restarting producer for {camera_id}...")
                    time.sleep(10)
    
    except Exception as e:
        logger.critical(f"Producer for {camera_id} is shutting down due to a critical error: {e}")
    finally:
        if redis_client:
            redis_client.close()
        logger.info(f"⏹️ Camera producer for {camera_id} has completely stopped.")

def video_producer(video_path, processor_id, stop_event=None):
    logger.info(f"Starting producer for {processor_id} with video: {video_path}")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"❌ Failed to open video: {video_path}")
        return
    
    redis_client = RedisClient(
        settings.REDIS_HOST, settings.REDIS_PORT, settings.REDIS_DB
    )
    frame_count = 0
    try:
        while cap.isOpened() and (stop_event is None or not stop_event.is_set()):
            ret, frame = cap.read()
            if not ret:
                logger.info(f"Reached end of video: {video_path}")
                break
            quality = evaluate_frame_quality(frame)
            if quality < settings.QUALITY_THRESHOLD:
                logger.debug(f"Frame {frame_count} discarded due to low quality: {quality}")
                continue
            
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            compressed_frame = buffer.tobytes()
            timestamp = time.time()
            frame_data = {'frame': compressed_frame, 'timestamp': timestamp}
            
            redis_client.publish(f"frame_queue_{processor_id}", pickle.dumps(frame_data))
            frame_count += 1
            logger.info(f"🎥 Video {processor_id} - Frame {frame_count} sent to Redis | Quality: {quality:.2f}")
            time.sleep(1.0 / settings.FRAME_RATE)  # تنظیم نرخ فریم

    except Exception as e:
        logger.error(f"❌ Error in video producer for {processor_id}: {e}")
    finally:
        cap.release()
        # **FIX:** Send an end-of-stream marker instead of setting the stop_event
        if stop_event is None or not stop_event.is_set():
            try:
                logger.info(f"🎥 Video {processor_id} - Publishing end-of-stream marker.")
                redis_client.publish(f"frame_queue_{processor_id}", pickle.dumps("END_OF_STREAM"))
            except Exception as e:
                logger.error(f"❌ Error publishing end-of-stream marker for {processor_id}: {e}")

        redis_client.close()
        logger.info(f"⏹️ Video producer {processor_id} has finished and closed its connections.")