import redis
import logging
import time

logger = logging.getLogger(__name__)
from config.config import settings

class RedisClient:
    def __init__(self, host, port, db):
        self.redis = redis.Redis(
            host=host,
            port=port,
            db=db,
            decode_responses=False
        )
        self.connect()

    def connect(self):
        try:
            self.redis.ping()
            logger.info("Connected to Redis")
        except redis.ConnectionError as e:
            logger.error(f"Redis connection failed: {e}")
            time.sleep(5)
            raise

    def publish(self, list_name, message):
        try:
            self.redis.lpush(list_name, message)
            self.redis.ltrim(list_name, 0, settings.REDIS_QUEUE_MAXLEN - 1)
            logger.debug(f"Published message to Redis list {list_name}")
        except redis.RedisError as e:
            logger.error(f"Error publishing to Redis: {e}")
            self.connect()

    def brpop(self, list_name, timeout=1):
        try:
            message = self.redis.brpop(list_name, timeout=timeout)
            if message:
                return message[1]  # message is a tuple (list_name, value)
            return None
        except redis.RedisError as e:
            logger.error(f"Error getting message from Redis: {e}")
            self.connect()
            return None

    def close(self):
        try:
            self.redis.close()
            logger.info("Redis connection closed")
        except redis.RedisError as e:
            logger.error(f"Error closing Redis connection: {e}")