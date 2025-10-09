import sqlite3
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging
import random
import json

from requests import session
import timedelta

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Попробуем импортировать aiohttp, и если не получится, предложим установить
try:
    import aiohttp
    import asyncio
except ImportError:
    logger.error("Библиотека aiohttp не установлена. Установите её командой: pip install aiohttp")
    exit(1)

class RateLimiter:
    """Класс для интеллектуального ограничения частоты запросов"""
    def __init__(self, max_rate, time_window=60):
        self.max_rate = max_rate  # Максимальное количество запросов
        self.time_window = time_window  # Временное окно в секундах
        self.requests = []  # Временные метки последних запросов
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
                    logger.info(f"Достигнут лимит запросов. Ждем {wait_time:.2f} секунд...")
                    await asyncio.sleep(wait_time)
                    now = time.time()
                    # Обновляем список запросов после ожидания
                    self.requests = [t for t in self.requests if now - t < self.time_window]
            
            # Добавляем текущий запрос
            self.requests.append(now)
            # Сортируем для правильного вычисления следующего ожидания
            self.requests.sort()

class ModrinthParser:
    def __init__(self, db_path: str = "modrinth.db", min_downloads: int = 1000, 
                max_concurrent_requests: int = 30, api_token: str = None,
                skip_existing: bool = True, min_versions: int = 0):
        self.db_path = db_path
        self.min_downloads = min_downloads
        self.min_versions = min_versions  # Новый параметр
        self.base_url = "https://api.modrinth.com/v2"
        self.max_concurrent_requests = max_concurrent_requests
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.skip_existing = skip_existing
        
        # Инициализируем ограничитель запросов (300 в минуту с токеном)
        self.rate_limiter = RateLimiter(max_rate=290, time_window=60)
        
        # Настройка заголовков
        self.headers = {
            "User-Agent": "Modrinth-Parser/1.0 (https://github.com/yourusername/modrinth-parser)",
            "Accept": "application/json"
        }
        
        if api_token:
            self.headers["Authorization"] = api_token
            logger.info("API-токен Modrinth добавлен в заголовки запросов")
        
        # Инициализация БД
        self.init_database()
    
    def init_database(self):
        """Инициализация структуры базы данных с добавлением столбцов для категорий и зависимостей"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Таблица модов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mods (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                slug TEXT UNIQUE,
                downloads INTEGER DEFAULT 0,
                updated_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_checked TEXT
            )
        ''')
        
        # Таблица версий
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS versions (
                id TEXT PRIMARY KEY,
                mod_id TEXT NOT NULL,
                version_number TEXT NOT NULL,
                loaders TEXT NOT NULL,
                game_versions TEXT NOT NULL,
                download_url TEXT NOT NULL,
                filename TEXT,
                published_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (mod_id) REFERENCES mods (id) ON DELETE CASCADE
            )
        ''')
        
        # Проверяем и добавляем отсутствующие столбцы в таблицу mods
        cursor.execute("PRAGMA table_info(mods)")
        existing_columns = [column[1] for column in cursor.fetchall()]
        
        # Добавляем отсутствующие столбцы в mods
        if 'categories' not in existing_columns:
            cursor.execute("ALTER TABLE mods ADD COLUMN categories TEXT")
        if 'license' not in existing_columns:
            cursor.execute("ALTER TABLE mods ADD COLUMN license TEXT")
        if 'client_side' not in existing_columns:
            cursor.execute("ALTER TABLE mods ADD COLUMN client_side TEXT")
        if 'server_side' not in existing_columns:
            cursor.execute("ALTER TABLE mods ADD COLUMN server_side TEXT")
        
        # Проверяем и добавляем отсутствующие столбцы в таблицу versions
        cursor.execute("PRAGMA table_info(versions)")
        existing_columns = [column[1] for column in cursor.fetchall()]
        
        # Добавляем отсутствующие столбцы в versions
        if 'file_size' not in existing_columns:
            cursor.execute("ALTER TABLE versions ADD COLUMN file_size INTEGER")
        if 'sha512_hash' not in existing_columns:
            cursor.execute("ALTER TABLE versions ADD COLUMN sha512_hash TEXT")
        if 'dependencies' not in existing_columns:
            cursor.execute("ALTER TABLE versions ADD COLUMN dependencies TEXT")
        if 'changelog' not in existing_columns:
            cursor.execute("ALTER TABLE versions ADD COLUMN changelog TEXT")
        if 'version_type' not in existing_columns:
            cursor.execute("ALTER TABLE versions ADD COLUMN version_type TEXT")
        
        # Таблица зависимостей (для нормализации)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dependencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id TEXT NOT NULL,
                project_id TEXT,
                version_id_ref TEXT,
                dependency_type TEXT,
                file_name TEXT,
                FOREIGN KEY (version_id) REFERENCES versions (id) ON DELETE CASCADE
            )
        ''')
        
        # Индексы для ускорения поиска
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_mods_downloads ON mods(downloads)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_versions_game ON versions(game_versions)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_versions_loaders ON versions(loaders)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_mods_last_checked ON mods(last_checked)')
        
        # Создаем индекс для categories только если столбец существует
        cursor.execute("PRAGMA table_info(mods)")
        mods_columns = [column[1] for column in cursor.fetchall()]
        if 'categories' in mods_columns:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_mods_categories ON mods(categories)')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_dependencies_version ON dependencies(version_id)')
        
        conn.commit()
        conn.close()
    
    def get_existing_mod_ids(self):
        """Получаем список ID модов, которые уже есть в базе"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM mods")
        existing_ids = {row[0] for row in cursor.fetchall()}
        conn.close()
        return existing_ids
    
    async def make_async_request(self, session, url, params=None, max_retries=50):
        """Асинхронный запрос с повторными попытками и ограничением частоты"""
        params = params or {}
        
        for attempt in range(max_retries):
            try:
                # Применяем ограничение частоты запросов
                await self.rate_limiter.acquire()
                
                async with self.semaphore:
                    async with session.get(url, params=params, headers=self.headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                        
                        if response.status == 429:
                            retry_after = int(response.headers.get('Retry-After', 10))
                            logger.warning(f"Достигнут лимит запросов. Ждем {retry_after} секунд...")
                            await asyncio.sleep(retry_after)
                            continue
                            
                        response.raise_for_status()
                        return await response.json()
                        
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"Попытка {attempt+1}/{max_retries} не удалась для {url}: {e}")
                if attempt < max_retries - 1:
                    # Добавляем случайную задержку для избежания синхронизации запросов
                    delay = 2 * (attempt + 1) + random.uniform(0, 1)
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Все попытки не удались для {url}")
                    return None
        return None

    async def fetch_popular_mods(self, session):
        """Асинхронное получение списка популярных модов с фильтрацией по минимальному количеству версий"""
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
            
            # Дополнительно фильтруем по минимальному количеству версий, если указано
            if self.min_versions > 0:
                filtered_mods = []
                for mod in page_mods:
                    # Получаем количество версий из данных API
                    versions_count = mod.get("versions", [])
                    if len(versions_count) >= self.min_versions:
                        filtered_mods.append(mod)
                page_mods = filtered_mods
            
            if not page_mods:
                break
                
            all_mods.extend(page_mods)
            logger.info(f"Offset {offset}: Получено {len(page_mods)} модов (Всего: {len(all_mods)})")
            
            if len(data["hits"]) < limit:
                break
                
            offset += limit
            # Увеличиваем задержку по мере роста offset
            delay = min(2.0, 0.5 + (offset / 1000) * 0.1)
            await asyncio.sleep(delay)
        
        return all_mods

    async def fetch_all_mod_versions(self, session, mod_id):
        """Асинхронное получение ВСЕХ версий мода с поддержкой пагинации"""
        all_versions = []
        limit = 100
        offset = 0
        
        while True:
            params = {"limit": limit, "offset": offset}
            
            data = await self.make_async_request(session, f"{self.base_url}/project/{mod_id}/version", params)
            
            if not data:
                break
            
            all_versions.extend(data)
            
            # Если получено меньше версий, чем запрошено, значит это последняя страница
            if len(data) < limit:
                break
                
            offset += limit
            # Небольшая задержка между запросами
            await asyncio.sleep(0.1)
        
        return all_versions

    async def fetch_mod_details(self, session, mod_id):
        """Асинхронное получение деталей мода"""
        return await self.make_async_request(session, f"{self.base_url}/project/{mod_id}")

    async def fetch_mod_versions(self, session, mod_id):
        """Асинхронное получение версий мода"""
        return await self.make_async_request(session, f"{self.base_url}/project/{mod_id}/version")

    async def process_single_mod(self, session, mod_info):
        """Асинхронная обработка одного мода"""
        mod_id, mod_data = mod_info
        
        # Если включен пропуск существующих модов и мод уже есть в базе - пропускаем
        if self.skip_existing and mod_id in self.existing_mod_ids:
            return {'mod_id': mod_id, 'mod_details': None, 'versions': None, 'error': "Уже существует в базе, пропускаем"}
        
        result = {'mod_id': mod_id, 'mod_details': None, 'versions': None, 'error': None}
        
        try:
            # Параллельно запрашиваем детали и ВСЕ версии
            details_task = self.fetch_mod_details(session, mod_id)
            versions_task = self.fetch_all_mod_versions(session, mod_id)  # Используем новую функцию
            
            mod_details, versions = await asyncio.gather(details_task, versions_task)
            
            if not mod_details:
                result['error'] = f"Не удалось получить детали для мода {mod_id}"
                return result
            if not versions:
                result['error'] = f"Не удалось получить версии для мода {mod_id}"
                return result
                
            result['mod_details'] = mod_details
            result['versions'] = versions
            
        except Exception as e:
            result['error'] = f"Ошибка при обработке мода {mod_id}: {e}"
        
        return result

    def save_mods_batch(self, results):
        """Синхронное сохранение батча результатов в БД"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        successful = 0
        skipped = 0
        
        try:
            # Получаем информацию о столбцах таблицы versions
            cursor.execute("PRAGMA table_info(versions)")
            versions_columns = [column[1] for column in cursor.fetchall()]
            
            for result in results:
                if result['error']:
                    if "Уже существует в базе" in result['error']:
                        skipped += 1
                    else:
                        logger.error(result['error'])
                    continue
                
                mod_data = result['mod_details']
                versions = result['versions']
            
                # Логируем информацию о количестве версий
                logger.info(f"Обработка мода {mod_data['title']} с {len(versions)} версиями")
                
                # Извлекаем категории, лицензию и информацию о поддержке клиент/сервер
                categories = ",".join(mod_data.get("categories", []))
                license_info = mod_data.get("license", {}).get("id", "") if isinstance(mod_data.get("license"), dict) else mod_data.get("license", "")
                client_side = mod_data.get("client_side", "unknown")
                server_side = mod_data.get("server_side", "unknown")
                
                # Проверяем, существует ли уже мод
                cursor.execute("SELECT id FROM mods WHERE id = ?", (mod_data["id"],))
                mod_exists = cursor.fetchone() is not None
                
                if mod_exists:
                    # Обновляем существующий мод
                    update_sql = '''
                        UPDATE mods 
                        SET title = ?, description = ?, slug = ?, downloads = ?, 
                            updated_at = ?, last_checked = ?
                    '''
                    params = [
                        mod_data["title"],
                        mod_data.get("description", ""),
                        mod_data["slug"],
                        mod_data.get("downloads", 0),
                        mod_data.get("updated", datetime.now().isoformat()),
                        datetime.now().isoformat(),
                    ]
                    
                    # Добавляем новые столбцы, если они существуют
                    if 'categories' in versions_columns:
                        update_sql += ', categories = ?'
                        params.append(categories)
                    if 'license' in versions_columns:
                        update_sql += ', license = ?'
                        params.append(license_info)
                    if 'client_side' in versions_columns:
                        update_sql += ', client_side = ?'
                        params.append(client_side)
                    if 'server_side' in versions_columns:
                        update_sql += ', server_side = ?'
                        params.append(server_side)
                        
                    update_sql += ' WHERE id = ?'
                    params.append(mod_data["id"])
                    cursor.execute(update_sql, params)
                else:
                    # Добавляем новый мод
                    insert_sql = '''
                        INSERT INTO mods 
                        (id, title, description, slug, downloads, updated_at, last_checked
                    '''
                    values_sql = 'VALUES (?, ?, ?, ?, ?, ?, ?'
                    params = [
                        mod_data["id"],
                        mod_data["title"],
                        mod_data.get("description", ""),
                        mod_data["slug"],
                        mod_data.get("downloads", 0),
                        mod_data.get("updated", datetime.now().isoformat()),
                        datetime.now().isoformat()
                    ]
                    
                    # Добавляем новые столбцы, если они существуют
                    if 'categories' in versions_columns:
                        insert_sql += ', categories'
                        values_sql += ', ?'
                        params.append(categories)
                    if 'license' in versions_columns:
                        insert_sql += ', license'
                        values_sql += ', ?'
                        params.append(license_info)
                    if 'client_side' in versions_columns:
                        insert_sql += ', client_side'
                        values_sql += ', ?'
                        params.append(client_side)
                    if 'server_side' in versions_columns:
                        insert_sql += ', server_side'
                        values_sql += ', ?'
                        params.append(server_side)
                        
                    insert_sql += ') ' + values_sql + ')'
                    cursor.execute(insert_sql, params)
                
                # Обрабатываем версии
                for version in versions:
                    # Поиск основного файла
                    primary_file = next(
                        (f for f in version["files"] if f["primary"]), 
                        version["files"][0] if version["files"] else {}
                    )
                    
                    if not primary_file:
                        continue
                    
                    # Получаем хэш и размер файла
                    file_size = primary_file.get("size", 0)
                    sha512_hash = primary_file.get("hashes", {}).get("sha512", "")
                    
                    # Извлекаем зависимости, историю изменений и тип версии
                    dependencies = json.dumps(version.get("dependencies", []))
                    changelog = version.get("changelog", "")
                    version_type = version.get("version_type", "release")
                    
                    # Проверяем, существует ли версия
                    cursor.execute("SELECT id FROM versions WHERE id = ?", (version["id"],))
                    version_exists = cursor.fetchone() is not None
                    
                    if version_exists:
                        # Обновляем существующую версию
                        update_sql = '''
                            UPDATE versions 
                            SET version_number = ?, loaders = ?, game_versions = ?, 
                                download_url = ?, filename = ?, published_at = ?
                        '''
                        params = [
                            version["version_number"],
                            ",".join(version["loaders"]),
                            ",".join(version["game_versions"]),
                            primary_file["url"],
                            primary_file["filename"],
                            version["date_published"],
                        ]
                        
                        # Добавляем новые столбцы, если они существуют
                        if 'file_size' in versions_columns:
                            update_sql += ', file_size = ?'
                            params.append(file_size)
                        if 'sha512_hash' in versions_columns:
                            update_sql += ', sha512_hash = ?'
                            params.append(sha512_hash)
                        if 'dependencies' in versions_columns:
                            update_sql += ', dependencies = ?'
                            params.append(dependencies)
                        if 'changelog' in versions_columns:
                            update_sql += ', changelog = ?'
                            params.append(changelog)
                        if 'version_type' in versions_columns:
                            update_sql += ', version_type = ?'
                            params.append(version_type)
                        
                        update_sql += ' WHERE id = ? AND mod_id = ?'
                        params.extend([version["id"], mod_data["id"]])
                        cursor.execute(update_sql, params)
                    else:
                        # Добавляем новую версию
                        insert_sql = '''
                            INSERT INTO versions 
                            (id, mod_id, version_number, loaders, game_versions, 
                            download_url, filename, published_at
                        '''
                        values_sql = 'VALUES (?, ?, ?, ?, ?, ?, ?, ?'
                        params = [
                            version["id"],
                            mod_data["id"],
                            version["version_number"],
                            ",".join(version["loaders"]),
                            ",".join(version["game_versions"]),
                            primary_file["url"],
                            primary_file["filename"],
                            version["date_published"]
                        ]
                        
                        # Добавляем новые столбцы, если они существуют
                        if 'file_size' in versions_columns:
                            insert_sql += ', file_size'
                            values_sql += ', ?'
                            params.append(file_size)
                        if 'sha512_hash' in versions_columns:
                            insert_sql += ', sha512_hash'
                            values_sql += ', ?'
                            params.append(sha512_hash)
                        if 'dependencies' in versions_columns:
                            insert_sql += ', dependencies'
                            values_sql += ', ?'
                            params.append(dependencies)
                        if 'changelog' in versions_columns:
                            insert_sql += ', changelog'
                            values_sql += ', ?'
                            params.append(changelog)
                        if 'version_type' in versions_columns:
                            insert_sql += ', version_type'
                            values_sql += ', ?'
                            params.append(version_type)
                        
                        insert_sql += ') ' + values_sql + ')'
                        cursor.execute(insert_sql, params)
                    
                    # Сохраняем зависимости в отдельную таблицу для нормализации
                    for dep in version.get("dependencies", []):
                        cursor.execute('''
                            INSERT OR IGNORE INTO dependencies 
                            (version_id, project_id, version_id_ref, dependency_type, file_name)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (
                            version["id"],
                            dep.get("project_id"),
                            dep.get("version_id"),
                            dep.get("dependency_type"),
                            dep.get("file_name")
                        ))
                    
                successful += 1
                
            conn.commit()
            logger.info(f"Обработано модов: {successful}, пропущено: {skipped}")
            
        except Exception as e:
            logger.error(f"Ошибка при сохранении партии модов: {e}")
            conn.rollback()
        finally:
            conn.close()
        
        return successful, skipped
    
    def get_mods_to_update(self, days_old=7):
        """Получаем список модов, которые не обновлялись более указанного количества дней"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cutoff_date = (datetime.now() - timedelta(days=days_old)).isoformat()
        
        cursor.execute("""
            SELECT id, title, last_checked 
            FROM mods 
            WHERE last_checked < ? OR last_checked IS NULL
            ORDER BY last_checked ASC
        """, (cutoff_date,))
        
        mods_to_update = [{"project_id": row[0], "title": row[1]} for row in cursor.fetchall()]
        conn.close()
        
        return mods_to_update
    
    async def run_async(self, update_mode=False, update_days_old=7):
        """Основной асинхронный метод запуска с поддержкой режима обновления"""
        start_time = time.time()
        
        if update_mode:
            logger.info(f"Запуск в режиме ОБНОВЛЕНИЯ модов старше {update_days_old} дней")
            mods_to_update = self.get_mods_to_update(update_days_old)
            mods_list = [{"project_id": mod["project_id"], "title": mod["title"]} for mod in mods_to_update]
            logger.info(f"Найдено модов для обновления: {len(mods_list)}")
        else:
            logger.info(f"Запуск асинхронного парсера Modrinth в {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info(f"Минимальное количество загрузок: {self.min_downloads}")
            logger.info(f"Минимальное количество версий: {self.min_versions}")
            logger.info(f"Максимальное количество одновременных запросов: {self.max_concurrent_requests}")
            logger.info(f"Пропуск существующих модов: {'Включен' if self.skip_existing else 'Отключен'}")
            
            # Получаем список уже существующих модов, если включен пропуск
            if self.skip_existing:
                self.existing_mod_ids = self.get_existing_mod_ids()
                logger.info(f"Найдено {len(self.existing_mod_ids)} модов в базе, которые будут пропущены")
            
            # 1. Получаем список всех модов для обработки
            mods_list = await self.fetch_popular_mods(session)
        
        if not mods_list:
            logger.error("Не удалось получить список модов для обработки")
            return
            
            mods_to_process = [(mod["project_id"], mod) for mod in mods_list]
            total_mods = len(mods_to_process)
            
            # 2. Обрабатываем моды асинхронными батчами
            batch_size = 50
            successful, skipped = 0, 0
            
            for i in range(0, total_mods, batch_size):
                batch = mods_to_process[i:i + batch_size]
                batch_number = i//batch_size + 1
                total_batches = (total_mods + batch_size - 1)//batch_size
                
                logger.info(f"Обработка батча {batch_number}/{total_batches}")
                
                # Создаем задачи для асинхронной обработки всего батча
                tasks = [self.process_single_mod(session, mod_info) for mod_info in batch]
                results = await asyncio.gather(*tasks)
                
                # Синхронно сохраняем весь батч в БД
                batch_successful, batch_skipped = self.save_mods_batch(results)
                successful += batch_successful
                skipped += batch_skipped
                
                # Прогресс и примерное время до завершения
                elapsed_time = time.time() - start_time
                mods_per_second = successful / elapsed_time if elapsed_time > 0 else 0
                remaining_mods = total_mods - successful - skipped
                eta_seconds = remaining_mods / mods_per_second if mods_per_second > 0 else 0
                
                logger.info(f"Прогресс: {successful+skipped}/{total_mods} модов "
                           f"({((successful+skipped)/total_mods*100):.1f}%), "
                           f"ETA: {eta_seconds/60:.1f} мин")
                
                # Короткая пауза между батчами
                await asyncio.sleep(1)
            
            # 3. Финализация и статистика
            end_time = time.time()
            duration = end_time - start_time
            logger.info(f"\nПарсинг завершен!")
            logger.info(f"Успешно обработано: {successful} модов")
            logger.info(f"Пропущено: {skipped} модов")
            logger.info(f"Затраченное время: {duration:.2f} секунд")
            logger.info(f"Скорость: {successful / duration:.2f} модов/секунду")
            
            # Вывод статистики базы данных
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM mods")
            mods_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM versions")
            versions_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM dependencies")
            dependencies_count = cursor.fetchone()[0]
            
            conn.close()
            
            logger.info(f"Всего модов в базе: {mods_count}")
            logger.info(f"Всего версий в базе: {versions_count}")
            logger.info(f"Всего зависимостей в базе: {dependencies_count}")

    # Для обратной совместимости
    def run(self):
        """Синхронный метод запуска (для обратной совместимости)"""
        asyncio.run(self.run_async())

# Запуск парсера
if __name__ == "__main__":
    # Ваш API-токен Modrinth
    API_TOKEN = "mrp_oZGKmhb6bISFT6Lw38u00edVh5QmAxp4gwv2qk73QEIeRHPiCtS9zNe50LnH"
    
    parser = ModrinthParser(
        db_path="modrinth.db",
        min_downloads=1000,
        min_versions=1,  # Новый параметр
        max_concurrent_requests=30,
        api_token=API_TOKEN,
        skip_existing=True
    )

    # Для обновления модов, которые не обновлялись более 7 дней
    parser.run_async(update_mode=True, update_days_old=7)
    
    # Запускаем асинхронный парсер
    asyncio.run(parser.run_async())