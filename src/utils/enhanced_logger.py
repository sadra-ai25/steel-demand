import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from enum import Enum
from typing import Optional, Dict, Any
import json

class LogLevel(Enum):
    """Log levels for different system events"""
    CRITICAL_ERROR = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"
    TRACE = "TRACE"

class SystemEventType(Enum):
    """System event types for comprehensive logging"""
    # Frame Processing Events
    FRAME_EXTRACTED = "FRAME_EXTRACTED"
    FRAME_PROCESSED = "FRAME_PROCESSED"
    FRAME_QUALITY_CHECK = "FRAME_QUALITY_CHECK"
    FRAME_DROPPED = "FRAME_DROPPED"

    # Ingot Counting Events
    INGOT_DETECTED = "INGOT_DETECTED"
    INGOT_COUNT_UPDATED = "INGOT_COUNT_UPDATED"
    INGOT_SIZE_MEASURED = "INGOT_SIZE_MEASURED"
    COUNTING_LINE_CROSSED = "COUNTING_LINE_CROSSED"

    # Barcode Events
    BARCODE_DETECTED = "BARCODE_DETECTED"
    BARCODE_READ_SUCCESS = "BARCODE_READ_SUCCESS"
    BARCODE_READ_FAILED = "BARCODE_READ_FAILED"
    BARCODE_DUPLICATE_FILTERED = "BARCODE_DUPLICATE_FILTERED"

    # Production Line Events
    PRODUCTION_STARTED = "PRODUCTION_STARTED"
    PRODUCTION_STOPPED = "PRODUCTION_STOPPED"
    PRODUCTION_IDLE_DETECTED = "PRODUCTION_IDLE_DETECTED"
    PRODUCTION_SPEED_CHANGE = "PRODUCTION_SPEED_CHANGE"

    # Camera/Stream Events
    CAMERA_CONNECTED = "CAMERA_CONNECTED"
    CAMERA_DISCONNECTED = "CAMERA_DISCONNECTED"
    CAMERA_RECONNECT_ATTEMPT = "CAMERA_RECONNECT_ATTEMPT"
    STREAM_STARTED = "STREAM_STARTED"
    STREAM_STOPPED = "STREAM_STOPPED"
    STREAM_ERROR = "STREAM_ERROR"
    STREAM_QUALITY_DEGRADED = "STREAM_QUALITY_DEGRADED"

    # Database Events
    DB_SYNC_STARTED = "DB_SYNC_STARTED"
    DB_SYNC_COMPLETED = "DB_SYNC_COMPLETED"
    DB_SYNC_FAILED = "DB_SYNC_FAILED"
    DB_CONNECTION_LOST = "DB_CONNECTION_LOST"
    DB_CONNECTION_RESTORED = "DB_CONNECTION_RESTORED"
    DB_RECORD_INSERTED = "DB_RECORD_INSERTED"
    DB_RECORD_UPDATED = "DB_RECORD_UPDATED"

    # System Performance Events
    REDIS_QUEUE_STATUS = "REDIS_QUEUE_STATUS"
    MEMORY_USAGE = "MEMORY_USAGE"
    CPU_USAGE = "CPU_USAGE"
    PROCESSING_LATENCY = "PROCESSING_LATENCY"
    SYSTEM_HEALTH_CHECK = "SYSTEM_HEALTH_CHECK"

    # AI Processing Events
    AI_MODEL_LOADED = "AI_MODEL_LOADED"
    AI_INFERENCE_STARTED = "AI_INFERENCE_STARTED"
    AI_INFERENCE_COMPLETED = "AI_INFERENCE_COMPLETED"
    AI_CONFIDENCE_LOW = "AI_CONFIDENCE_LOW"

    # Error and Recovery Events
    PROCESS_CRASHED = "PROCESS_CRASHED"
    PROCESS_RESTARTED = "PROCESS_RESTARTED"
    AUTOMATIC_RECOVERY = "AUTOMATIC_RECOVERY"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"

class EnhancedLogger:
    """Comprehensive logging system for steel ingot analysis"""

    def __init__(self, logger_name: str):
        self.logger = logging.getLogger(logger_name)
        self.timezone = ZoneInfo("Asia/Tehran")

        # Performance tracking
        self._last_ingot_count = {}
        self._production_status = {}
        self._camera_status = {}
        self._processing_times = {}

    def _get_timestamp(self) -> str:
        """Get formatted timestamp in Tehran timezone"""
        return datetime.now(self.timezone).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def _log_event(self, level: LogLevel, event_type: SystemEventType,
                   source_id: str, message: str, **kwargs):
        """Core logging method with structured format"""
        timestamp = self._get_timestamp()

        log_data = {
            "timestamp": timestamp,
            "level": level.value,
            "event_type": event_type.value,
            "source_id": source_id,
            "message": message,
            **kwargs
        }

        # Format log message
        formatted_msg = f"[{timestamp}] [{level.value}] [{event_type.value}] [{source_id}] {message}"
        if kwargs:
            formatted_msg += f" | Data: {json.dumps(kwargs, default=str)}"

        # Log at appropriate level
        if level == LogLevel.CRITICAL_ERROR:
            self.logger.critical(formatted_msg)
        elif level == LogLevel.ERROR:
            self.logger.error(formatted_msg)
        elif level == LogLevel.WARNING:
            self.logger.warning(formatted_msg)
        elif level == LogLevel.INFO:
            self.logger.info(formatted_msg)
        elif level == LogLevel.DEBUG:
            self.logger.debug(formatted_msg)
        else:  # TRACE
            self.logger.debug(formatted_msg)

    # Frame Processing Logs
    def log_frame_extracted(self, source_id: str, frame_size: int, quality: float,
                           extraction_time: float):
        """Log successful frame extraction"""
        self._log_event(
            LogLevel.INFO, SystemEventType.FRAME_EXTRACTED, source_id,
            f"Frame extracted successfully",
            frame_size_bytes=frame_size,
            quality_score=quality,
            extraction_time_ms=round(extraction_time * 1000, 2)
        )

    def log_frame_processed(self, source_id: str, processing_time: float,
                           ingots_detected: int, barcode_found: Optional[str] = None):
        """Log frame processing completion"""
        self._processing_times[source_id] = processing_time
        self._log_event(
            LogLevel.INFO, SystemEventType.FRAME_PROCESSED, source_id,
            f"Frame processed successfully",
            processing_time_ms=round(processing_time * 1000, 2),
            ingots_detected=ingots_detected,
            barcode_found=barcode_found
        )

    def log_frame_quality_check(self, source_id: str, quality: float,
                               threshold: float, passed: bool):
        """Log frame quality assessment"""
        level = LogLevel.DEBUG if passed else LogLevel.WARNING
        self._log_event(
            level, SystemEventType.FRAME_QUALITY_CHECK, source_id,
            f"Frame quality {'passed' if passed else 'failed'} threshold check",
            quality_score=quality,
            threshold=threshold,
            passed=passed
        )

    def log_frame_dropped(self, source_id: str, reason: str, quality: Optional[float] = None):
        """Log frame being dropped"""
        self._log_event(
            LogLevel.WARNING, SystemEventType.FRAME_DROPPED, source_id,
            f"Frame dropped: {reason}",
            reason=reason,
            quality_score=quality
        )

    # Ingot Counting Logs
    def log_ingot_detected(self, source_id: str, ingot_count: int, size: float,
                          width: float, confidence: float, position: Dict[str, int]):
        """Log ingot detection"""
        self._log_event(
            LogLevel.INFO, SystemEventType.INGOT_DETECTED, source_id,
            f"Ingot detected",
            ingot_count=ingot_count,
            size_mm=size,
            width_mm=width,
            confidence=confidence,
            position=position
        )

    def log_ingot_count_updated(self, source_id: str, previous_count: int,
                               new_count: int, increment: int):
        """Log ingot count update"""
        self._last_ingot_count[source_id] = new_count
        self._log_event(
            LogLevel.INFO, SystemEventType.INGOT_COUNT_UPDATED, source_id,
            f"Ingot count updated: {previous_count} → {new_count} (+{increment})",
            previous_count=previous_count,
            new_count=new_count,
            increment=increment
        )

    def log_counting_line_crossed(self, source_id: str, line_position: int,
                                 ingot_id: str, direction: str):
        """Log ingot crossing counting line"""
        self._log_event(
            LogLevel.INFO, SystemEventType.COUNTING_LINE_CROSSED, source_id,
            f"Ingot crossed counting line",
            line_position=line_position,
            ingot_id=ingot_id,
            direction=direction
        )

    # Barcode Logs
    def log_barcode_detected(self, source_id: str, barcode: str, confidence: float,
                            position: Dict[str, int], read_time: float):
        """Log barcode detection"""
        self._log_event(
            LogLevel.INFO, SystemEventType.BARCODE_DETECTED, source_id,
            f"Barcode detected: {barcode}",
            barcode=barcode,
            confidence=confidence,
            position=position,
            read_time_ms=round(read_time * 1000, 2)
        )

    def log_barcode_read_success(self, source_id: str, barcode: str, attempts: int):
        """Log successful barcode reading"""
        self._log_event(
            LogLevel.INFO, SystemEventType.BARCODE_READ_SUCCESS, source_id,
            f"Barcode read successfully: {barcode}",
            barcode=barcode,
            attempts=attempts
        )

    def log_barcode_read_failed(self, source_id: str, error: str, attempts: int):
        """Log failed barcode reading"""
        self._log_event(
            LogLevel.ERROR, SystemEventType.BARCODE_READ_FAILED, source_id,
            f"Barcode reading failed: {error}",
            error=error,
            attempts=attempts
        )

    def log_barcode_duplicate_filtered(self, source_id: str, barcode: str,
                                     last_seen_time: str):
        """Log duplicate barcode filtering"""
        self._log_event(
            LogLevel.DEBUG, SystemEventType.BARCODE_DUPLICATE_FILTERED, source_id,
            f"Duplicate barcode filtered: {barcode}",
            barcode=barcode,
            last_seen_time=last_seen_time
        )

    # Production Line Logs
    def log_production_started(self, source_id: str, speed: Optional[float] = None):
        """Log production line start"""
        self._production_status[source_id] = "RUNNING"
        self._log_event(
            LogLevel.INFO, SystemEventType.PRODUCTION_STARTED, source_id,
            "Production line started",
            speed=speed
        )

    def log_production_stopped(self, source_id: str, reason: str, duration_minutes: float):
        """Log production line stop"""
        self._production_status[source_id] = "STOPPED"
        self._log_event(
            LogLevel.WARNING, SystemEventType.PRODUCTION_STOPPED, source_id,
            f"Production line stopped: {reason}",
            reason=reason,
            duration_minutes=duration_minutes
        )

    def log_production_idle_detected(self, source_id: str, idle_duration: float):
        """Log production line idle detection"""
        self._log_event(
            LogLevel.WARNING, SystemEventType.PRODUCTION_IDLE_DETECTED, source_id,
            f"Production line idle detected",
            idle_duration_minutes=idle_duration
        )

    def log_production_speed_change(self, source_id: str, old_speed: float,
                                   new_speed: float):
        """Log production speed change"""
        self._log_event(
            LogLevel.INFO, SystemEventType.PRODUCTION_SPEED_CHANGE, source_id,
            f"Production speed changed: {old_speed} → {new_speed}",
            old_speed=old_speed,
            new_speed=new_speed
        )

    # Camera/Stream Logs
    def log_camera_connected(self, source_id: str, rtsp_url: str, resolution: str):
        """Log camera connection"""
        self._camera_status[source_id] = "CONNECTED"
        self._log_event(
            LogLevel.INFO, SystemEventType.CAMERA_CONNECTED, source_id,
            f"Camera connected successfully",
            rtsp_url=rtsp_url,
            resolution=resolution
        )

    def log_camera_disconnected(self, source_id: str, reason: str,
                               connection_duration: float):
        """Log camera disconnection"""
        self._camera_status[source_id] = "DISCONNECTED"
        self._log_event(
            LogLevel.ERROR, SystemEventType.CAMERA_DISCONNECTED, source_id,
            f"Camera disconnected: {reason}",
            reason=reason,
            connection_duration_minutes=connection_duration
        )

    def log_camera_reconnect_attempt(self, source_id: str, attempt_number: int,
                                    max_attempts: int):
        """Log camera reconnection attempt"""
        self._log_event(
            LogLevel.WARNING, SystemEventType.CAMERA_RECONNECT_ATTEMPT, source_id,
            f"Camera reconnection attempt {attempt_number}/{max_attempts}",
            attempt_number=attempt_number,
            max_attempts=max_attempts
        )

    def log_stream_quality_degraded(self, source_id: str, quality_score: float,
                                   min_quality: float):
        """Log stream quality degradation"""
        self._log_event(
            LogLevel.WARNING, SystemEventType.STREAM_QUALITY_DEGRADED, source_id,
            f"Stream quality degraded",
            quality_score=quality_score,
            min_quality=min_quality
        )

    # Database Logs
    def log_db_sync_started(self, source_id: str, records_to_sync: int):
        """Log database sync start"""
        self._log_event(
            LogLevel.INFO, SystemEventType.DB_SYNC_STARTED, source_id,
            f"Database sync started",
            records_to_sync=records_to_sync
        )

    def log_db_sync_completed(self, source_id: str, synced_records: int,
                             sync_time: float):
        """Log database sync completion"""
        self._log_event(
            LogLevel.INFO, SystemEventType.DB_SYNC_COMPLETED, source_id,
            f"Database sync completed",
            synced_records=synced_records,
            sync_time_seconds=round(sync_time, 2)
        )

    def log_db_sync_failed(self, source_id: str, error: str, failed_records: int):
        """Log database sync failure"""
        self._log_event(
            LogLevel.ERROR, SystemEventType.DB_SYNC_FAILED, source_id,
            f"Database sync failed: {error}",
            error=error,
            failed_records=failed_records
        )

    def log_db_connection_lost(self, source_id: str, error: str):
        """Log database connection loss"""
        self._log_event(
            LogLevel.CRITICAL_ERROR, SystemEventType.DB_CONNECTION_LOST, source_id,
            f"Database connection lost: {error}",
            error=error
        )

    def log_db_connection_restored(self, source_id: str, downtime: float):
        """Log database connection restoration"""
        self._log_event(
            LogLevel.INFO, SystemEventType.DB_CONNECTION_RESTORED, source_id,
            f"Database connection restored",
            downtime_seconds=round(downtime, 2)
        )

    # System Performance Logs
    def log_processing_latency(self, source_id: str, latency: float,
                              target_latency: float):
        """Log processing latency"""
        level = LogLevel.WARNING if latency > target_latency else LogLevel.DEBUG
        self._log_event(
            level, SystemEventType.PROCESSING_LATENCY, source_id,
            f"Processing latency measured",
            latency_ms=round(latency * 1000, 2),
            target_latency_ms=round(target_latency * 1000, 2),
            exceeds_target=latency > target_latency
        )

    def log_system_health_check(self, source_id: str, cpu_usage: float,
                               memory_usage: float, redis_queue_size: int):
        """Log system health metrics"""
        self._log_event(
            LogLevel.INFO, SystemEventType.SYSTEM_HEALTH_CHECK, source_id,
            f"System health check",
            cpu_usage_percent=cpu_usage,
            memory_usage_percent=memory_usage,
            redis_queue_size=redis_queue_size
        )

    # AI Processing Logs
    def log_ai_model_loaded(self, source_id: str, model_path: str, load_time: float):
        """Log AI model loading"""
        self._log_event(
            LogLevel.INFO, SystemEventType.AI_MODEL_LOADED, source_id,
            f"AI model loaded successfully",
            model_path=model_path,
            load_time_seconds=round(load_time, 2)
        )

    def log_ai_inference_completed(self, source_id: str, inference_time: float,
                                  objects_detected: int, confidence_avg: float):
        """Log AI inference completion"""
        self._log_event(
            LogLevel.DEBUG, SystemEventType.AI_INFERENCE_COMPLETED, source_id,
            f"AI inference completed",
            inference_time_ms=round(inference_time * 1000, 2),
            objects_detected=objects_detected,
            confidence_avg=confidence_avg
        )

    def log_ai_confidence_low(self, source_id: str, confidence: float,
                             threshold: float, object_type: str):
        """Log low AI confidence warning"""
        self._log_event(
            LogLevel.WARNING, SystemEventType.AI_CONFIDENCE_LOW, source_id,
            f"Low AI confidence detected",
            confidence=confidence,
            threshold=threshold,
            object_type=object_type
        )

    # Error and Recovery Logs
    def log_process_crashed(self, source_id: str, process_name: str, error: str):
        """Log process crash"""
        self._log_event(
            LogLevel.CRITICAL_ERROR, SystemEventType.PROCESS_CRASHED, source_id,
            f"Process crashed: {process_name}",
            process_name=process_name,
            error=error
        )

    def log_process_restarted(self, source_id: str, process_name: str,
                             restart_time: float):
        """Log process restart"""
        self._log_event(
            LogLevel.INFO, SystemEventType.PROCESS_RESTARTED, source_id,
            f"Process restarted: {process_name}",
            process_name=process_name,
            restart_time_seconds=round(restart_time, 2)
        )

    def log_automatic_recovery(self, source_id: str, issue: str, recovery_action: str):
        """Log automatic recovery action"""
        self._log_event(
            LogLevel.INFO, SystemEventType.AUTOMATIC_RECOVERY, source_id,
            f"Automatic recovery performed",
            issue=issue,
            recovery_action=recovery_action
        )

    def log_manual_intervention_required(self, source_id: str, issue: str,
                                       recommended_action: str):
        """Log manual intervention requirement"""
        self._log_event(
            LogLevel.CRITICAL_ERROR, SystemEventType.MANUAL_INTERVENTION_REQUIRED, source_id,
            f"Manual intervention required",
            issue=issue,
            recommended_action=recommended_action
        )

    # Status getters for monitoring
    def get_camera_status(self, source_id: str) -> str:
        """Get current camera status"""
        return self._camera_status.get(source_id, "UNKNOWN")

    def get_production_status(self, source_id: str) -> str:
        """Get current production status"""
        return self._production_status.get(source_id, "UNKNOWN")

    def get_last_ingot_count(self, source_id: str) -> int:
        """Get last recorded ingot count"""
        return self._last_ingot_count.get(source_id, 0)

    def get_avg_processing_time(self, source_id: str) -> float:
        """Get average processing time"""
        return self._processing_times.get(source_id, 0.0)