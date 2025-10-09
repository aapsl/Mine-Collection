import os
from dotenv import load_dotenv

load_dotenv()

# Убедитесь, что ваш ID указан правильно
ADMIN_IDS = [1649504565, 6820832782]  # Замените на ваш ID пользователя Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "modrinth.db")
MOD_ALIASES_PATH = os.getenv("MOD_ALIASES_PATH", "mod_aliases.json")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Redis configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))