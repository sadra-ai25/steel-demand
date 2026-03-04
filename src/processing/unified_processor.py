import logging
import time
import cv2
import numpy as np
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, Tuple
import threading

from capture.frame_extractor import FrameExtractor, VideoFrameExtractor
from ai.barcode import process_frame_for_barcode
from ai.counter import IngotCounter
from db.database import DatabaseLogger
from rabbitmq.client import RedisClient
from config.config import settings
from utils.enhanced_logger import EnhancedLogger

class UnifiedProcessor:
    """
    Unified processor that implements demand-driven frame processing
    Extracts frames only when AI is ready to process them
    """

    def __init__(self, source_id: str, source_type: str = 'camera', source_path: Optional[str] = None):
        self.source_id = source_id
        self.source_type = source_type
        self.source_path = source_path
        self.running = False

        # Initialize logger
        self.logger = EnhancedLogger(f"UnifiedProcessor-{source_id}")

        # Get source configuration
        if source_type == 'video':
            source_info = settings.VIDEOS.get(source_id, {})
        else:
            source_info = settings.CAMERAS.get(source_id, {})

        self.bbox = source_info.get('bbox', settings.DEFAULT_BBOX)
        self.counting_line_x = source_info.get('counting_line_x', settings.DEFAULT_COUNTING_LINE_X)

        # Initialize components
        self.redis_client = None
        self.db_logger = None
        self.counter = None
        self.frame_extractor = None
        self.video_extractor = None

        # Processing state
        self.frame_count = 0
        self.ingot_count = 0
        self.last_saved_barcodes = {}
        self.production_state = "UNKNOWN"
        self.last_ingot_time = None
        self.idle_start_time = None

        # Performance tracking
        self.processing_times = []
        self.frame_rates = []
        self.last_health_check = time.time()

        # Configuration
        self.target_time = 1.0 / settings.FRAME_RATE
        self.quality_threshold = settings.QUALITY_THRESHOLD
        self.production_idle_threshold = 30.0  # seconds without ingot = idle
        self.health_check_interval = 60.0  # seconds

    def initialize_components(self) -> bool:
        """Initialize all components required for processing"""
        try:
            # Redis client
            self.redis_client = RedisClient(
                settings.REDIS_HOST,
                settings.REDIS_PORT,
                settings.REDIS_DB
            )

            # AI components
            self.counter = IngotCounter(
                model_path='src/ai/weights/best.pt',
                counting_line_x=self.counting_line_x,
                match_threshold=5
            )

            # Database logger
            self.db_logger = DatabaseLogger()

            # Frame extractors
            if self.source_type == 'camera':
                self.frame_extractor = FrameExtractor(self.redis_client)
            else:
                self.video_extractor = VideoFrameExtractor()

            # Create output directory
            output_dir = os.path.join(settings.FRAMES_PATH, self.source_id)
            os.makedirs(output_dir, exist_ok=True)

            # Log AI model loading
            model_load_start = time.time()
            model_load_time = time.time() - model_load_start
            self.logger.log_ai_model_loaded(self.source_id, 'src/ai/weights/best.pt', model_load_time)

            return True

        except Exception as e:
            self.logger.log_process_crashed(self.source_id, "Component initialization", str(e))
            return False

    def test_connection(self) -> bool:
        """Test connection to source"""
        if self.source_type == 'camera':
            camera_info = settings.CAMERAS.get(self.source_id)
            if not camera_info:
                return False
            return self.frame_extractor.test_camera_connection(camera_info["rtsp"], self.source_id)
        else:
            # For video, just check if file exists
            if self.source_path and os.path.exists(self.source_path):
                self.logger.log_camera_connected(self.source_id, self.source_path, "video")
                return True
            return False

    def extract_frame(self) -> Optional[Tuple[np.ndarray, Dict[str, Any]]]:
        """Extract frame based on source type (demand-driven)"""
        if self.source_type == 'camera':
            camera_info = settings.CAMERAS.get(self.source_id)
            if not camera_info:
                return None

            return self.frame_extractor.extract_frame_from_camera(
                camera_info["rtsp"],
                self.source_id,
                self.quality_threshold
            )
        else:
            return self.video_extractor.extract_frame_from_video(
                self.source_path,
                self.source_id
            )

    def process_barcode(self, frame: np.ndarray, timestamp: float) -> Optional[str]:
        """Process frame for barcode detection"""
        try:
            barcode_start = time.time()
            barcode, cropped = process_frame_for_barcode(frame, self.bbox)
            barcode_time = time.time() - barcode_start

            if barcode:
                # Check for duplicate
                if self.last_saved_barcodes.get(self.source_id) == barcode:
                    last_seen = datetime.fromtimestamp(
                        self.last_saved_barcodes.get(f"{self.source_id}_time", 0),
                        tz=ZoneInfo("Asia/Tehran")
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    self.logger.log_barcode_duplicate_filtered(self.source_id, barcode, last_seen)
                    return None

                # New barcode detected
                frame_datetime = datetime.fromtimestamp(timestamp, tz=ZoneInfo("Asia/Tehran"))

                self.logger.log_barcode_detected(
                    self.source_id,
                    barcode,
                    0.9,  # confidence (could be enhanced)
                    {"x": self.bbox["x_min"], "y": self.bbox["y_min"],
                     "width": self.bbox["x_max"] - self.bbox["x_min"],
                     "height": self.bbox["y_max"] - self.bbox["y_min"]},
                    barcode_time
                )

                # Save cropped image
                self.save_image_to_folder(cropped, barcode)

                # Log to database
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                frame_data = buffer.tobytes()
                self.db_logger.log_barcode(self.source_id, barcode, frame_datetime, frame_data, "")

                # Update last seen
                self.last_saved_barcodes[self.source_id] = barcode
                self.last_saved_barcodes[f"{self.source_id}_time"] = timestamp

                self.logger.log_barcode_read_success(self.source_id, barcode, 1)
                return barcode

        except Exception as e:
            self.logger.log_barcode_read_failed(self.source_id, str(e), 1)

        return None

    def process_ingots(self, frame: np.ndarray, timestamp: float) -> Tuple[int, Optional[float], Optional[float]]:
        """Process frame for ingot counting"""
        try:
            inference_start = time.time()
            count, sizes, widths, results = self.counter.process_frame(frame)
            inference_time = time.time() - inference_start

            # Log AI inference
            objects_detected = len(results[0].boxes) if results and results[0].boxes else 0
            avg_confidence = 0.0
            if results and results[0].boxes:
                confidences = [box.conf.item() for box in results[0].boxes]
                avg_confidence = np.mean(confidences) if confidences else 0.0

            self.logger.log_ai_inference_completed(
                self.source_id,
                inference_time,
                objects_detected,
                avg_confidence
            )

            # Check for low confidence
            if avg_confidence < 0.7 and objects_detected > 0:
                self.logger.log_ai_confidence_low(
                    self.source_id,
                    avg_confidence,
                    0.7,
                    "ingot"
                )

            # Update ingot count
            if count > 0:
                previous_count = self.ingot_count
                self.ingot_count += count
                self.last_ingot_time = timestamp

                self.logger.log_ingot_detected(
                    self.source_id,
                    count,
                    sizes[0] if sizes else 0.0,
                    widths[0] if widths else 0.0,
                    avg_confidence,
                    {"x": self.counting_line_x, "y": 0}
                )

                self.logger.log_ingot_count_updated(
                    self.source_id,
                    previous_count,
                    self.ingot_count,
                    count
                )

                self.logger.log_counting_line_crossed(
                    self.source_id,
                    self.counting_line_x,
                    f"ingot_{self.frame_count}",
                    "forward"
                )

                # Update production state
                if self.production_state != "RUNNING":
                    self.production_state = "RUNNING"
                    self.logger.log_production_started(self.source_id)

                self.idle_start_time = None

            # Draw detection results on frame
            if results and results[0].boxes:
                for box in results[0].boxes:
                    x, y, w, h = box.xywh[0].tolist()
                    x1, y1 = int(x - w / 2), int(y - h / 2)
                    x2, y2 = int(x + w / 2), int(y + h / 2)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)

            # Draw counting line
            cv2.line(frame, (self.counting_line_x, 0),
                    (self.counting_line_x, frame.shape[0]), (0, 255, 0), 2)

            # Draw ingot count
            cv2.putText(frame, f"ingot_count: {self.ingot_count}",
                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 3)

            return count, sizes[0] if sizes else None, widths[0] if widths else None

        except Exception as e:
            self.logger.log_ai_inference_completed(self.source_id, 0, 0, 0)
            raise e

    def save_image_to_folder(self, cropped_image: np.ndarray, barcode: str):
        """Save cropped image with barcode"""
        try:
            os.makedirs(settings.CROPPED_IMAGES_PATH, exist_ok=True)
            cv2.putText(cropped_image, barcode, (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
            image_filename = os.path.join(settings.CROPPED_IMAGES_PATH, f"{barcode}.jpg")

            if cv2.imwrite(image_filename, cropped_image):
                self.logger.log_frame_processed(self.source_id, 0, 0, barcode)
            else:
                self.logger.log_frame_dropped(self.source_id, f"Failed to save barcode image: {barcode}")

        except Exception as e:
            self.logger.log_frame_dropped(self.source_id, f"Error saving barcode image: {str(e)}")

    def save_frame(self, frame: np.ndarray, timestamp: float,
                  ingot_count: int, size: Optional[float], width: Optional[float]):
        """Save frame to disk and database"""
        try:
            output_dir = os.path.join(settings.FRAMES_PATH, self.source_id)
            frame_path = os.path.join(output_dir, f"frame_{self.frame_count:04d}.jpg")

            if cv2.imwrite(frame_path, frame):
                self.logger.log_frame_processed(self.source_id, 0, ingot_count)
            else:
                self.logger.log_frame_dropped(self.source_id, f"Failed to save frame {self.frame_count}")
                return

            # Log to database
            frame_datetime = datetime.fromtimestamp(timestamp, tz=ZoneInfo("Asia/Tehran"))
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            frame_data = buffer.tobytes()

            self.db_logger.log_ingot(
                self.source_id,
                size or 0,
                width or 0,
                frame_datetime,
                frame_data,
                ""
            )

        except Exception as e:
            self.logger.log_frame_dropped(self.source_id, f"Error saving frame: {str(e)}")

    def check_production_status(self, current_time: float):
        """Check and update production status based on ingot activity"""
        if self.last_ingot_time is None:
            return

        time_since_last_ingot = current_time - self.last_ingot_time

        if time_since_last_ingot > self.production_idle_threshold:
            if self.production_state == "RUNNING":
                self.production_state = "IDLE"
                self.idle_start_time = current_time
                self.logger.log_production_idle_detected(
                    self.source_id,
                    time_since_last_ingot / 60.0
                )
        elif self.production_state == "IDLE" and time_since_last_ingot <= 5.0:
            # Production resumed
            idle_duration = (current_time - self.idle_start_time) / 60.0 if self.idle_start_time else 0
            self.production_state = "RUNNING"
            self.logger.log_production_started(self.source_id)

    def perform_health_check(self, processing_time: float):
        """Perform system health check"""
        current_time = time.time()

        if current_time - self.last_health_check >= self.health_check_interval:
            try:
                # Calculate performance metrics
                avg_processing_time = np.mean(self.processing_times[-10:]) if self.processing_times else 0
                current_fps = 1.0 / processing_time if processing_time > 0 else 0

                # Get Redis queue size
                queue_size = 0  # Not applicable in demand-driven mode

                # Log system health
                self.logger.log_system_health_check(
                    self.source_id,
                    0.0,  # CPU usage (could be enhanced)
                    0.0,  # Memory usage (could be enhanced)
                    queue_size
                )

                # Log processing latency
                self.logger.log_processing_latency(
                    self.source_id,
                    processing_time,
                    self.target_time
                )

                self.last_health_check = current_time

            except Exception as e:
                self.logger.log_process_crashed(self.source_id, "Health check", str(e))

    def process_continuous(self, stop_event: Optional[threading.Event] = None):
        """
        Main processing loop - demand-driven frame processing
        Equivalent to the face recognition continuous processing
        """
        self.logger.log_production_started(self.source_id)

        try:
            while self.running and (stop_event is None or not stop_event.is_set()):
                loop_start = time.time()

                try:
                    # Step 1: Extract frame when ready for processing (demand-driven)
                    result = self.extract_frame()

                    if result is None:
                        # No frame available or extraction failed
                        time.sleep(0.1)  # Brief pause before retry
                        continue

                    frame, metadata = result
                    frame_timestamp = metadata['timestamp']

                    # Step 2: Process frame through AI pipeline
                    processing_start = time.time()

                    # Process barcode
                    barcode = self.process_barcode(frame, frame_timestamp)

                    # Process ingots
                    ingot_count, size, width = self.process_ingots(frame, frame_timestamp)

                    processing_time = time.time() - processing_start

                    # Step 3: Save results if ingots detected
                    self.frame_count += 1

                    if ingot_count > 0:
                        self.save_frame(frame, frame_timestamp, ingot_count, size, width)
                    else:
                        # Log production idle if no ingots for extended period
                        current_time = time.time()
                        self.check_production_status(current_time)

                    # Update performance metrics
                    self.processing_times.append(processing_time)
                    if len(self.processing_times) > 100:  # Keep last 100 measurements
                        self.processing_times = self.processing_times[-100:]

                    # Perform health check
                    self.perform_health_check(processing_time)

                    # Step 4: Wait for next processing cycle (maintain target FPS)
                    elapsed = time.time() - loop_start
                    if elapsed < self.target_time:
                        time.sleep(self.target_time - elapsed)

                except Exception as e:
                    self.logger.log_process_crashed(self.source_id, "Processing loop", str(e))
                    time.sleep(1)  # Pause before retry

        except Exception as e:
            self.logger.log_process_crashed(self.source_id, "Main processing", str(e))
        finally:
            self.cleanup()

    def start_processing(self, stop_event: Optional[threading.Event] = None):
        """Start the unified processing"""
        if not self.initialize_components():
            return False

        if not self.test_connection():
            return False

        self.running = True
        self.process_continuous(stop_event)
        return True

    def stop_processing(self):
        """Stop processing"""
        self.running = False

        # Log production stop
        if self.production_state == "RUNNING":
            self.logger.log_production_stopped(
                self.source_id,
                "Manual stop requested",
                0.0
            )

    def cleanup(self):
        """Clean up resources"""
        try:
            if self.db_logger:
                self.db_logger.close()
            if self.redis_client:
                self.redis_client.close()
            if self.video_extractor:
                self.video_extractor.cleanup_all()

            self.logger.log_process_restarted(self.source_id, "Cleanup completed", 0)

        except Exception as e:
            self.logger.log_process_crashed(self.source_id, "Cleanup", str(e))