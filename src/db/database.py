import sqlite3
import pyodbc
import datetime
import logging
import threading
import time
from config.config import settings

logger = logging.getLogger(__name__)

class DatabaseLogger:
    def __init__(self):
        """Initialize connections to main and local databases."""
        self.main_conn_str = (
            f'DRIVER={{ODBC Driver 17 for SQL Server}};'
            f'SERVER={settings.DB_SERVER};'
            f'DATABASE={settings.DB_NAME};'
            f'UID={settings.USERNAME};'
            f'PWD={settings.PASSWORD}'
        )
        self.local_db_path = "/app/output/local.db"
        self.local_conn = sqlite3.connect(self.local_db_path, check_same_thread=False)
        self.local_cursor = self.local_conn.cursor()
        self._create_local_tables()
        self.main_conn = None
        self.main_cursor = None
        self._connect_to_main_db()
        self.stop_event = threading.Event()  # پرچم برای توقف نخ
        self.sync_thread = threading.Thread(target=self._sync_periodically, daemon=True)
        self.sync_thread.start()
        logger.info("🔄 Synchronization thread started.")

    def _create_local_tables(self):
        """Create tables in the local SQLite database."""
        self.local_cursor.execute("""
            CREATE TABLE IF NOT EXISTS barcodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id TEXT,
                barcode TEXT,
                frame_datetime TEXT,
                frame_data BLOB,
                memo TEXT,
                synced INTEGER DEFAULT 0
            )
        """)
        self.local_cursor.execute("""
            CREATE TABLE IF NOT EXISTS ingots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id TEXT,
                height REAL,
                width REAL,
                frame_datetime TEXT,
                frame_data BLOB,
                memo TEXT,
                synced INTEGER DEFAULT 0
            )
        """)
        self.local_conn.commit()

    def _connect_to_main_db(self):
        """Attempt to connect to the main SQL Server database."""
        try:
            self.main_conn = pyodbc.connect(self.main_conn_str)
            self.main_cursor = self.main_conn.cursor()
            logger.info("✅ Connected to main database")
        except Exception as e:
            logger.warning("⚠️ Connection to SQL database failed, data will only be saved to local database.")
            logger.error(f"🚫 Failed to connect to main database: {e}")
            self.main_conn = None
            self.main_cursor = None

    def log_barcode(self, camera_id, barcode, frame_datetime, frame_data, memo):
        """Log barcode data to the local database and attempt to log to the main database."""
        self.local_cursor.execute(
            "INSERT INTO barcodes (camera_id, barcode, frame_datetime, frame_data, memo, synced) VALUES (?, ?, ?, ?, ?, 0)",
            (camera_id, barcode, frame_datetime.isoformat(), frame_data, memo)
        )
        self.local_conn.commit()
        logger.info(f"📝 Barcode {barcode} for camera {camera_id} saved to local database with synced=0")
        if self.main_conn:
            try:
                # اصلاح: تغییر نام پارامتر از @フレーム به @frame
                self.main_cursor.execute(
                    "EXEC aiStpInsertFrameBarcode @cameraId=?, @barcode=?, @frameDateTime=?, @frame=?, @memo=?",
                    (camera_id, barcode, frame_datetime, frame_data, memo)
                )
                self.main_conn.commit()
                self.local_cursor.execute("UPDATE barcodes SET synced = 1 WHERE id = ?", (self.local_cursor.lastrowid,))
                self.local_conn.commit()
                logger.info(f"✅ Barcode {barcode} synced to main database")
            except Exception as e:
                logger.error(f"❌ Error logging barcode {barcode} to main database: {e}")
                self._connect_to_main_db()

    def log_ingot(self, camera_id, height, width, frame_datetime, frame_data, memo):
        """Log ingot data to the local database and attempt to log to the main database."""
        self.local_cursor.execute(
            "INSERT INTO ingots (camera_id, height, width, frame_datetime, frame_data, memo, synced) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (camera_id, height, width, frame_datetime.isoformat(), frame_data, memo)
        )
        self.local_conn.commit()
        logger.info(f"📝 Ingot for camera {camera_id} saved to local database with synced=0")
        if self.main_conn:
            try:
                # اصلاح: تغییر نام پارامتر از @フレーム به @frame
                self.main_cursor.execute(
                    "EXEC aiStpInsertFrameIngot @cameraId=?, @width=?, @height=?, @frameDateTime=?, @frame=?, @memo=?",
                    (camera_id, width, height, frame_datetime, frame_data, memo)
                )
                self.main_conn.commit()
                self.local_cursor.execute("UPDATE ingots SET synced = 1 WHERE id = ?", (self.local_cursor.lastrowid,))
                self.local_conn.commit()
                logger.info(f"✅ Ingot synced to main database")
            except Exception as e:
                logger.error(f"❌ Error logging ingot to main database: {e}")
                self._connect_to_main_db()

    def synchronize(self):
        """Synchronize unsynced data from local to main database in batches."""
        if not self.main_conn:
            self._connect_to_main_db()
            if not self.main_conn:
                logger.warning("⚠️ Main database unavailable, skipping sync")
                return
        batch_size = 100
        for table in ['barcodes', 'ingots']:
            self.local_cursor.execute(f"SELECT * FROM {table} WHERE synced = 0 ORDER BY id ASC LIMIT {batch_size}")
            records = self.local_cursor.fetchall()
            while records:
                logger.info(f"📋 Found {len(records)} unsynced records in {table}")
                try:
                    for record in records:
                        if table == 'barcodes':
                            self.main_cursor.execute(
                                "SELECT COUNT(*) FROM AiBarcodeInFrame WHERE cameraId = ? AND barcode = ? AND frameDateTime = ?",
                                (record[1], record[2], datetime.datetime.fromisoformat(record[3]))
                            )
                            exists = self.main_cursor.fetchone()[0] > 0
                            if not exists:
                                # اصلاح: تغییر نام پارامتر از @フレーム به @frame
                                self.main_cursor.execute(
                                    "EXEC aiStpInsertFrameBarcode @cameraId=?, @barcode=?, @frameDateTime=?, @frame=?, @memo=?",
                                    (record[1], record[2], datetime.datetime.fromisoformat(record[3]), record[4], record[5])
                                )
                        elif table == 'ingots':
                            self.main_cursor.execute(
                                "SELECT COUNT(*) FROM AiIngotInFrame WHERE cameraId = ? AND height = ? AND width = ? AND frameDateTime = ?",
                                (record[1], record[2], record[3], datetime.datetime.fromisoformat(record[4]))
                            )
                            exists = self.main_cursor.fetchone()[0] > 0
                            if not exists:
                                # اصلاح: تغییر نام پارامتر از @フレーム به @frame
                                self.main_cursor.execute(
                                    "EXEC aiStpInsertFrameIngot @cameraId=?, @width=?, @height=?, @frameDateTime=?, @frame=?, @memo=?",
                                    (record[1], record[3], record[2], datetime.datetime.fromisoformat(record[4]), record[5], record[6])
                                )
                    self.main_conn.commit()
                    ids = [record[0] for record in records]
                    self.local_cursor.execute(f"UPDATE {table} SET synced = 1 WHERE id IN ({','.join('?'*len(ids))})", ids)
                    self.local_conn.commit()
                    logger.info(f"🔄 Synced {len(records)} records from {table}")
                except Exception as e:
                    self.main_conn.rollback()
                    logger.error(f"❌ Sync error in {table}: {e}")
                    time.sleep(5)
                    self._connect_to_main_db()
                    break
                self.local_cursor.execute(f"SELECT * FROM {table} WHERE synced = 0 ORDER BY id ASC LIMIT {batch_size}")
                records = self.local_cursor.fetchall()

    def _sync_periodically(self):
        """Run synchronization every 30 seconds until stopped."""
        while not self.stop_event.is_set():  # توقف در صورت فعال شدن stop_event
            logger.info("🔄 Starting periodic sync")
            self.synchronize()
            time.sleep(30)
        logger.info("🔚 Synchronization thread stopped")

    def close(self):
        """Close all database connections and stop the sync thread."""
        self.stop_event.set()  # سیگنال توقف به نخ همگام‌سازی
        if self.sync_thread and self.sync_thread.is_alive():
            self.sync_thread.join(timeout=2)  # منتظر توقف نخ
        if self.main_conn:
            self.main_conn.close()
        self.local_conn.close()
        logger.info("🔚 Database connections closed.")