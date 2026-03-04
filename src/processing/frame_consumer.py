import logging
import pickle
import time
import cv2
import numpy as np
import datetime
from datetime import datetime
from zoneinfo import ZoneInfo
import os
from rabbitmq.client import RedisClient
from ai.barcode import process_frame_for_barcode
from ai.counter import IngotCounter
from db.database import DatabaseLogger
from config.config import settings

last_saved_barcodes = {}
logger = logging.getLogger(__name__)
logging.getLogger().setLevel(logging.INFO)

def save_image_to_folder(cropped_image, barcode):
    """ذخیره تصویر برش‌خورده با بارکد در پوشه مشخص‌شده"""
    os.makedirs(settings.CROPPED_IMAGES_PATH, exist_ok=True)
    cv2.putText(cropped_image, barcode, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
    image_filename = os.path.join(settings.CROPPED_IMAGES_PATH, f"{barcode}.jpg")
    if cv2.imwrite(image_filename, cropped_image):
        logger.info(f"Saved cropped image with barcode {barcode} to {image_filename}")
    else:
        logger.error(f"Failed to save cropped image with barcode {barcode} to {image_filename}")

def frame_consumer(source_id, source_path=None, source_type='camera', stop_event=None):
    """پردازش فریم‌ها برای شمارش شمش و خوانش بارکد"""
    if source_type == 'video':
        source_info = settings.VIDEOS.get(source_id)
    else:
        source_info = settings.CAMERAS.get(source_id)
        
    if not source_info:
        logger.warning(f"Source {source_id} not found in configuration, using default settings")
        bbox = settings.DEFAULT_BBOX
        counting_line_x = settings.DEFAULT_COUNTING_LINE_X
    else:
        bbox = source_info.get('bbox', settings.DEFAULT_BBOX)
        counting_line_x = source_info.get('counting_line_x', settings.DEFAULT_COUNTING_LINE_X)

    redis_client = None
    db_logger = None
    counter = None
    try:
        redis_client = RedisClient(settings.REDIS_HOST, settings.REDIS_PORT, settings.REDIS_DB)
        counter = IngotCounter(
            model_path='src/ai/weights/best.pt',
            counting_line_x=counting_line_x,
            match_threshold=5
        )
        db_logger = DatabaseLogger()
        output_dir = os.path.join(settings.FRAMES_PATH, source_id)
        os.makedirs(output_dir, exist_ok=True)
        frame_count = 0
        ingot_count = 0
        target_time = 1.0 / settings.FRAME_RATE
        
        while stop_event is None or not stop_event.is_set():
            t_start = time.time()
            msg = redis_client.brpop(f"frame_queue_{source_id}", timeout=5)
            
            if msg is None:
                logger.info(f"{source_id} - No frames available in queue, waiting...")
                continue

            # **FIX:** Check for the end-of-stream marker
            try:
                data = pickle.loads(msg)
                if isinstance(data, str) and data == "END_OF_STREAM":
                    logger.info(f"{source_id} - Received end-of-stream marker. Consumer will now shut down.")
                    break # Exit the main while loop
            except Exception as e:
                logger.error(f"Failed to unpickle message for {source_id}: {e}")
                continue

            logger.info(f"{source_id} - Received frame from queue")
            try:
                compressed_frame = data['frame']
                timestamp = data['timestamp']
                if not isinstance(compressed_frame, bytes):
                    logger.error(f"Invalid frame data type: {type(compressed_frame)}, expected bytes")
                    continue
                frame = cv2.imdecode(np.frombuffer(compressed_frame, np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    logger.warning(f"{source_id} - Corrupted frame detected, Skipping...")
                    continue
            except (KeyError, TypeError) as e:
                logger.error(f"Failed to process frame data for {source_id}: {e}")
                continue

            # پردازش بارکد
            try:
                barcode, cropped = process_frame_for_barcode(frame, bbox)
                if barcode and last_saved_barcodes.get(source_id) != barcode:
                    frame_datetime = datetime.fromtimestamp(timestamp, tz=ZoneInfo("Asia/Tehran"))
                    logger.info(f"🟢 Detected new barcode: {barcode} from {source_type} in {source_id}")
                    save_image_to_folder(cropped, barcode)
                    db_logger.log_barcode(source_id, barcode, frame_datetime, compressed_frame, "")
                    last_saved_barcodes[source_id] = barcode
            except Exception as e:
                logger.error(f"Error processing barcode for {source_id}: {e}")

            # پردازش شمش
            try:
                count, sizes, widths, results = counter.process_frame(frame)
                ingot_count += count
                for box in (results[0].boxes if results and results[0].boxes else []):
                    x, y, w, h = box.xywh[0].tolist()
                    x1, y1 = int(x - w / 2), int(y - h / 2)
                    x2, y2 = int(x + w / 2), int(y + h / 2)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
                cv2.line(frame, (counting_line_x, 0), (counting_line_x, frame.shape[0]), (0, 255, 0), 2)
                cv2.putText(frame, f"ingot_count: {ingot_count}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 3)
            except Exception as e:
                logger.error(f"Error processing ingot count for {source_id}: {e}")
                continue

            # ذخیره فریم
            frame_count += 1
            if count > 0:
                frame_path = os.path.join(output_dir, f"frame_{frame_count:04d}.jpg")
                if cv2.imwrite(frame_path, frame):
                    logger.info(f"🟢 {source_id} saved frame {frame_count} at {frame_path}")
                else:
                    logger.error(f"❌ Failed to save frame {frame_count} at {frame_path}")
                
                frame_datetime = datetime.fromtimestamp(timestamp, tz=ZoneInfo("Asia/Tehran"))
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                frame_data = buffer.tobytes()
                try:
                    size = sizes[0] if sizes and isinstance(sizes, list) and len(sizes) > 0 else 0
                    width = widths[0] if widths and isinstance(widths, list) and len(widths) > 0 else 0
                    db_logger.log_ingot(source_id, size, width, frame_datetime, frame_data, "")
                except Exception as e:
                    logger.error(f"Error logging ingot to database for {source_id}: {e}")

                elapsed = time.time() - t_start
                if elapsed < target_time:
                    time.sleep(target_time - elapsed)
            else:
                logger.info(f"🔴 the steel line production is currently stopped -----> ingot_count={ingot_count}")
                
    except Exception as e:
        logger.error(f"Consumer {source_id} interrupted, shutting down with error: {e}")
    finally:
        try:
            if db_logger:
                db_logger.close()
            if redis_client:
                redis_client.close()
        except Exception as e:
            logger.error(f"Error during cleanup for {source_type} {source_id}: {e}")