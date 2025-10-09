import aiohttp
import asyncio
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Set, Optional, Tuple
import json
import sys
from dataclasses import dataclass
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import asyncpg  # Добавляем импорт asyncpg для работы с PostgreSQL
from asyncpg.pool import Pool

# Настройка UTF-8 кодировки
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Настройка логирования
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

class RateLimiter:
    """Класс для интеллектуального ограничения частоты запросов"""
    def __init__(self, max_rate, time_window=60):
        self.max_rate = max_rate
        self.time_window = time_window
        self.requests = []
        self.lock = asyncio.Lock()
        
    async def acquire(self):
        async with self.lock:
            now = time.time()
            # Удаляем старые запросы вне временного окна
            self.requests = [t for t in self.requests if now - t < self.time_window]
            
            if len(self.requests) >= self.max_rate:
                # Вычисляем время ожидания
                oldest_request = self.requests[0]
                wait_time = self.time_window - (now - oldest_request)
                if wait_time > 0:
                    # Уменьшаем логирование для скорости
                    if wait_time > 2:  # Логируем только длительные ожидания
                        logger.info(f"Достигнут лимит запросов. Ждем {wait_time:.2f} секунд...")
                    await asyncio.sleep(wait_time)
                    now = time.time()
                    # Обновляем список запросов после ожидания
                    self.requests = [t for t in self.requests if now - t < self.time_window]
            
            # Добавляем текущий запрос
            self.requests.append(now)

class ModUpdater:
    def __init__(self, db_config: Dict, api_token: str = None, 
                 max_concurrent_requests: int = 50, force_update: bool = False,
                 min_downloads: int = 1000, fill_missing_data: bool = True,
                 update_all_versions: bool = True):
        self.db_config = db_config  # Конфигурация для PostgreSQL
        self.max_concurrent_requests = max_concurrent_requests
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.force_update = force_update
        self.min_downloads = min_downloads
        self.fill_missing_data = fill_missing_data
        self.update_all_versions = update_all_versions
        self.status = ModUpdateStatus()
        self.base_url = "https://api.modrinth.com/v2"
        self.pool: Optional[Pool] = None  # Пул соединений с PostgreSQL
        
        # Увеличиваем лимит запросов при наличии токена
        rate_limit = 290 if api_token else 100
        self.rate_limiter = RateLimiter(max_rate=rate_limit, time_window=60)
        
        # Настройка заголовков
        self.headers = {
            "User-Agent": "Modrinth-Updater/1.0 (contact@example.com)",
            "Accept": "application/json"
        }
        
        if api_token:
            self.headers["Authorization"] = api_token
            logger.info("API токен установлен, увеличен лимит запросов")
        else:
            logger.warning("API токен не предоставлен. Будут применяться стандартные лимиты запросов")
    
    async def init_database(self):
        """Инициализация структуры базы данных PostgreSQL"""
        self.pool = await asyncpg.create_pool(**self.db_config)
        
        async with self.pool.acquire() as conn:
            # Таблица модов
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS mods (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    slug TEXT UNIQUE,
                    downloads INTEGER DEFAULT 0,
                    updated_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    last_checked TIMESTAMP WITH TIME ZONE,
                    categories TEXT[],
                    license TEXT,
                    client_side TEXT,
                    server_side TEXT
                )
            ''')
            
            # Таблица версий
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS versions (
                    id TEXT PRIMARY KEY,
                    mod_id TEXT NOT NULL REFERENCES mods(id) ON DELETE CASCADE,
                    version_number TEXT NOT NULL,
                    loaders TEXT[] NOT NULL,
                    game_versions TEXT[] NOT NULL,
                    download_url TEXT NOT NULL,
                    filename TEXT,
                    published_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    file_size INTEGER,
                    sha512_hash TEXT,
                    dependencies JSONB,
                    changelog TEXT,
                    version_type TEXT
                )
            ''')
            
            # Индексы
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_mods_downloads ON mods(downloads)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_versions_game ON versions USING GIN(game_versions)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_versions_loaders ON versions USING GIN(loaders)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_mods_last_checked ON mods(last_checked)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_mods_updated ON mods(updated_at)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_versions_mod ON versions(mod_id)')
    
    async def get_existing_mods(self) -> Dict[str, datetime]:
        """Получаем список существующих модов и время их последнего обновления"""
        existing_mods = {}
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("SELECT id, updated_at FROM mods")
                
                for row in rows:
                    mod_id, updated_at = row['id'], row['updated_at']
                    if updated_at:
                        existing_mods[mod_id] = updated_at
                    else:
                        existing_mods[mod_id] = datetime.min
            
        except Exception as e:
            logger.error(f"Ошибка при получении списка существующих модов: {e}")
            existing_mods = {}
        
        return existing_mods
    
    async def get_existing_versions(self, mod_id: str) -> Set[str]:
        """Получаем список существующих версий для мода"""
        existing_versions = set()
        
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch("SELECT id FROM versions WHERE mod_id = $1", mod_id)
                
                for row in rows:
                    existing_versions.add(row['id'])
                    
        except Exception as e:
            logger.error(f"Ошибка при получении списка версий для мода {mod_id}: {e}")
        
        return existing_versions
    
    async def get_mods_with_missing_data(self) -> List[str]:
        """Получаем список модов с пропущенными данными"""
        mod_ids = []
        
        try:
            async with self.pool.acquire() as conn:
                # Определяем поля, которые должны быть заполнены
                query = """
                    SELECT id FROM mods 
                    WHERE (
                        description IS NULL OR description = '' OR
                        categories IS NULL OR array_length(categories, 1) IS NULL OR
                        license IS NULL OR license = '' OR
                        client_side = 'unknown' OR
                        server_side = 'unknown' OR
                        downloads = 0
                    )
                """
                
                rows = await conn.fetch(query)
                mod_ids = [row['id'] for row in rows]
                
        except Exception as e:
            logger.error(f"Ошибка при получении списка модов с пропущенными данными: {e}")
        
        logger.info(f"Найдено {len(mod_ids)} модов с пропущенными данными")
        return mod_ids
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError, aiohttp.ServerDisconnectedError))
    )
    async def make_async_request(self, session, url, params=None):
        """Асинхронный запрос с повторными попытками и ограничением частоты"""
        params = params or {}
        
        await self.rate_limiter.acquire()
        
        async with self.semaphore:
            try:
                async with session.get(url, params=params, headers=self.headers, 
                                      timeout=aiohttp.ClientTimeout(total=30)) as response:
                    
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 5))
                        logger.warning(f"Достигнут лимит запросов. Ждем {retry_after} секунд...")
                        await asyncio.sleep(retry_after)
                        raise aiohttp.ClientResponseError(
                            request_info=response.request_info,
                            history=response.history,
                            status=429,
                            message=f"Rate limit exceeded, retry after {retry_after} seconds",
                            headers=response.headers
                        )
                    
                    if response.status >= 400:
                        error_text = await response.text()
                        logger.error(f"Ошибка HTTP {response.status}: {error_text}")
                        response.raise_for_status()
                    
                    return await response.json()
                    
            except asyncio.TimeoutError:
                logger.warning(f"Таймаут при запросе к {url}")
                raise
            except aiohttp.ClientError as e:
                logger.warning(f"Ошибка клиента при запросе к {url}: {e}")
                raise
            except Exception as e:
                logger.error(f"Неожиданная ошибка при запросе к {url}: {e}")
                raise
    
    async def get_all_mod_ids(self, session) -> List[str]:
        """Получаем все ID модов с Modrinth, отфильтрованные по min_downloads"""
        all_mods = []
        limit = 100
        offset = 0
        
        logger.info("Получение списка популярных модов...")
        
        while True:
            params = {"limit": limit, "offset": offset, "index": "downloads"}
            
            data = await self.make_async_request(session, f"{self.base_url}/search", params)
            
            if not data or "hits" not in data:
                break
            
            # Фильтруем моды по минимальному количеству загрузок
            page_mods = [mod for mod in data["hits"] if mod.get("downloads", 0) >= self.min_downloads]
            if not page_mods:
                break
                
            all_mods.extend(page_mods)
            
            if len(data["hits"]) < limit:
                break
                
            offset += limit
            # Небольшая пауза между запросами
            await asyncio.sleep(0.1)
        
        # Извлекаем только ID модов
        mod_ids = [mod["project_id"] for mod in all_mods]
        logger.info(f"Всего получено {len(mod_ids)} модов с ≥{self.min_downloads} загрузок")
        return mod_ids
    
    async def get_mod_details_batch(self, session, mod_ids: List[str]) -> Dict[str, Dict]:
        """Получаем детали для батча модов"""
        if not mod_ids:
            return {}
        
        try:
            batch_size = 50
            all_details = {}
            
            for i in range(0, len(mod_ids), batch_size):
                batch = mod_ids[i:i + batch_size]
                ids_param = json.dumps(batch)
                
                data = await self.make_async_request(
                    session,
                    f"{self.base_url}/projects",
                    params={"ids": ids_param}
                )
                
                if data:
                    all_details.update({mod["id"]: mod for mod in data if mod is not None})
            
            return all_details
        except Exception as e:
            logger.error(f"Ошибка при получении деталей модов: {e}")
            return {}
    
    async def get_all_mod_versions(self, session, mod_id: str) -> List[Dict]:
        """Получаем все версии мода с пагинацией"""
        all_versions = []
        limit = 100
        offset = 0
        
        while True:
            params = {"limit": limit, "offset": offset}
            data = await self.make_async_request(
                session,
                f"{self.base_url}/project/{mod_id}/version",
                params
            )
            
            if not data:
                break
                
            all_versions.extend(data)
            
            if len(data) < limit:
                break
                
            offset += limit
            await asyncio.sleep(0.1)  # Небольшая пауза между запросами
        
        return all_versions
    
    async def get_mod_versions_batch(self, session, mod_ids: List[str]) -> Dict[str, List]:
        """Получаем версии для батча модов"""
        if not mod_ids:
            return {}
        
        try:
            all_versions = {}
            
            # Создаем задачи для получения версий каждого мода
            tasks = []
            for mod_id in mod_ids:
                task = asyncio.create_task(self.get_all_mod_versions(session, mod_id))
                tasks.append((mod_id, task))
            
            # Ожидаем завершения всех задач
            for mod_id, task in tasks:
                try:
                    versions = await task
                    all_versions[mod_id] = versions
                    logger.debug(f"Получено {len(versions)} версий для мода {mod_id}")
                except Exception as e:
                    logger.error(f"Ошибка при получении версий для мода {mod_id}: {e}")
                    all_versions[mod_id] = []
            
            return all_versions
        except Exception as e:
            logger.error(f"Ошибка при получении версий модов: {e}")
            return {}
    
    def needs_update(self, mod_id: str, mod_data: Dict, existing_mods: Dict[str, datetime]) -> bool:
        """Проверяем, нужно ли обновлять мод"""
        if self.force_update:
            return True
        
        if mod_id not in existing_mods:
            return True
        
        if "updated" in mod_data:
            try:
                api_updated_str = mod_data["updated"].replace('Z', '+00:00')
                api_updated = datetime.fromisoformat(api_updated_str)
                db_updated = existing_mods[mod_id]
                return api_updated > db_updated
            except (ValueError, TypeError):
                return False
        
        return False
    
    async def has_missing_data(self, mod_id: str) -> bool:
        """Проверяет, есть ли у мода пропущенные данные"""
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT description, categories, license, client_side, server_side, downloads
                    FROM mods WHERE id = $1
                """, mod_id)
                
                if not row:
                    return True
                
                # Проверяем наличие NULL или пустых значений
                for key, value in row.items():
                    if value is None or value == '' or value == 'unknown' or value == 0:
                        return True
                
                return False
        except Exception as e:
            logger.error(f"Ошибка при проверке пропущенных данных для мода {mod_id}: {e}")
            return True
    
    async def process_mod_batch(self, session, mod_ids: List[str], existing_mods: Dict[str, datetime]):
        """Обрабатываем батч модов"""
        mod_details = await self.get_mod_details_batch(session, mod_ids)
        
        # Получаем версии только если включено обновление версий
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
            
            # Проверяем, нужно ли обновить мод из-за изменений или пропущенных данных
            needs_update = self.needs_update(mod_id, mod_data, existing_mods)
            has_missing = await self.has_missing_data(mod_id) if self.fill_missing_data else False
            
            if not needs_update and not has_missing and not self.update_all_versions:
                self.status.skipped += 1
                continue
            
            mods_to_update[mod_id] = {
                "details": mod_data,
                "versions": mod_versions.get(mod_id, []),
                "update_reason": "changes" if needs_update else "missing_data"
            }
        
        if mods_to_update:
            updated_count, filled_count, versions_added, versions_updated = await self.save_mods_batch(mods_to_update)
            self.status.updated += updated_count
            self.status.filled += filled_count
            self.status.versions_added += versions_added
            self.status.versions_updated += versions_updated
        
        # Логируем прогресс
        if self.status.processed % 500 == 0:
            logger.info(
                f"Обработано: {self.status.processed}, "
                f"Обновлено: {self.status.updated}, "
                f"Заполнено: {self.status.filled}, "
                f"Пропущено: {self.status.skipped}, "
                f"Ошибок: {self.status.errors}, "
                f"Версий добавлено: {self.status.versions_added}, "
                f"Версий обновлено: {self.status.versions_updated}"
            )
    
    async def save_mods_batch(self, mods_batch: Dict[str, Dict]) -> Tuple[int, int, int, int]:
        """Сохраняем батч модов в БД и возвращаем количество обновленных, заполненных, добавленных и обновленных версий"""
        updated_count = 0
        filled_count = 0
        versions_added = 0
        versions_updated = 0
        
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    for mod_id, mod_data in mods_batch.items():
                        details = mod_data["details"]
                        versions = mod_data["versions"]
                        update_reason = mod_data["update_reason"]
                        
                        # Для заполнения пропущенных данных: сначала получаем текущие значения
                        current_values = {}
                        if update_reason == "missing_data":
                            row = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
                            if row:
                                current_values = dict(row)
                        
                        # Подготавливаем данные
                        categories = details.get("categories", [])
                        license_info = details.get("license", {}).get("id", "") if isinstance(details.get("license"), dict) else details.get("license", "")
                        client_side = details.get("client_side", "unknown")
                        server_side = details.get("server_side", "unknown")
                        current_time = datetime.now()
                        
                        # Преобразуем строку даты в объект datetime
                        updated_at_str = details.get("updated")
                        updated_at = current_time  # значение по умолчанию
                        
                        if updated_at_str:
                            try:
                                # Убираем 'Z' в конце и добавляем информацию о временной зоне
                                if updated_at_str.endswith('Z'):
                                    updated_at_str = updated_at_str[:-1] + '+00:00'
                                updated_at = datetime.fromisoformat(updated_at_str)
                            except (ValueError, TypeError):
                                logger.warning(f"Не удалось распарсить дату обновления для мода {mod_id}: {updated_at_str}")
                                updated_at = current_time
                        
                        # Для заполнения пропущенных данных: используем текущие значения, если новые недоступны
                        if update_reason == "missing_data":
                            description = details.get("description", "") or current_values.get("description", "")
                            categories = categories or current_values.get("categories", [])
                            license_info = license_info or current_values.get("license", "")
                            client_side = client_side if client_side != "unknown" else current_values.get("client_side", "unknown")
                            server_side = server_side if server_side != "unknown" else current_values.get("server_side", "unknown")
                            downloads = details.get("downloads", 0) or current_values.get("downloads", 0)
                        else:
                            description = details.get("description", "")
                            downloads = details.get("downloads", 0)
                        
                        # Обновляем или добавляем мод
                        mod_params = (
                            details["id"],
                            details["title"],
                            description,
                            details["slug"],
                            downloads,
                            updated_at,  # Используем преобразованный объект datetime
                            current_time,
                            categories,
                            license_info,
                            client_side,
                            server_side
                        )
                        
                        await conn.execute('''
                            INSERT INTO mods 
                            (id, title, description, slug, downloads, updated_at, last_checked, categories, license, client_side, server_side)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                            ON CONFLICT (id) DO UPDATE SET
                                title = EXCLUDED.title,
                                description = EXCLUDED.description,
                                slug = EXCLUDED.slug,
                                downloads = EXCLUDED.downloads,
                                updated_at = EXCLUDED.updated_at,
                                last_checked = EXCLUDED.last_checked,
                                categories = EXCLUDED.categories,
                                license = EXCLUDED.license,
                                client_side = EXCLUDED.client_side,
                                server_side = EXCLUDED.server_side
                        ''', *mod_params)
                        
                        # Получаем существующие версии для этого мода
                        existing_versions = await self.get_existing_versions(mod_id) if self.update_all_versions else set()
                        
                        # Обрабатываем версии
                        for version in versions:
                            # Находим основной файл
                            primary_file = next(
                                (f for f in version["files"] if f["primary"]), 
                                version["files"][0] if version["files"] else {}
                            )
                            
                            if not primary_file:
                                continue
                            
                            # Преобразуем строку даты публикации в объект datetime
                            published_at_str = version.get("date_published")
                            published_at = None
                            
                            if published_at_str:
                                try:
                                    # Убираем 'Z' в конце и добавляем информацию о временной зоне
                                    if published_at_str.endswith('Z'):
                                        published_at_str = published_at_str[:-1] + '+00:00'
                                    published_at = datetime.fromisoformat(published_at_str)
                                except (ValueError, TypeError):
                                    logger.warning(f"Не удалось распарсить дату публикации для версии {version['id']}: {published_at_str}")
                                    published_at = None
                            
                            # Подготавливаем данные версии
                            file_size = primary_file.get("size", 0)
                            sha512_hash = primary_file.get("hashes", {}).get("sha512", "")
                            dependencies = version.get("dependencies", [])
                            changelog = version.get("changelog", "")
                            version_type = version.get("version_type", "release")
                            
                            # Проверяем, существует ли уже эта версия
                            version_exists = version["id"] in existing_versions
                            
                            # Вставляем или обновляем версию
                            version_params = (
                                version["id"],
                                details["id"],
                                version["version_number"],
                                version["loaders"],
                                version["game_versions"],
                                primary_file["url"],
                                primary_file["filename"],
                                published_at,  # Используем преобразованный объект datetime или None
                                file_size,
                                sha512_hash,
                                dependencies,
                                changelog,
                                version_type
                            )
                            
                            await conn.execute('''
                                INSERT INTO versions 
                                (id, mod_id, version_number, loaders, game_versions, download_url, filename, published_at, file_size, sha512_hash, dependencies, changelog, version_type)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                                ON CONFLICT (id) DO UPDATE SET
                                    version_number = EXCLUDED.version_number,
                                    loaders = EXCLUDED.loaders,
                                    game_versions = EXCLUDED.game_versions,
                                    download_url = EXCLUDED.download_url,
                                    filename = EXCLUDED.filename,
                                    published_at = EXCLUDED.published_at,
                                    file_size = EXCLUDED.file_size,
                                    sha512_hash = EXCLUDED.sha512_hash,
                                    dependencies = EXCLUDED.dependencies,
                                    changelog = EXCLUDED.changelog,
                                    version_type = EXCLUDED.version_type
                            ''', *version_params)
                            
                            # Обновляем счетчики версий
                            if version_exists:
                                versions_updated += 1
                            else:
                                versions_added += 1
                        
                        if update_reason == "missing_data":
                            filled_count += 1
                        else:
                            updated_count += 1
                    
        except Exception as e:
            logger.error(f"Ошибка при сохранении батча модов: {e}", exc_info=True)
        
        return updated_count, filled_count, versions_added, versions_updated
    
    async def fill_missing_data(self, session):
        """Заполняет пропущенные данные для модов, у которых они отсутствуют"""
        if not self.fill_missing_data:
            return
        
        logger.info("Запуск процесса заполнения пропущенных данных...")
        
        # Получаем моды с пропущенными данными
        mods_with_missing_data = await self.get_mods_with_missing_data()
        
        if not mods_with_missing_data:
            logger.info("Не найдено модов с пропущенными данными")
            return
        
        # Обрабатываем моды с пропущенными данными большими батчами
        batch_size = 100
        for i in range(0, len(mods_with_missing_data), batch_size):
            batch_ids = mods_with_missing_data[i:i + batch_size]
            
            # Получаем детали и версии для этих модов
            mod_details = await self.get_mod_details_batch(session, batch_ids)
            
            # Получаем версии только если включено обновление версий
            mod_versions = {}
            if self.update_all_versions:
                mod_versions = await self.get_mod_versions_batch(session, batch_ids)
            
            # Обрабатываем моды с пропущенными данными
            mods_to_update = {}
            for mod_id in batch_ids:
                if mod_id not in mod_details:
                    continue
                
                mod_data = mod_details[mod_id]
                
                mods_to_update[mod_id] = {
                    "details": mod_data,
                    "versions": mod_versions.get(mod_id, []),
                    "update_reason": "missing_data"
                }
            
            if mods_to_update:
                updated_count, filled_count, versions_added, versions_updated = await self.save_mods_batch(mods_to_update)
                logger.info(f"Заполнено пропущенных данных для {filled_count} модов, "
                           f"добавлено {versions_added} версий, "
                           f"обновлено {versions_updated} версий (батч {i//batch_size + 1})")
    
    async def run_async(self):
        """Основной асинхронный метод запуска обновления"""
        start_time = time.time()
        logger.info(f"Запуск обновления модов в {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Минимальное количество загрузок: {self.min_downloads}")
        logger.info(f"Принудительное обновление: {'Включено' if self.force_update else 'Отключено'}")
        logger.info(f"Заполнение пропущенных данных: {'Включено' if self.fill_missing_data else 'Отключено'}")
        logger.info(f"Обновление всех версий: {'Включено' if self.update_all_versions else 'Отключено'}")
        logger.info(f"Максимальное количество одновременных запросов: {self.max_concurrent_requests}")
        
        # Инициализируем базу данных
        await self.init_database()
        
        # Получаем список существующих модов
        existing_mods = await self.get_existing_mods()
        
        # Проверяем, что existing_mods не None
        if existing_mods is None:
            logger.warning("Не удалось получить список существующих модов, используем пустой словарь")
            existing_mods = {}
        
        logger.info(f"В базе найдено {len(existing_mods)} модов")
        
        connector = aiohttp.TCPConnector(limit=self.max_concurrent_requests, ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Получаем все актуальные ID модов с Modrinth
            all_mod_ids = await self.get_all_mod_ids(session)
            
            if not all_mod_ids:
                logger.error("Не удалось получить список модов с Modrinth. Пробуем альтернативный подход...")
                
                # Альтернативный подход: используем существующие моды из базы
                all_mod_ids = list(existing_mods.keys())
                logger.info(f"Используем {len(all_mod_ids)} модов из базы данных")
            
            logger.info(f"Всего модов для обработки: {len(all_mod_ids)}")
            
            # Обрабатываем моды большими батчами
            batch_size = 100
            total_batches = (len(all_mod_ids) + batch_size - 1) // batch_size
            
            for batch_num in range(0, len(all_mod_ids), batch_size):
                batch_ids = all_mod_ids[batch_num:batch_num + batch_size]
                current_batch = (batch_num // batch_size) + 1
                
                # Логируем начало обработки батча
                logger.info(f"Обработка батча {current_batch}/{total_batches} "
                           f"(моды {batch_num}-{min(batch_num + batch_size, len(all_mod_ids))})")
                
                await self.process_mod_batch(session, batch_ids, existing_mods)
                
                # Вычисляем прогресс и ETA
                elapsed_time = time.time() - start_time
                processed_mods = self.status.processed
                progress_percent = (processed_mods / len(all_mod_ids)) * 100
                
                if processed_mods > 0:
                    mods_per_second = processed_mods / elapsed_time
                    remaining_mods = len(all_mod_ids) - processed_mods
                    eta_seconds = remaining_mods / mods_per_second if mods_per_second > 0 else 0
                    
                    logger.info(f"Прогресс: {processed_mods}/{len(all_mod_ids)} модов "
                               f"({progress_percent:.1f}%), "
                               f"Скорость: {mods_per_second:.2f} модов/сек, "
                               f"ETA: {eta_seconds/60:.1f} мин")
                
                # Небольшая пауза между батчами
                await asyncio.sleep(0.5)
            
            # Заполняем пропущенные данные для модов, которые не обновлялись
            await self.fill_missing_data(session)
        
        # Закрываем пул соединений
        await self.pool.close()
        
        # Выводим итоговую статистику
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info(f"\nОбновление завершено!")
        logger.info(f"Обработано модов: {self.status.processed}")
        logger.info(f"Обновлено модов: {self.status.updated}")
        logger.info(f"Заполнено пропусков: {self.status.filled}")
        logger.info(f"Пропущено модов: {self.status.skipped}")
        logger.info(f"Ошибок: {self.status.errors}")
        logger.info(f"Версий добавлено: {self.status.versions_added}")
        logger.info(f"Версий обновлено: {self.status.versions_updated}")
        logger.info(f"Затраченное время: {duration:.2f} секунд")
        
        if duration > 0:
            logger.info(f"Скорость: {self.status.processed / duration:.2f} модов/секунду")
        
        # Статистика базы данных
        async with self.pool.acquire() as conn:
            mods_count = await conn.fetchval("SELECT COUNT(*) FROM mods")
            versions_count = await conn.fetchval("SELECT COUNT(*) FROM versions")
            
            # Проверяем полноту данных
            mods_with_missing_data = await conn.fetchval("""
                SELECT COUNT(*) FROM mods 
                WHERE (
                    description IS NULL OR description = '' OR
                    categories IS NULL OR array_length(categories, 1) IS NULL OR
                    license IS NULL OR license = '' OR
                    client_side = 'unknown' OR
                    server_side = 'unknown' OR
                    downloads = 0
                )
            """)
        
        logger.info(f"Всего модов в базе: {mods_count}")
        logger.info(f"Всего версий в базе: {versions_count}")
        logger.info(f"Модов с пропущенными данными: {mods_with_missing_data}")

# Запуск обновления
if __name__ == "__main__":
    # Конфигурация PostgreSQL
    POSTGRES_CONFIG = {
        "host": "localhost",
        "port": 5432,
        "user": "postgres",
        "password": "20088002",
        "database": "MineCollection"
    }
    
    # Ваш API-токен Modrinth
    API_TOKEN = "mrp_oZGKmhb6bISFT6Lw38u00edVh5QmAxp4gwv2qk73QEIeRHPiCtS9zNe50LnH"
    
    updater = ModUpdater(
        db_config=POSTGRES_CONFIG,
        api_token=API_TOKEN,
        max_concurrent_requests=50,
        force_update=True,
        min_downloads=1000000,
        fill_missing_data=True,
        update_all_versions=True
    )
    
    # Запускаем асинхронное обновление
    asyncio.run(updater.run_async())