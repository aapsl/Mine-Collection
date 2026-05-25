import asyncio
import logging
import asyncpg
from typing import Optional, List, Dict, Any
from functools import lru_cache

from bot.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DATABASE_URL

_pool: Optional[asyncpg.Pool] = None

def get_pool() -> Optional[asyncpg.Pool]:
    """Возвращает пул соединений"""
    return _pool

async def init_database():
    """Инициализация базы данных"""
    global _pool
    
    logging.info("🔄 Подключение к PostgreSQL...")
    
    try:
        if DATABASE_URL:
            _pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=2,
                max_size=10,
                command_timeout=60
            )
        else:
            _pool = await asyncpg.create_pool(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                database=DB_NAME,
                min_size=2,
                max_size=10,
                command_timeout=60
            )
        
        async with _pool.acquire() as conn:
            await conn.execute("SELECT 1")
        
        await _init_tables()
        logging.info("✅ PostgreSQL готов")
        
    except Exception as e:
        logging.error(f"❌ Ошибка БД: {e}")
        raise

async def _init_tables():
    """Создание таблиц"""
    async with _pool.acquire() as conn:
        # Таблица модов
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mods (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                slug TEXT UNIQUE,
                downloads BIGINT DEFAULT 0,
                updated_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                last_checked TIMESTAMPTZ,
                categories TEXT[],
                license TEXT,
                client_side TEXT,
                server_side TEXT
            )
        """)
        
        # Таблица версий
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS versions (
                id TEXT PRIMARY KEY,
                mod_id TEXT NOT NULL REFERENCES mods(id) ON DELETE CASCADE,
                version_number TEXT NOT NULL,
                loaders TEXT[] NOT NULL,
                game_versions TEXT[] NOT NULL,
                download_url TEXT NOT NULL,
                filename TEXT,
                published_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                file_size BIGINT,
                sha512_hash TEXT,
                changelog TEXT,
                version_type TEXT
            )
        """)
        
        # Таблица пользователей
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                last_interaction TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Таблица подписок
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                mod_id TEXT NOT NULL REFERENCES mods(id) ON DELETE CASCADE,
                mod_name TEXT NOT NULL,
                last_version TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, mod_id)
            )
        """)
        
        # Индексы
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mods_downloads ON mods(downloads DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_mods_slug ON mods(slug)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_versions_mod ON versions(mod_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_mod ON subscriptions(mod_id)")

async def close_database():
    """Закрытие соединения"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logging.info("✅ БД закрыта")

# ============ ПОЛЬЗОВАТЕЛИ ============

async def register_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None, language_code: str = None):
    """Регистрирует или обновляет информацию о пользователе"""
    global _pool
    
    # Проверяем, инициализирован ли пул
    if _pool is None:
        logging.error(f"❌ Пул БД не инициализирован при регистрации пользователя {user_id}")
        # Пробуем переинициализировать
        try:
            await init_database()
        except Exception as e:
            logging.error(f"❌ Не удалось переинициализировать БД: {e}")
            return
    
    try:
        async with _pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, language_code, last_interaction)
                VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    language_code = EXCLUDED.language_code,
                    last_interaction = CURRENT_TIMESTAMP
            """, user_id, username, first_name, last_name, language_code)
            logging.info(f"✅ Пользователь {user_id} зарегистрирован/обновлён")
    except Exception as e:
        logging.error(f"❌ Ошибка при регистрации пользователя {user_id}: {e}") 

async def get_users_count() -> int:
    """Количество пользователей"""
    if _pool is None:
        return 0
    async with _pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users")

async def get_all_users() -> List[int]:
    """Список всех пользователей"""
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [row['user_id'] for row in rows]

# ============ МОДЫ ============

async def get_mod_versions(mod_id: str) -> List[Dict]:
    """Версии мода"""
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, version_number, loaders, game_versions, download_url, 
                   filename, published_at, file_size, version_type
            FROM versions 
            WHERE mod_id = $1 
            ORDER BY published_at DESC
        """, mod_id)
        return [dict(row) for row in rows]

async def get_all_mod_loaders(mod_id: str) -> List[str]:
    """Загрузчики мода"""
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT unnest(loaders) as loader FROM versions WHERE mod_id = $1", mod_id)
        return sorted([row['loader'] for row in rows if row['loader']])

async def get_mod_stats() -> Dict:
    """Статистика"""
    if _pool is None:
        return {}
    async with _pool.acquire() as conn:
        mods = await conn.fetchval("SELECT COUNT(*) FROM mods")
        vers = await conn.fetchval("SELECT COUNT(*) FROM versions")
        last = await conn.fetchval("SELECT MAX(last_checked) FROM mods")
        return {"mods_count": mods, "versions_count": vers, "last_updated": last}

# ============ ПОДПИСКИ ============

async def add_subscription(user_id: int, mod_id: str, mod_name: str, last_version: str = None) -> bool:
    """Добавить подписку"""
    if _pool is None:
        return False
    try:
        async with _pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO subscriptions (user_id, mod_id, mod_name, last_version, updated_at)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, mod_id) DO UPDATE SET
                    mod_name = EXCLUDED.mod_name,
                    last_version = EXCLUDED.last_version,
                    updated_at = CURRENT_TIMESTAMP
            """, user_id, mod_id, mod_name, last_version)
            return True
    except Exception as e:
        logging.error(f"Ошибка подписки: {e}")
        return False

async def remove_subscription(user_id: int, mod_id: str) -> bool:
    """Удалить подписку"""
    if _pool is None:
        return False
    try:
        async with _pool.acquire() as conn:
            result = await conn.execute("DELETE FROM subscriptions WHERE user_id = $1 AND mod_id = $2", user_id, mod_id)
            return result == "DELETE 1"
    except Exception as e:
        logging.error(f"Ошибка отписки: {e}")
        return False

async def get_user_subscriptions(user_id: int) -> List[Dict]:
    """Подписки пользователя"""
    if _pool is None:
        return []
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT s.*, COALESCE(m.title, s.mod_name) as mod_title, COALESCE(m.slug, s.mod_id) as mod_slug
                FROM subscriptions s
                LEFT JOIN mods m ON s.mod_id = m.id
                WHERE s.user_id = $1
                ORDER BY s.mod_name
            """, user_id)
            return [dict(row) for row in rows]
    except Exception as e:
        logging.error(f"Ошибка получения подписок: {e}")
        return []

async def get_subscriptions_for_mod(mod_id: str) -> List[Dict]:
    """Подписчики мода"""
    if _pool is None:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM subscriptions WHERE mod_id = $1", mod_id)
        return [dict(row) for row in rows]

async def update_subscription_version(mod_id: str, new_version: str) -> int:
    """Обновить версию для всех подписок"""
    if _pool is None:
        return 0
    async with _pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE subscriptions SET last_version = $1, updated_at = CURRENT_TIMESTAMP WHERE mod_id = $2
        """, new_version, mod_id)
        return int(result.split()[-1]) if "UPDATE" in result else 0