import aiohttp
import asyncio
import asyncpg # Replaced sqlite3 with asyncpg
import time
import logging
from datetime import datetime
from typing import List, Dict, Set, Optional, Tuple
import json
import sys
import os # To get credentials from environment variables
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Configure UTF-8 encoding
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("mod_updater.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class ModUpdateStatus:
    processed: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    filled: int = 0
    versions_added: int = 0
    versions_updated: int = 0
    dependencies_added: int = 0

class RateLimiter:
    """Class for intelligent request rate limiting"""
    def __init__(self, max_rate, time_window=60):
        self.max_rate = max_rate
        self.time_window = time_window
        self.requests = []
        self.lock = asyncio.Lock()
        
    async def acquire(self):
        async with self.lock:
            now = time.time()
            self.requests = [t for t in self.requests if now - t < self.time_window]
            
            if len(self.requests) >= self.max_rate:
                oldest_request = self.requests[0]
                wait_time = self.time_window - (now - oldest_request)
                if wait_time > 0:
                    if wait_time > 2:
                        logger.info(f"Rate limit reached. Waiting for {wait_time:.2f} seconds...")
                    await asyncio.sleep(wait_time)
                    now = time.time()
                    self.requests = [t for t in self.requests if now - t < self.time_window]
            
            self.requests.append(now)

class ModUpdater:
    def __init__(self, postgres_config: dict, api_token: str = None, 
                 max_concurrent_requests: int = 50, force_update: bool = False,
                 min_downloads: int = 1000, fill_missing_data: bool = True,
                 update_all_versions: bool = True):
        self.postgres_config = postgres_config
        self.pool: Optional[asyncpg.Pool] = None
        self.max_concurrent_requests = max_concurrent_requests
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.force_update = force_update
        self.min_downloads = min_downloads
        self.fill_missing_data = fill_missing_data
        self.update_all_versions = update_all_versions
        self.status = ModUpdateStatus()
        self.base_url = "https://api.modrinth.com/v2"
        
        rate_limit = 290 if api_token else 100
        self.rate_limiter = RateLimiter(max_rate=rate_limit, time_window=60)
        
        self.headers = {
            "User-Agent": "Modrinth-Updater/1.0 (contact@example.com)",
            "Accept": "application/json"
        }
        
        if api_token:
            self.headers["Authorization"] = api_token
            logger.info("API токен установлен, лимит запросов увеличен.")
        else:
            logger.warning("API токен не предоставлен. Будут применяться стандартные лимиты запросов.")

    async def init_pool(self):
        """Initialize the PostgreSQL connection pool."""
        try:
            self.pool = await asyncpg.create_pool(**self.postgres_config)
            logger.info("Пул подключений к PostgreSQL успешно создан.")
        except Exception as e:
            logger.error(f"Не удалось создать пул подключений к PostgreSQL: {e}")
            raise

    async def close_pool(self):
        """Close the PostgreSQL connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("Пул подключений к PostgreSQL закрыт.")
    
    async def init_database(self):
        """Initialize the database schema in PostgreSQL."""
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS mods (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    slug TEXT UNIQUE,
                    downloads INTEGER DEFAULT 0,
                    updated_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    last_checked TIMESTAMPTZ,
                    categories TEXT[],
                    license TEXT,
                    client_side TEXT,
                    server_side TEXT
                )
            ''')
            
            # Removed 'dependencies' column from versions table
            await conn.execute('''
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
                    file_size INTEGER,
                    sha512_hash TEXT,
                    changelog TEXT,
                    version_type TEXT
                )
            ''')

            # NEW: Create dependencies table
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS dependencies (
                    id SERIAL PRIMARY KEY,
                    version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE,
                    project_id TEXT,
                    version_id_ref TEXT,
                    dependency_type TEXT,
                    file_name TEXT
                )
            ''')
            
            logger.info("Создание индексов в PostgreSQL...")
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_mods_downloads ON mods(downloads)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_versions_game ON versions USING GIN(game_versions)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_versions_loaders ON versions USING GIN(loaders)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_mods_last_checked ON mods(last_checked)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_mods_updated ON mods(updated_at)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_versions_mod ON versions(mod_id)')
            # NEW: Index for dependencies table
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_dependencies_version ON dependencies(version_id)')
    
    async def get_existing_mods(self) -> Dict[str, datetime]:
        """Get a list of existing mods and their last update times."""
        if not self.pool:
            raise ConnectionError("Database pool is not initialized.")
        
        existing_mods = {}
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("SELECT id, updated_at FROM mods")
                for row in rows:
                    mod_id, updated_at = row['id'], row['updated_at']
                    existing_mods[mod_id] = updated_at if updated_at else datetime.min.replace(tzinfo=None)
        except Exception as e:
            logger.error(f"Ошибка при получении существующих модов: {e}")
        return existing_mods
    
    async def get_existing_versions(self, mod_id: str) -> Set[str]:
        """Get a set of existing version IDs for a specific mod."""
        if not self.pool:
            raise ConnectionError("Database pool is not initialized.")

        existing_versions = set()
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("SELECT id FROM versions WHERE mod_id = $1", mod_id)
                for row in rows:
                    existing_versions.add(row['id'])
        except Exception as e:
            logger.error(f"Ошибка при получении версий для мода {mod_id}: {e}")
        return existing_versions
    
    async def get_mods_with_missing_data(self) -> List[str]:
        """Get a list of mods with missing data fields."""
        if not self.pool:
            raise ConnectionError("Database pool is not initialized.")

        query = """
            SELECT id FROM mods 
            WHERE description IS NULL OR description = ''
               OR categories IS NULL OR array_length(categories, 1) IS NULL
               OR license IS NULL OR license = ''
               OR client_side = 'unknown' OR server_side = 'unknown'
               OR downloads = 0
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query)
                mod_ids = [row['id'] for row in rows]
                logger.info(f"Найдено {len(mod_ids)} модов с неполными данными.")
                return mod_ids
        except Exception as e:
            logger.error(f"Ошибка при поиске модов с неполными данными: {e}")
            return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError, aiohttp.ServerDisconnectedError))
    )
    async def make_async_request(self, session, url, params=None):
        """Asynchronous request with retries and rate limiting."""
        params = params or {}
        await self.rate_limiter.acquire()
        async with self.semaphore:
            try:
                async with session.get(url, params=params, headers=self.headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 5))
                        logger.warning(f"Достигнут лимит запросов. Ожидание {retry_after} секунд...")
                        await asyncio.sleep(retry_after)
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info, history=response.history,
                            status=429, message=f"Rate limit exceeded, retry after {retry_after} seconds",
                            headers=response.headers
                        )
                    if response.status >= 400:
                        error_text = await response.text()
                        logger.error(f"HTTP ошибка {response.status}: {error_text}")
                        response.raise_for_status()
                    return await response.json()
            except asyncio.TimeoutError:
                logger.warning(f"Тайм-аут при запросе к {url}")
                raise
            except aiohttp.ClientError as e:
                logger.warning(f"Ошибка клиента при запросе к {url}: {e}")
                raise
            except Exception as e:
                logger.error(f"Непредвиденная ошибка при запросе к {url}: {e}")
                raise

    async def get_all_mod_ids(self, session) -> List[str]:
        """Get all mod IDs from Modrinth, with detailed logging in Russian."""
        all_mods = []
        limit = 100
        offset = 0
        logger.info("Начинаем получение списка популярных модов с Modrinth...")
        page_num = 1
        while True:
            params = {"limit": limit, "offset": offset, "index": "downloads"}
            data = await self.make_async_request(session, f"{self.base_url}/search", params)
            if not data or "hits" not in data:
                break
            
            page_mods = [mod for mod in data["hits"] if mod.get("downloads", 0) >= self.min_downloads]
            if not page_mods:
                break
                
            all_mods.extend(page_mods)
            # NEW: Detailed logging in Russian
            logger.info(f"Страница {page_num}: Найдено {len(data['hits'])} модов. Всего накоплено: {len(all_mods)}")

            if len(data["hits"]) < limit:
                break
            offset += limit
            page_num += 1
            await asyncio.sleep(0.1)
        
        mod_ids = [mod["project_id"] for mod in all_mods]
        logger.info(f"Всего получено {len(mod_ids)} модов с >= {self.min_downloads} загрузок.")
        return mod_ids

    async def get_mod_details_batch(self, session, mod_ids: List[str]) -> Dict[str, Dict]:
        """Get details for a batch of mods."""
        if not mod_ids:
            return {}
        try:
            batch_size = 50
            all_details = {}
            for i in range(0, len(mod_ids), batch_size):
                batch = mod_ids[i:i + batch_size]
                ids_param = json.dumps(batch)
                data = await self.make_async_request(session, f"{self.base_url}/projects", params={"ids": ids_param})
                if data:
                    all_details.update({mod["id"]: mod for mod in data if mod is not None})
            return all_details
        except Exception as e:
            logger.error(f"Ошибка при получении деталей модов: {e}")
            return {}

    async def get_all_mod_versions(self, session, mod_id: str) -> List[Dict]:
        """Get all versions for a mod with pagination."""
        all_versions = []
        limit = 100
        offset = 0
        while True:
            params = {"limit": limit, "offset": offset}
            data = await self.make_async_request(session, f"{self.base_url}/project/{mod_id}/version", params)
            if not data:
                break
            all_versions.extend(data)
            if len(data) < limit:
                break
            offset += limit
            await asyncio.sleep(0.1)
        return all_versions

    async def get_mod_versions_batch(self, session, mod_ids: List[str]) -> Dict[str, List]:
        """Get versions for a batch of mods."""
        if not mod_ids: return {}
        try:
            tasks = {mod_id: asyncio.create_task(self.get_all_mod_versions(session, mod_id)) for mod_id in mod_ids}
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            all_versions = {}
            for mod_id, result in zip(tasks.keys(), results):
                if isinstance(result, Exception):
                    logger.error(f"Ошибка при получении версий для мода {mod_id}: {result}")
                    all_versions[mod_id] = []
                else:
                    all_versions[mod_id] = result
            return all_versions
        except Exception as e:
            logger.error(f"Ошибка при получении версий модов: {e}")
            return {}

    def needs_update(self, mod_id: str, mod_data: Dict, existing_mods: Dict[str, datetime]) -> bool:
        """Check if a mod needs to be updated."""
        if self.force_update or mod_id not in existing_mods:
            return True
        
        if "updated" in mod_data:
            try:
                api_updated_str = mod_data["updated"].replace('Z', '+00:00')
                api_updated = datetime.fromisoformat(api_updated_str)
                db_updated = existing_mods[mod_id]
                if db_updated:
                    return api_updated > db_updated.replace(tzinfo=api_updated.tzinfo)
                return True
            except (ValueError, TypeError):
                return False
        return False
    
    async def has_missing_data(self, mod_id: str) -> bool:
        """Check if a mod has missing data in the DB."""
        if not self.pool: raise ConnectionError("Database pool is not initialized.")
        query = """
            SELECT 1 FROM mods 
            WHERE id = $1 AND (
                description IS NULL OR description = '' OR
                categories IS NULL OR array_length(categories, 1) IS NULL OR
                license IS NULL OR license = '' OR
                client_side = 'unknown' OR
                server_side = 'unknown' OR
                downloads = 0
            )
        """
        try:
            async with self.pool.acquire() as conn:
                return await conn.fetchval(query, mod_id) is not None
        except Exception as e:
            logger.error(f"Ошибка при проверке неполных данных для мода {mod_id}: {e}")
            return True

    async def process_mod_batch(self, session, mod_ids: List[str], existing_mods: Dict[str, datetime]):
        """Process a batch of mods."""
        mod_details = await self.get_mod_details_batch(session, mod_ids)
        mod_versions = {}
        if self.update_all_versions:
            mod_versions = await self.get_mod_versions_batch(session, mod_ids)
        
        mods_to_update = {}
        for mod_id in mod_ids:
            self.status.processed += 1
            if mod_id not in mod_details:
                self.status.errors += 1
                continue
            
            mod_data = mod_details[mod_id]
            if mod_data.get("downloads", 0) < self.min_downloads:
                self.status.skipped += 1
                continue
            
            needs_update_flag = self.needs_update(mod_id, mod_data, existing_mods)
            has_missing_flag = await self.has_missing_data(mod_id) if self.fill_missing_data else False
            
            if not needs_update_flag and not has_missing_flag and not self.update_all_versions:
                self.status.skipped += 1
                continue
            
            mods_to_update[mod_id] = {
                "details": mod_data,
                "versions": mod_versions.get(mod_id, []),
                "update_reason": "changes" if needs_update_flag else "missing_data"
            }
        
        if mods_to_update:
            updated_count, filled_count, versions_added, versions_updated, deps_added = await self.save_mods_batch(mods_to_update)
            self.status.updated += updated_count
            self.status.filled += filled_count
            self.status.versions_added += versions_added
            self.status.versions_updated += versions_updated
            self.status.dependencies_added += deps_added
        
        if self.status.processed % 500 == 0:
            logger.info(
                f"Обработано: {self.status.processed}, Обновлено: {self.status.updated}, "
                f"Заполнено: {self.status.filled}, Пропущено: {self.status.skipped}, "
                f"Ошибок: {self.status.errors}, Версий добавлено: {self.status.versions_added}, "
                f"Зависимостей добавлено: {self.status.dependencies_added}"
            )
    
    async def save_mods_batch(self, mods_batch: Dict[str, Dict]) -> Tuple[int, int, int, int, int]:
        """Save a batch of mods and their dependencies to the PostgreSQL DB."""
        if not self.pool: raise ConnectionError("Database pool is not initialized.")

        updated_count, filled_count, versions_added, versions_updated, deps_added = 0, 0, 0, 0, 0
        
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                try:
                    for mod_id, mod_data in mods_batch.items():
                        details = mod_data["details"]
                        versions = mod_data["versions"]
                        update_reason = mod_data["update_reason"]
                        
                        license_info = details.get("license", {}).get("id", "") if isinstance(details.get("license"), dict) else details.get("license", "")
                        
                        await conn.execute('''
                            INSERT INTO mods (id, title, description, slug, downloads, updated_at, last_checked, categories, license, client_side, server_side)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                            ON CONFLICT (id) DO UPDATE SET
                                title = EXCLUDED.title, description = EXCLUDED.description, slug = EXCLUDED.slug,
                                downloads = EXCLUDED.downloads, updated_at = EXCLUDED.updated_at,
                                last_checked = EXCLUDED.last_checked, categories = EXCLUDED.categories,
                                license = EXCLUDED.license, client_side = EXCLUDED.client_side,
                                server_side = EXCLUDED.server_side
                        ''', 
                            details["id"], details["title"], details.get("description", ""), details["slug"],
                            details.get("downloads", 0), datetime.fromisoformat(details["updated"].replace('Z', '+00:00')),
                            datetime.now(), details.get("categories", []), license_info,
                            details.get("client_side", "unknown"), details.get("server_side", "unknown")
                        )

                        if self.update_all_versions:
                            existing_versions = await self.get_existing_versions(mod_id)
                            for version in versions:
                                primary_file = next((f for f in version["files"] if f["primary"]), version["files"][0] if version["files"] else None)
                                if not primary_file: continue

                                version_id = version["id"]
                                version_exists = version_id in existing_versions
                                
                                # Insert/update version WITHOUT dependencies column
                                await conn.execute('''
                                    INSERT INTO versions (id, mod_id, version_number, loaders, game_versions, download_url, filename, published_at, file_size, sha512_hash, changelog, version_type)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                                    ON CONFLICT (id) DO UPDATE SET
                                        version_number = EXCLUDED.version_number, loaders = EXCLUDED.loaders,
                                        game_versions = EXCLUDED.game_versions, download_url = EXCLUDED.download_url,
                                        filename = EXCLUDED.filename, published_at = EXCLUDED.published_at,
                                        file_size = EXCLUDED.file_size, sha512_hash = EXCLUDED.sha512_hash,
                                        changelog = EXCLUDED.changelog, version_type = EXCLUDED.version_type
                                ''',
                                    version_id, mod_id, version["version_number"], version["loaders"],
                                    version["game_versions"], primary_file["url"], primary_file["filename"],
                                    datetime.fromisoformat(version["date_published"].replace('Z', '+00:00')),
                                    primary_file.get("size", 0), primary_file.get("hashes", {}).get("sha512"),
                                    version.get("changelog", ""), version.get("version_type", "release")
                                )
                                if version_exists: versions_updated += 1
                                else: versions_added += 1

                                # NEW: Process dependencies for this version
                                # First, clear old dependencies to ensure data is fresh
                                await conn.execute("DELETE FROM dependencies WHERE version_id = $1", version_id)
                                
                                for dep in version.get("dependencies", []):
                                    await conn.execute('''
                                        INSERT INTO dependencies (version_id, project_id, version_id_ref, dependency_type, file_name)
                                        VALUES ($1, $2, $3, $4, $5)
                                    ''',
                                        version_id,
                                        dep.get("project_id"),
                                        dep.get("version_id"), # API `version_id` is our `version_id_ref`
                                        dep.get("dependency_type"),
                                        dep.get("file_name")
                                    )
                                    deps_added += 1

                        if update_reason == "missing_data": filled_count += 1
                        else: updated_count += 1
                except Exception as e:
                    logger.error(f"Ошибка во время транзакции сохранения данных: {e}")
                    raise # Rollback transaction
        return updated_count, filled_count, versions_added, versions_updated, deps_added

    async def fill_missing_data_async(self, session):
        """Fill missing data for mods that require it."""
        if not self.fill_missing_data: return
        
        logger.info("Запуск процесса заполнения неполных данных...")
        mods_with_missing_data = await self.get_mods_with_missing_data()
        if not mods_with_missing_data:
            logger.info("Моды с неполными данными не найдены.")
            return

        batch_size = 100
        for i in range(0, len(mods_with_missing_data), batch_size):
            batch_ids = mods_with_missing_data[i:i + batch_size]
            mod_details = await self.get_mod_details_batch(session, batch_ids)
            mod_versions = await self.get_mod_versions_batch(session, batch_ids) if self.update_all_versions else {}
            
            mods_to_update = {
                mod_id: {"details": mod_data, "versions": mod_versions.get(mod_id, []), "update_reason": "missing_data"}
                for mod_id, mod_data in mod_details.items()
            }
            
            if mods_to_update:
                _, filled_count, versions_added, _, deps_added = await self.save_mods_batch(mods_to_update)
                logger.info(
                    f"Заполнено данных для {filled_count} модов, добавлено {versions_added} версий, "
                    f"и {deps_added} зависимостей (батч {i//batch_size + 1})"
                )

    async def run_async(self):
        """Main asynchronous method to run the update."""
        start_time = time.time()
        logger.info(f"Запуск обновления модов: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            await self.init_pool()
            await self.init_database()
            
            existing_mods = await self.get_existing_mods()
            logger.info(f"В базе данных найдено {len(existing_mods)} модов.")
            
            connector = aiohttp.TCPConnector(limit=self.max_concurrent_requests, ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                all_mod_ids = await self.get_all_mod_ids(session)
                
                if not all_mod_ids:
                    logger.error("Не удалось получить список модов с Modrinth. Используем моды из БД.")
                    all_mod_ids = list(existing_mods.keys())

                logger.info(f"Всего модов для обработки: {len(all_mod_ids)}")
                
                batch_size = 100
                total_batches = (len(all_mod_ids) + batch_size - 1) // batch_size
                
                for i in range(0, len(all_mod_ids), batch_size):
                    batch_ids = all_mod_ids[i:i + batch_size]
                    current_batch_num = (i // batch_size) + 1
                    logger.info(f"Обработка батча {current_batch_num}/{total_batches}...")
                    
                    await self.process_mod_batch(session, batch_ids, existing_mods)
                    
                    elapsed = time.time() - start_time
                    progress_percent = (self.status.processed / len(all_mod_ids)) * 100 if len(all_mod_ids) > 0 else 0
                    if self.status.processed > 0:
                        mods_per_sec = self.status.processed / elapsed
                        remaining = len(all_mod_ids) - self.status.processed
                        eta = remaining / mods_per_sec if mods_per_sec > 0 else 0
                        logger.info(f"Прогресс: {self.status.processed}/{len(all_mod_ids)} ({progress_percent:.1f}%), "
                                   f"Скорость: {mods_per_sec:.2f} мод/сек, ETA: {eta/60:.1f} мин")

                await self.fill_missing_data_async(session)
            
            duration = time.time() - start_time
            logger.info("\nОбновление завершено!")
            logger.info(f"Затраченное время: {duration:.2f} секунд")
            
            async with self.pool.acquire() as conn:
                mods_count = await conn.fetchval("SELECT COUNT(*) FROM mods")
                versions_count = await conn.fetchval("SELECT COUNT(*) FROM versions")
                dependencies_count = await conn.fetchval("SELECT COUNT(*) FROM dependencies") # NEW
                
                logger.info(f"Итоговая статистика:")
                logger.info(f"  - Всего модов в БД: {mods_count}")
                logger.info(f"  - Всего версий в БД: {versions_count}")
                logger.info(f"  - Всего зависимостей в БД: {dependencies_count}") # NEW

        except Exception as e:
            logger.error(f"Во время выполнения произошла критическая ошибка: {e}")
        finally:
            await self.close_pool()

if __name__ == "__main__":
    API_TOKEN = os.getenv("MODRINTH_API_TOKEN")
    
    POSTGRES_CONFIG = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", 5432)),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME", "modrinth")
    }

    if not POSTGRES_CONFIG["password"]:
        raise ValueError("Переменная окружения DB_PASSWORD не установлена.")

    updater = ModUpdater(
        postgres_config=POSTGRES_CONFIG,
        api_token=API_TOKEN,
        max_concurrent_requests=50,
        force_update=False,
        min_downloads=1000,
        fill_missing_data=True,
        update_all_versions=True
    )
    
    asyncio.run(updater.run_async())