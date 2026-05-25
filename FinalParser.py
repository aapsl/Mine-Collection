#!/usr/bin/env python
"""
БЕЗОПАСНЫЙ парсер модов с Modrinth
НЕ УДАЛЯЕТ существующие данные, только добавляет/обновляет
Запуск: python safe_parser.py
"""

import asyncio
import os
import sys
from dotenv import load_dotenv
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

import aiohttp
import asyncpg
import logging
import time
from typing import List, Dict, Set
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# PostgreSQL конфигурация из .env
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME", "MineCollection")
}


def parse_datetime(dt_str: str) -> datetime:
    """Преобразует строку даты из API в datetime объект"""
    if not dt_str:
        return None
    try:
        # Убираем 'Z' и заменяем на '+00:00'
        if dt_str.endswith('Z'):
            dt_str = dt_str[:-1] + '+00:00'
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None


class SafeModrinthParser:
    def __init__(self, min_downloads: int = 1000):
        self.min_downloads = min_downloads
        self.base_url = "https://api.modrinth.com/v2"
        self.headers = {
            "User-Agent": "MineCollection-Parser/1.0",
            "Accept": "application/json"
        }
        token = os.getenv("MODRINTH_API_TOKEN")
        if token:
            self.headers["Authorization"] = token
            logger.info("✅ API токен установлен")
        self.pool = None
    
    async def init_database(self):
        """Инициализация БД с правильной структурой"""
        self.pool = await asyncpg.create_pool(**DB_CONFIG)
        logger.info("✅ Подключение к БД установлено")
    
    async def get_existing_mods(self) -> Set[str]:
        """Получение списка существующих ID модов"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM mods")
            return {row['id'] for row in rows}
    
    async def get_all_mod_ids(self, session) -> List[str]:
        """Получение всех ID модов с API (останавливается после 3 страниц без новых модов)"""
        all_mods = []
        limit = 100
        offset = 0
        empty_pages_count = 0
        max_pages = 500
        
        logger.info(f"🔍 Поиск модов с >= {self.min_downloads} загрузок")
        
        while offset // limit < max_pages:
            params = {"limit": limit, "offset": offset, "index": "downloads"}
            
            try:
                async with session.get(f"{self.base_url}/search", params=params, headers=self.headers) as resp:
                    if resp.status != 200:
                        logger.warning(f"API вернул статус {resp.status}")
                        break
                    
                    data = await resp.json()
                    
                    if not data or "hits" not in data:
                        break
                    
                    hits = data["hits"]
                    
                    # Фильтруем моды по загрузкам
                    added_on_page = 0
                    for mod in hits:
                        downloads = mod.get("downloads", 0)
                        if downloads >= self.min_downloads:
                            all_mods.append(mod["project_id"])
                            added_on_page += 1
                    
                    # Логируем
                    if added_on_page > 0:
                        logger.info(f"📄 Страница {offset//limit + 1}: +{added_on_page} модов, всего {len(all_mods)}")
                        empty_pages_count = 0  # Сбрасываем счётчик, если есть добавления
                    else:
                        empty_pages_count += 1
                        logger.info(f"📄 Страница {offset//limit + 1}: нет модов с >= {self.min_downloads} загрузок ({empty_pages_count}/3)")
                        
                        # После 3 страниц без новых модов — останавливаемся
                        if empty_pages_count >= 3:
                            logger.info(f"🛑 Остановка: 3 страницы без модов с >= {self.min_downloads} загрузок")
                            break
                    
                    # Если получили меньше 100 модов — это последняя страница
                    if len(hits) < limit:
                        logger.info(f"🛑 Остановка: последняя страница")
                        break
                    
                    offset += limit
                    await asyncio.sleep(0.1)
                    
            except asyncio.CancelledError:
                logger.info("⏹️ Прервано пользователем")
                break
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                break
        
        logger.info(f"✅ Итого {len(all_mods)} модов с >= {self.min_downloads} загрузок")
        return all_mods
    
    async def process_batch(self, session, mod_ids: List[str], is_update: bool = False):
        """Обработка батча модов"""
        if not mod_ids:
            return
        
        batch_size = 50
        total = len(mod_ids)
        
        for i in range(0, total, batch_size):
            batch = mod_ids[i:i + batch_size]
            
            # Получаем детали модов
            ids_param = json.dumps(batch)
            async with session.get(f"{self.base_url}/projects", params={"ids": ids_param}, headers=self.headers) as resp:
                if resp.status != 200:
                    logger.error(f"Ошибка API: {resp.status}")
                    continue
                projects = await resp.json()
            
            projects_dict = {p["id"]: p for p in projects if p}
            
            for mod_id in batch:
                if mod_id not in projects_dict:
                    continue
                
                mod = projects_dict[mod_id]
                
                # Получаем версии
                async with session.get(f"{self.base_url}/project/{mod_id}/version", headers=self.headers) as resp:
                    if resp.status != 200:
                        versions = []
                    else:
                        versions = await resp.json()
                
                # Сохраняем в БД
                await self.save_mod(mod, versions, is_update)
                await asyncio.sleep(0.05)
            
            logger.info(f"  Обработан батч {i//batch_size + 1}/{(total + batch_size - 1)//batch_size}")
    
    async def save_mod(self, mod: dict, versions: list, is_update: bool = False):
        """Сохранение мода в БД с обработкой конфликтов"""
        async with self.pool.acquire() as conn:
            # Подготовка данных
            categories = mod.get("categories", [])
            license_info = mod.get("license", {}).get("id", "") if isinstance(mod.get("license"), dict) else mod.get("license", "")
            client_side = mod.get("client_side", "unknown")
            server_side = mod.get("server_side", "unknown")
            
            # Преобразуем дату
            updated_at = parse_datetime(mod.get("updated"))
            
            # Пытаемся вставить или обновить
            try:
                if is_update:
                    # Обновляем существующий
                    await conn.execute("""
                        UPDATE mods SET
                            title = $2,
                            description = $3,
                            downloads = $4,
                            updated_at = $5,
                            last_checked = CURRENT_TIMESTAMP,
                            categories = $6,
                            license = $7,
                            client_side = $8,
                            server_side = $9
                        WHERE id = $1
                    """,
                        mod["id"], mod["title"], mod.get("description", "")[:1000],
                        mod.get("downloads", 0), updated_at, categories, license_info,
                        client_side, server_side
                    )
                else:
                    # Вставляем новый (игнорируем конфликты по id и slug)
                    await conn.execute("""
                        INSERT INTO mods (id, title, description, slug, downloads, updated_at, last_checked, categories, license, client_side, server_side)
                        VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP, $7, $8, $9, $10)
                        ON CONFLICT (id) DO NOTHING
                    """,
                        mod["id"], mod["title"], mod.get("description", "")[:1000], mod["slug"],
                        mod.get("downloads", 0), updated_at, categories, license_info,
                        client_side, server_side
                    )
            except Exception as e:
                logger.warning(f"Не удалось сохранить мод {mod['id']}: {e}")
                return  # Выходим, не пытаемся сохранять версии
            
            # Сохраняем версии
            for version in versions[:100]:
                # Находим основной файл
                primary_file = None
                for f in version.get("files", []):
                    if f.get("primary"):
                        primary_file = f
                        break
                if not primary_file and version.get("files"):
                    primary_file = version["files"][0]
                
                if not primary_file:
                    continue
                
                # Преобразуем дату публикации
                published_at = parse_datetime(version.get("date_published"))
                
                try:
                    if is_update:
                        await conn.execute("""
                            UPDATE versions SET
                                version_number = $3,
                                loaders = $4,
                                game_versions = $5,
                                download_url = $6,
                                filename = $7,
                                published_at = $8,
                                file_size = $9,
                                sha512_hash = $10,
                                changelog = $11,
                                version_type = $12
                            WHERE id = $1 AND mod_id = $2
                        """,
                            version["id"], mod["id"], version["version_number"],
                            version.get("loaders", []), version.get("game_versions", []),
                            primary_file.get("url", ""), primary_file.get("filename", ""),
                            published_at, primary_file.get("size", 0),
                            primary_file.get("hashes", {}).get("sha512", ""),
                            version.get("changelog", ""), version.get("version_type", "release")
                        )
                    else:
                        await conn.execute("""
                            INSERT INTO versions (id, mod_id, version_number, loaders, game_versions, download_url, filename, published_at, file_size, sha512_hash, changelog, version_type)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                            ON CONFLICT (id) DO NOTHING
                        """,
                            version["id"], mod["id"], version["version_number"],
                            version.get("loaders", []), version.get("game_versions", []),
                            primary_file.get("url", ""), primary_file.get("filename", ""),
                            published_at, primary_file.get("size", 0),
                            primary_file.get("hashes", {}).get("sha512", ""),
                            version.get("changelog", ""), version.get("version_type", "release")
                        )
                except Exception as e:
                    logger.warning(f"Не удалось сохранить версию {version['id']}: {e}")
    
    async def parse(self):
        """Основной метод парсинга"""
        logger.info("🚀 Запуск парсера")
        start_time = time.time()
        
        await self.init_database()
        
        existing_ids = await self.get_existing_mods()
        logger.info(f"📊 В БД уже {len(existing_ids)} модов")
        
        async with aiohttp.ClientSession() as session:
            all_mod_ids = await self.get_all_mod_ids(session)
            logger.info(f"📦 На API найдено {len(all_mod_ids)} модов")
            
            new_ids = [mid for mid in all_mod_ids if mid not in existing_ids]
            logger.info(f"🆕 Новых модов: {len(new_ids)}")
            
            if new_ids:
                logger.info("📥 Добавление новых модов...")
                await self.process_batch(session, new_ids[:20000], is_update=False)  # Ограничиваем первыми 20000
        
        await self.pool.close()
        
        duration = time.time() - start_time
        logger.info(f"✅ Готово за {duration:.1f} сек")


async def main():
    parser = SafeModrinthParser(min_downloads=1000)
    await parser.parse()


if __name__ == "__main__":
    asyncio.run(main())