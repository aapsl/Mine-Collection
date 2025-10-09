import json
import logging
import redis
from functools import lru_cache

from .config import REDIS_HOST, REDIS_PORT, REDIS_DB

# Инициализация Redis
redis_client = None
REDIS_AVAILABLE = False

def init_redis():
    """Инициализация Redis подключения"""
    global redis_client, REDIS_AVAILABLE
    try:
        redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
        redis_client.ping()
        logging.info("Успешное подключение к Redis")
        REDIS_AVAILABLE = True
    except (redis.ConnectionError, Exception) as e:
        logging.warning(f"Не удалось подключиться к Redis: {e}. Будет использоваться встроенный кэш.")
        REDIS_AVAILABLE = False
    return redis_client

# Функции для работы с Redis
def get_cached_search(query, limit=10):
    """Проверяет, есть ли результаты поиска в кэше"""
    if not REDIS_AVAILABLE:
        return None
    try:
        cache_key = f"search:{query}:{limit}"
        cached_data = redis_client.get(cache_key)
        if cached_data:
            logging.info(f"Найдены кэшированные результаты для: {query}")
            return json.loads(cached_data)
    except Exception as e:
        logging.error(f"Ошибка при получении из кэша: {e}")
    return None

def set_cached_search(query, limit=10, results=None):
    """Сохраняет результаты поиска в кэш"""
    if not REDIS_AVAILABLE or results is None:
        return
    try:
        cache_key = f"search:{query}:{limit}"
        redis_client.setex(cache_key, 3600, json.dumps(results))
        logging.info(f"Результаты для '{query}' сохранены в кэш")
    except Exception as e:
        logging.error(f"Ошибка при сохранении в кэш: {e}")

def clear_cache():
    """Очищает весь кэш Redis"""
    if REDIS_AVAILABLE:
        try:
            redis_client.flushdb()
            logging.info("Кэш Redis полностью очищен")
            return True
        except Exception as e:
            logging.error(f"Ошибка при очистке кэша Redis: {e}")
    return False