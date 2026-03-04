import subprocess
import base64
import cv2
import numpy as np
import time
import logging
from PIL import Image
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, Tuple, Dict, Any
from utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)

class FrameExtractor:
    """Demand-driven frame extractor using FFmpeg - extracts frames only when needed"""

    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.extraction_stats = {}
        self.connection_status = {}

    def evaluate_frame_quality(self, frame: np.ndarray) -> float:
        """Evaluate frame quality based on brightness and sharpness"""
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Brightness evaluation
            mean_brightness = np.mean(gray)

            # Sharpness evaluation using Laplacian variance
            laplacian_variance = cv2.Laplacian(gray, cv2.CV_64F).var()

            # Combined quality score (weighted average)
            quality_score = (mean_brightness * 0.7) + (min(laplacian_variance / 100, 100) * 0.3)

            return quality_score

        except Exception as e:
            logger.log_frame_quality_check("system", 0.0, 0.0, False)
            return 0.0

    def extract_frame_from_camera(self, camera_url: str, camera_id: str,
                                 quality_threshold: float = 50.0) -> Optional[Tuple[np.ndarray, Dict[str, Any]]]:
        """
        Extract single frame from camera using FFmpeg (demand-driven)
        Returns frame and metadata if successful, None otherwise
        """
        start_time = time.time()

        # FFmpeg command for single frame extraction
        cmd = [
            'ffmpeg',
            '-rtsp_transport', 'tcp',           # Use TCP for RTSP
            '-i', camera_url,                   # Input camera stream
            '-vframes', '1',                    # Extract only 1 frame
            '-f', 'image2pipe',                 # Output as pipe
            '-vcodec', 'mjpeg',                 # JPEG codec
            '-q:v', '2',                        # High quality
            '-'                                 # Output to stdout
        ]

        try:
            # Run FFmpeg and capture frame
            result = subprocess.run(cmd, capture_output=True, timeout=10)

            if result.returncode == 0:
                extraction_time = time.time() - start_time

                # Convert frame bytes to OpenCV format
                frame_bytes = result.stdout
                nparr = np.frombuffer(frame_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                if frame is None:
                    logger.log_frame_dropped(camera_id, "Failed to decode frame data")
                    return None

                # Evaluate frame quality
                quality = self.evaluate_frame_quality(frame)
                quality_passed = quality >= quality_threshold

                logger.log_frame_quality_check(camera_id, quality, quality_threshold, quality_passed)

                if not quality_passed:
                    logger.log_frame_dropped(camera_id, "Quality below threshold", quality)
                    return None

                # Prepare metadata
                metadata = {
                    'timestamp': time.time(),
                    'quality': quality,
                    'extraction_time': extraction_time,
                    'frame_size': len(frame_bytes),
                    'resolution': f"{frame.shape[1]}x{frame.shape[0]}"
                }

                # Log successful extraction
                logger.log_frame_extracted(camera_id, len(frame_bytes), quality, extraction_time)

                # Update stats
                self.extraction_stats[camera_id] = {
                    'last_extraction': time.time(),
                    'total_extractions': self.extraction_stats.get(camera_id, {}).get('total_extractions', 0) + 1,
                    'avg_quality': quality,
                    'avg_extraction_time': extraction_time
                }

                return frame, metadata

            else:
                error_msg = result.stderr.decode() if result.stderr else "Unknown FFmpeg error"
                logger.log_camera_disconnected(camera_id, f"FFmpeg extraction failed: {error_msg}", 0)
                return None

        except subprocess.TimeoutExpired:
            logger.log_camera_disconnected(camera_id, "FFmpeg timeout during frame extraction", 0)
            return None
        except Exception as e:
            logger.log_camera_disconnected(camera_id, f"Frame extraction error: {str(e)}", 0)
            return None

    def extract_frame_to_redis(self, camera_url: str, camera_id: str,
                              quality_threshold: float = 50.0) -> bool:
        """
        Extract frame and store in Redis (compatible with face recognition pattern)
        Returns True if successful, False otherwise
        """
        result = self.extract_frame_from_camera(camera_url, camera_id, quality_threshold)

        if result is None:
            return False

        frame, metadata = result

        try:
            # Encode frame as JPEG
            _, buffer_img = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            frame_base64 = base64.b64encode(buffer_img.tobytes()).decode('utf-8')

            # Store in Redis with key pattern: cam{camera_id}
            redis_key = f"cam{camera_id}"
            self.redis_client.set(redis_key, frame_base64, ex=30)  # Expire in 30 seconds

            logger.log_frame_processed(
                camera_id,
                metadata['extraction_time'],
                0,  # ingots_detected will be updated by processor
                None  # barcode will be updated by processor
            )

            return True

        except Exception as e:
            logger.log_frame_dropped(camera_id, f"Redis storage failed: {str(e)}")
            return False

    def get_frame_from_redis(self, camera_id: str) -> Optional[Tuple[np.ndarray, Dict[str, Any]]]:
        """
        Get frame from Redis and decode it
        Returns frame and metadata if available, None otherwise
        """
        try:
            # Get base64 frame from Redis
            redis_key = f"cam{camera_id}"
            frame_base64 = self.redis_client.get(redis_key)

            if not frame_base64:
                return None

            # Decode base64 to image
            frame_bytes = base64.b64decode(frame_base64)
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is None:
                return None

            # Prepare metadata
            metadata = {
                'timestamp': time.time(),
                'source': 'redis',
                'frame_size': len(frame_bytes),
                'resolution': f"{frame.shape[1]}x{frame.shape[0]}"
            }

            return frame, metadata

        except Exception as e:
            logger.log_frame_dropped(camera_id, f"Redis frame retrieval failed: {str(e)}")
            return None

    def test_camera_connection(self, camera_url: str, camera_id: str) -> bool:
        """
        Test camera connection by attempting frame extraction
        Returns True if connection is successful, False otherwise
        """
        try:
            start_time = time.time()
            result = self.extract_frame_from_camera(camera_url, camera_id, quality_threshold=0.0)

            if result is not None:
                connection_time = time.time() - start_time
                frame, metadata = result
                resolution = metadata['resolution']

                logger.log_camera_connected(camera_id, camera_url, resolution)
                self.connection_status[camera_id] = {
                    'status': 'CONNECTED',
                    'last_check': time.time(),
                    'connection_time': connection_time,
                    'url': camera_url
                }
                return True
            else:
                logger.log_camera_disconnected(camera_id, "Connection test failed", 0)
                self.connection_status[camera_id] = {
                    'status': 'DISCONNECTED',
                    'last_check': time.time(),
                    'url': camera_url
                }
                return False

        except Exception as e:
            logger.log_camera_disconnected(camera_id, f"Connection test error: {str(e)}", 0)
            return False

    def get_extraction_stats(self, camera_id: str) -> Dict[str, Any]:
        """Get extraction statistics for a camera"""
        return self.extraction_stats.get(camera_id, {})

    def get_connection_status(self, camera_id: str) -> Dict[str, Any]:
        """Get connection status for a camera"""
        return self.connection_status.get(camera_id, {})

class VideoFrameExtractor:
    """Demand-driven frame extractor for video files"""

    def __init__(self):
        self.video_caps = {}
        self.frame_positions = {}

    def extract_frame_from_video(self, video_path: str, video_id: str,
                                frame_number: Optional[int] = None) -> Optional[Tuple[np.ndarray, Dict[str, Any]]]:
        """
        Extract specific frame from video file
        If frame_number is None, gets the next frame
        """
        try:
            # Initialize video capture if not exists
            if video_id not in self.video_caps:
                cap = cv2.VideoCapture(video_path)
                if not cap.isOpened():
                    logger.log_camera_disconnected(video_id, f"Failed to open video: {video_path}", 0)
                    return None

                self.video_caps[video_id] = cap
                self.frame_positions[video_id] = 0

                # Log video connection
                fps = cap.get(cv2.CAP_PROP_FPS)
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

                logger.log_camera_connected(video_id, video_path, f"{width}x{height}")

            cap = self.video_caps[video_id]

            # Set frame position if specified
            if frame_number is not None:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                self.frame_positions[video_id] = frame_number

            # Read frame
            ret, frame = cap.read()

            if not ret:
                logger.log_camera_disconnected(video_id, "End of video reached", 0)
                self.cleanup_video(video_id)
                return None

            # Prepare metadata
            current_frame = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
            metadata = {
                'timestamp': time.time(),
                'frame_number': current_frame,
                'video_path': video_path,
                'resolution': f"{frame.shape[1]}x{frame.shape[0]}"
            }

            self.frame_positions[video_id] = current_frame

            return frame, metadata

        except Exception as e:
            logger.log_camera_disconnected(video_id, f"Video frame extraction error: {str(e)}", 0)
            return None

    def cleanup_video(self, video_id: str):
        """Clean up video capture resources"""
        if video_id in self.video_caps:
            self.video_caps[video_id].release()
            del self.video_caps[video_id]
            del self.frame_positions[video_id]

    def cleanup_all(self):
        """Clean up all video captures"""
        for video_id in list(self.video_caps.keys()):
            self.cleanup_video(video_id)