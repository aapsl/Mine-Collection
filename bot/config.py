import logging
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "1649504565").split(",")]
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# PostgreSQL
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME", "MineCollection")
DATABASE_URL = os.getenv("DATABASE_URL")

# Redis
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

# Пути
MOD_ALIASES_PATH = os.getenv("MOD_ALIASES_PATH", "mod_aliases.json")

def validate_config():
    """Проверяет обязательные переменные"""
    if not BOT_TOKEN:
        logging.error("❌ BOT_TOKEN не указан")
        return False
    if not DB_PASSWORD and not DATABASE_URL:
        logging.error("❌ DB_PASSWORD не указан")
        return False
    return True