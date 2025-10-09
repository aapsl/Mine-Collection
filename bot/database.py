import sqlite3
import logging
from datetime import datetime
from functools import lru_cache

from bot.config import DB_PATH

# Инициализация таблиц
def init_database():
    """Инициализация всех таблиц базы данных"""
    init_users_table()
    init_subscriptions_table()

def init_users_table():
    """Создает таблицу пользователей, если она не существует"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    language_code TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logging.info("Таблица пользователей готова")
    except sqlite3.Error as e:
        logging.error(f"Ошибка при создании таблицы пользователей: {e}")

def init_subscriptions_table():
    """Создает таблицу подписок, если она не существует"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    mod_id TEXT NOT NULL,
                    mod_name TEXT NOT NULL,
                    last_version TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, mod_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_mod ON subscriptions (mod_id)")
            logging.info("Таблица подписок готова")
    except sqlite3.Error as e:
        logging.error(f"Ошибка при создании таблица подписок: {e}")

# Функции для работы с пользователями
def register_user(user_id: int, username: str, first_name: str, last_name: str, language_code: str):
    """Регистрирует или обновляет информацию о пользователе"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, language_code, last_interaction)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (user_id, username, first_name, last_name, language_code))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Ошибка при регистрации пользователя: {e}")

def get_all_users():
    """Возвращает список всех пользователей"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении списка пользователей: {e}")
        return []

def get_users_count():
    """Возвращает количество пользователей"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            return cursor.fetchone()[0]
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении количества пользователей: {e}")
        return 0

# Функции для работы с подписками
def add_subscription(user_id: int, mod_id: str, mod_name: str, last_version: str = None):
    """Добавляет подписку пользователя на мод"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            
            # Сначала проверяем, существует ли уже подписка
            cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id = ? AND mod_id = ?", 
                          (user_id, mod_id))
            exists = cursor.fetchone()[0] > 0
            
            if exists:
                # Обновляем существующую подписку
                cursor.execute("""
                    UPDATE subscriptions 
                    SET mod_name = ?, last_version = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND mod_id = ?
                """, (mod_name, last_version, user_id, mod_id))
                logging.info(f"Обновлена подписка пользователя {user_id} на мод {mod_name} ({mod_id})")
            else:
                # Добавляем новую подпику
                cursor.execute("""
                    INSERT INTO subscriptions (user_id, mod_id, mod_name, last_version, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (user_id, mod_id, mod_name, last_version))
                logging.info(f"Добавлена подписка пользователя {user_id} на мод {mod_name} ({mod_id})")
            
            conn.commit()
            return True
            
    except sqlite3.Error as e:
        logging.error(f"Ошибка при добавлении/обновлении подписки: {e}")
        return False

def remove_subscription(user_id: int, mod_id: str):
    """Удаляет подписку пользователя на мод"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM subscriptions WHERE user_id = ? AND mod_id = ?", (user_id, mod_id))
            conn.commit()
            logging.info(f"Пользователь {user_id} отписался от мода {mod_id}")
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"Ошибка при удалении подписки: {e}")
        return False

def get_user_subscriptions(user_id: int):
    """Возвращает все подписки пользователя"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT s.*, 
                       COALESCE(m.title, s.mod_name) as mod_title, 
                       COALESCE(m.slug, s.mod_id) as mod_slug
                FROM subscriptions s
                LEFT JOIN mods m ON s.mod_id = m.id
                WHERE s.user_id = ?
                ORDER BY s.mod_name
            """, (user_id,))
            
            subscriptions = [dict(row) for row in cursor.fetchall()]
            logging.info(f"Найдено {len(subscriptions)} подписок для пользователя {user_id}")
            return subscriptions
            
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении подписок пользователя {user_id}: {e}")
        return []

def get_subscriptions_for_mod(mod_id: str):
    """Возвращает всех пользователей, подписанных на мод"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscriptions WHERE mod_id = ?", (mod_id,))
            return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении подписок на мод: {e}")
        return []

def update_subscription_version(mod_id: str, new_version: str):
    """Обновляет последнюю версию для всех подписок на мод"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE subscriptions 
                SET last_version = ?, updated_at = CURRENT_TIMESTAMP
                WHERE mod_id = ?
            """, (new_version, mod_id))
            conn.commit()
            logging.info(f"Обновлена версия для подписок на мод {mod_id}: {new_version}")
            return cursor.rowcount
    except sqlite3.Error as e:
        logging.error(f"Ошибка при обновлении версии подписки: {e}")
        return 0

# Функции для работы с модами
def get_mod_versions(mod_id: str):
    """Получаем все версии мода с поддержкой разных версий Minecraft"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT v.id, v.version_number, v.loaders, v.game_versions, 
                       v.download_url, v.filename, v.published_at, v.file_size, v.version_type
                FROM versions v
                WHERE v.mod_id = ?
                ORDER BY v.published_at DESC
            """, (mod_id,))
            # Преобразуем Row объекты в словари
            versions = [dict(row) for row in cursor.fetchall()]
            logging.info(f"Получено {len(versions)} версий для мода {mod_id}")
            return versions
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении версий мода {mod_id}: {e}")
        return []

def get_all_mod_loaders(mod_id: str):
    """Получаем все уникальные загрузчики для мода"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT v.loaders
                FROM versions v
                WHERE v.mod_id = ?
            """, (mod_id,))
            
            loaders = set()
            for row in cursor.fetchall():
                if row[0]:
                    loaders.update(row[0].split(','))
            
            return sorted(loaders)
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении загрузчиков мода: {e}")
        return []

def get_mod_stats():
    """Возвращает статистику по модам и версиям"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM mods")
            mods_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM versions")
            versions_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT MAX(last_checked) FROM mods")
            last_updated = cursor.fetchone()[0]
            
            return {
                "mods_count": mods_count,
                "versions_count": versions_count,
                "last_updated": last_updated
            }
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении статистики модов: {e}")
        return {}
    
def check_mod_exists(mod_name: str):
    """Проверяет, существует ли мод с указанным названием в базе данных"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM mods WHERE title = ?", (mod_name,))
            count = cursor.fetchone()[0]
            return count > 0
    except sqlite3.Error as e:
        logging.error(f"Ошибка при проверке существования мода: {e}")
        return False