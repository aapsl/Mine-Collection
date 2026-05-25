import json
import logging
import redis
from functools import lru_cache

from bot.config import REDIS_HOST, REDIS_PORT, REDIS_DB

redis_client = None
REDIS_AVAILABLE = False

def init_redis():
    global redis_client, REDIS_AVAILABLE
    try:
        redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
        redis_client.ping()
        REDIS_AVAILABLE = True
        logging.info("✅ Redis подключен")
    except Exception as e:
        logging.warning(f"Redis не доступен: {e}")
        REDIS_AVAILABLE = False

def get_cached_search(query: str, limit: int = 10):
    if not REDIS_AVAILABLE:
        return None
    try:
        data = redis_client.get(f"search:{query}:{limit}")
        return json.loads(data) if data else None
    except:
        return None

def set_cached_search(query: str, limit: int, results):
    if not REDIS_AVAILABLE:
        return
    try:
        redis_client.setex(f"search:{query}:{limit}", 3600, json.dumps(results, default=str))
    except:
        pass

def clear_cache():
    if REDIS_AVAILABLE:
        try:
            redis_client.flushdb()
            return True
        except:
            return False
    return False