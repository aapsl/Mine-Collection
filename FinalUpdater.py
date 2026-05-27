#!/usr/bin/env python
"""
УНИВЕРСАЛЬНЫЙ АПДЕЙТЕР МОДОВ (С RATE LIMIT И ФИЛЬТРАЦИЕЙ)
- Учитывает ограничения API Modrinth (100/300 RPM)
- Сохраняет только полезные зависимости (required, optional, incompatible)
- Автоматически повторяет сбор до стабилизации
- Батчевая обработка для предотвращения зависаний

Запуск: python universal_updater.py
"""

import asyncio
import asyncpg
import aiohttp
import json
import os
import sys
import time
from datetime import datetime
from typing import List, Tuple, Optional
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME", "MineCollection")
}

API_TOKEN = os.getenv("MODRINTH_API_TOKEN")
HEADERS = {"User-Agent": "MineCollection-Updater/3.2", "Accept": "application/json"}
if API_TOKEN:
    HEADERS["Authorization"] = API_TOKEN
    print("✅ API токен установлен (лимит 300 RPM)")
else:
    print("⚠️ API токен не установлен (лимит 100 RPM)")

# Настройки с учётом rate limit
if API_TOKEN:
    MAX_CONCURRENT = 5      # Параллельных запросов
    BATCH_SIZE = 200        # Модов в батче
    RPM_LIMIT = 250         # Запросов в минуту (запас)
else:
    MAX_CONCURRENT = 2
    BATCH_SIZE = 50
    RPM_LIMIT = 80

# Типы зависимостей, которые сохраняем
KEEP_DEPENDENCY_TYPES = ("required", "optional", "incompatible")


class RateLimiter:
    """Ограничитель частоты запросов к API"""
    def __init__(self, max_requests_per_minute: int):
        self.max_requests = max_requests_per_minute
        self.requests = []
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        async with self.lock:
            now = time.time()
            # Очищаем запросы старше 60 секунд
            self.requests = [t for t in self.requests if now - t < 60]
            
            if len(self.requests) >= self.max_requests:
                wait_time = 60 - (now - self.requests[0])
                if wait_time > 0:
                    print(f"\n⏳ Rate limit: ждём {wait_time:.1f} сек...")
                    await asyncio.sleep(wait_time)
                    now = time.time()
                    self.requests = [t for t in self.requests if now - t < 60]
            
            self.requests.append(now)


# Глобальный ограничитель
rate_limiter = RateLimiter(RPM_LIMIT)


def parse_datetime(dt_str: str) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        if dt_str.endswith('Z'):
            dt_str = dt_str[:-1] + '+00:00'
        return datetime.fromisoformat(dt_str)
    except:
        return None


async def fetch_with_rate_limit(session, url: str) -> dict:
    """Выполняет запрос с учётом rate limit"""
    await rate_limiter.acquire()
    
    async with session.get(url, headers=HEADERS) as resp:
        if resp.status == 429:
            retry_after = int(resp.headers.get('Retry-After', 10))
            print(f"\n⚠️ 429 Too Many Requests, ждём {retry_after} сек...")
            await asyncio.sleep(retry_after)
            return await fetch_with_rate_limit(session, url)
        
        resp.raise_for_status()
        return await resp.json()


async def get_mod_ids(pool, limit: int = None) -> List[str]:
    async with pool.acquire() as conn:
        if limit:
            rows = await conn.fetch("SELECT id FROM mods ORDER BY downloads DESC LIMIT $1", limit)
        else:
            rows = await conn.fetch("SELECT id FROM mods ORDER BY downloads DESC")
        return [row['id'] for row in rows]


async def update_downloads_batch(pool, session, batch: List[str]) -> int:
    """Обновляет только загрузки для батча модов"""
    try:
        ids_param = json.dumps(batch)
        await rate_limiter.acquire()
        
        async with session.get(
            "https://api.modrinth.com/v2/projects",
            params={"ids": ids_param},
            headers=HEADERS
        ) as resp:
            if resp.status != 200:
                return 0
            
            projects = await resp.json()
            
            async with pool.acquire() as conn:
                updated = 0
                for project in projects:
                    if project:
                        current = await conn.fetchval(
                            "SELECT downloads FROM mods WHERE id = $1", project['id']
                        )
                        new_downloads = project.get('downloads', 0)
                        if current != new_downloads:
                            await conn.execute(
                                "UPDATE mods SET downloads = $1, last_checked = CURRENT_TIMESTAMP WHERE id = $2",
                                new_downloads, project['id']
                            )
                            updated += 1
            return updated
    except Exception as e:
        print(f"❌ Ошибка батча: {e}")
        return 0


def filter_useful_dependencies(dependencies: list) -> list:
    """Оставляет только полезные типы зависимостей"""
    if not dependencies:
        return []
    
    return [
        dep for dep in dependencies
        if dep.get("project_id") and dep.get("dependency_type", "") in KEEP_DEPENDENCY_TYPES
    ]


async def collect_single_mod_dependencies(pool, session, mod_id: str, semaphore) -> Tuple[bool, int, int]:
    """Собирает только полезные зависимости для ОДНОГО мода"""
    try:
        async with semaphore:
            versions = await fetch_with_rate_limit(session, f"https://api.modrinth.com/v2/project/{mod_id}/version")
        
        async with pool.acquire() as conn:
            added = 0
            
            for version in versions[:30]:
                deps = filter_useful_dependencies(version.get("dependencies", []))
                if not deps:
                    continue
                
                for dep in deps:
                    project_id = dep.get("project_id")
                    if not project_id:
                        continue
                    
                    exists = await conn.fetchval("""
                        SELECT 1 FROM dependencies 
                        WHERE version_id = $1 AND project_id = $2
                    """, version["id"], project_id)
                    
                    if exists:
                        continue
                    
                    version_id_ref = dep.get("version_id")
                    dep_type = dep.get("dependency_type", "required")
                    
                    if version_id_ref:
                        version_exists = await conn.fetchval("SELECT 1 FROM versions WHERE id = $1", version_id_ref)
                        if not version_exists:
                            continue
                    
                    try:
                        await conn.execute("""
                            INSERT INTO dependencies (version_id, project_id, version_id_ref, dependency_type, file_name)
                            VALUES ($1, $2, $3, $4, $5)
                        """,
                            version["id"], project_id, version_id_ref, dep_type, dep.get("file_name")
                        )
                        added += 1
                    except Exception:
                        pass
            
            return True, 0, added
        
    except Exception as e:
        print(f"❌ Ошибка {mod_id}: {e}")
        return False, 0, 0


async def collect_all_dependencies_auto(pool, session, max_rounds: int = 10):
    """Автоматически собирает зависимости, повторяя до стабилизации"""
    
    print("\n" + "=" * 60)
    print("🔄 АВТОМАТИЧЕСКИЙ СБОР ЗАВИСИМОСТЕЙ")
    print("=" * 60)
    print(f"\n💡 Настройки rate limit:")
    print(f"   • Лимит RPM: {RPM_LIMIT}")
    print(f"   • Параллельных запросов: {MAX_CONCURRENT}")
    print(f"   • Батч: {BATCH_SIZE} модов")
    print(f"\n💡 Сохраняются только типы:", ", ".join(KEEP_DEPENDENCY_TYPES))
    print("   (embedded зависимости игнорируются)\n")
    
    round_num = 1
    total_deps = 0
    total_mods_with_deps = 0
    
    async with pool.acquire() as conn:
        total_deps = await conn.fetchval("SELECT COUNT(*) FROM dependencies")
        total_mods_with_deps = await conn.fetchval("""
            SELECT COUNT(DISTINCT v.mod_id) 
            FROM dependencies d
            JOIN versions v ON d.version_id = v.id
        """)
    
    print(f"📊 Начальная статистика:")
    print(f"   • Зависимостей: {total_deps}")
    print(f"   • Модов с зависимостями: {total_mods_with_deps}")
    
    while round_num <= max_rounds:
        print(f"\n{'='*60}")
        print(f"📊 РАУНД {round_num}")
        print(f"{'='*60}")
        
        async with pool.acquire() as conn:
            mods_without = await conn.fetch("""
                SELECT DISTINCT v.mod_id 
                FROM versions v
                LEFT JOIN dependencies d ON v.id = d.version_id
                WHERE d.id IS NULL
            """)
            mod_ids = [row['mod_id'] for row in mods_without]
        
        if not mod_ids:
            print("\n✅ Нет модов без зависимостей!")
            break
        
        print(f"\n📋 Модов без зависимостей: {len(mod_ids)}")
        
        total_added = 0
        total_failed = 0
        total_processed = 0
        
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        
        for batch_start in range(0, len(mod_ids), BATCH_SIZE):
            batch = mod_ids[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(mod_ids) + BATCH_SIZE - 1) // BATCH_SIZE
            
            print(f"\n  📦 БАТЧ {batch_num}/{total_batches} ({len(batch)} модов)")
            
            tasks = [collect_single_mod_dependencies(pool, session, mod_id, semaphore) for mod_id in batch]
            
            start_time = time.time()
            batch_added = 0
            batch_failed = 0
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    batch_failed += 1
                elif result[0]:
                    batch_added += result[2]
                else:
                    batch_failed += 1
            
            total_added += batch_added
            total_failed += batch_failed
            total_processed += len(batch)
            
            elapsed = time.time() - start_time
            rate = len(batch) / elapsed if elapsed > 0 else 0
            progress_pct = (batch_start + len(batch)) / len(mod_ids) * 100
            
            print(f"    ✅ Добавлено: {batch_added} | Ошибок: {batch_failed} | Скорость: {rate:.1f} мод/сек | Прогресс: {progress_pct:.1f}%")
        
        async with pool.acquire() as conn:
            new_total = await conn.fetchval("SELECT COUNT(*) FROM dependencies")
            new_mods_with_deps = await conn.fetchval("""
                SELECT COUNT(DISTINCT v.mod_id) 
                FROM dependencies d
                JOIN versions v ON d.version_id = v.id
            """)
        
        added_this_round = new_total - total_deps
        added_mods = new_mods_with_deps - total_mods_with_deps
        
        print(f"\n📊 ИТОГИ РАУНДА {round_num}:")
        print(f"   • Успешно обработано: {total_processed - total_failed}")
        print(f"   • Ошибок: {total_failed}")
        print(f"   • Добавлено зависимостей: {added_this_round}")
        print(f"   • Добавлено модов с зависимостями: {added_mods}")
        print(f"   • Всего зависимостей: {new_total}")
        print(f"   • Всего модов с зависимостями: {new_mods_with_deps}")
        
        if added_this_round == 0 and total_failed == 0:
            print("\n✅ Стабилизация достигнута! Новых зависимостей не найдено.")
            break
        
        total_deps = new_total
        total_mods_with_deps = new_mods_with_deps
        round_num += 1
    
    if round_num > max_rounds:
        print(f"\n⚠️ Достигнут лимит раундов ({max_rounds}).")
    
    print("\n" + "=" * 60)
    print("🎉 СБОР ЗАВИСИМОСТЕЙ ЗАВЕРШЁН!")
    print("=" * 60)
    
    async with pool.acquire() as conn:
        final_deps = await conn.fetchval("SELECT COUNT(*) FROM dependencies")
        final_mods = await conn.fetchval("""
            SELECT COUNT(DISTINCT v.mod_id) 
            FROM dependencies d
            JOIN versions v ON d.version_id = v.id
        """)
        
        type_stats = await conn.fetch("""
            SELECT dependency_type, COUNT(*) 
            FROM dependencies 
            GROUP BY dependency_type
        """)
        
        print(f"\n📊 ФИНАЛЬНАЯ СТАТИСТИКА:")
        print(f"   • Всего зависимостей: {final_deps}")
        print(f"   • Модов с зависимостями: {final_mods}")
        print(f"   • Процент от всех модов: {final_mods/48585*100:.1f}%")
        
        if type_stats:
            print(f"\n📊 РАСПРЕДЕЛЕНИЕ ПО ТИПАМ:")
            for dep_type, count in type_stats:
                print(f"   • {dep_type}: {count}")
    
    return total_deps, total_mods_with_deps


async def update_single_mod_full(pool, session, mod_id: str, semaphore) -> Tuple[bool, int, int, int]:
    """Полное обновление мода (только реальные изменения)"""
    try:
        async with semaphore:
            mod = await fetch_with_rate_limit(session, f"https://api.modrinth.com/v2/project/{mod_id}")
            versions = await fetch_with_rate_limit(session, f"https://api.modrinth.com/v2/project/{mod_id}/version")
        
        async with pool.acquire() as conn:
            current = await conn.fetchrow(
                "SELECT title, description, downloads, updated_at FROM mods WHERE id = $1", mod_id
            )
            
            new_downloads = mod.get('downloads', 0)
            new_updated_at = parse_datetime(mod.get('updated'))
            
            mod_changed = False
            if current:
                if (current['title'] != mod.get('title', '') or
                    current['downloads'] != new_downloads or
                    (current['updated_at'] != new_updated_at and new_updated_at)):
                    mod_changed = True
            
            if mod_changed or not current:
                categories = mod.get("categories", [])
                license_info = mod.get("license", {}).get("id", "") if isinstance(mod.get("license"), dict) else mod.get("license", "")
                
                await conn.execute("""
                    UPDATE mods SET
                        title = $2, description = $3, slug = $4,
                        downloads = $5, updated_at = $6, last_checked = CURRENT_TIMESTAMP,
                        categories = $7, license = $8, client_side = $9, server_side = $10
                    WHERE id = $1
                """,
                    mod["id"], mod["title"], mod.get("description", "")[:2000], mod["slug"],
                    new_downloads, new_updated_at, categories, license_info,
                    mod.get("client_side", "unknown"), mod.get("server_side", "unknown")
                )
            
            new_versions = 0
            updated_versions = 0
            deps_count = 0
            
            for version in versions[:100]:
                exists = await conn.fetchval("SELECT 1 FROM versions WHERE id = $1", version["id"])
                
                if not exists:
                    primary_file = None
                    for f in version.get("files", []):
                        if f.get("primary"):
                            primary_file = f
                            break
                    if not primary_file and version.get("files"):
                        primary_file = version["files"][0]
                    
                    if primary_file:
                        published_at = parse_datetime(version.get("date_published"))
                        
                        await conn.execute("""
                            INSERT INTO versions (id, mod_id, version_number, loaders, game_versions,
                                                  download_url, filename, published_at, file_size,
                                                  sha512_hash, changelog, version_type)
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
                        new_versions += 1
                
                deps = [
                    dep for dep in version.get("dependencies", [])
                    if dep.get("project_id") and dep.get("dependency_type", "") in KEEP_DEPENDENCY_TYPES
                ]
                
                for dep in deps:
                    project_id = dep.get("project_id")
                    target_version = dep.get("version_id")
                    
                    if target_version:
                        version_exists = await conn.fetchval("SELECT 1 FROM versions WHERE id = $1", target_version)
                        if not version_exists:
                            continue
                    
                    exists = await conn.fetchval("""
                        SELECT 1 FROM dependencies 
                        WHERE version_id = $1 AND project_id = $2
                    """, version["id"], project_id)
                    
                    if not exists:
                        try:
                            await conn.execute("""
                                INSERT INTO dependencies (version_id, project_id, version_id_ref, dependency_type, file_name)
                                VALUES ($1, $2, $3, $4, $5)
                            """,
                                version["id"], project_id, target_version,
                                dep.get("dependency_type", "required"),
                                dep.get("file_name")
                            )
                            deps_count += 1
                        except Exception:
                            pass
            
            return True, new_versions, updated_versions, deps_count
            
    except Exception as e:
        print(f"❌ Ошибка обновления {mod_id}: {e}")
        return False, 0, 0, 0


async def main():
    print("=" * 60)
    print("🔄 УНИВЕРСАЛЬНЫЙ АПДЕЙТЕР МОДОВ (С RATE LIMIT)")
    print("=" * 60)
    
    pool = await asyncpg.create_pool(**DB_CONFIG)
    
    async with pool.acquire() as conn:
        total_mods = await conn.fetchval("SELECT COUNT(*) FROM mods")
        total_versions = await conn.fetchval("SELECT COUNT(*) FROM versions")
        total_deps = await conn.fetchval("SELECT COUNT(*) FROM dependencies")
        print(f"\n📊 В базе данных:")
        print(f"   • Модов: {total_mods}")
        print(f"   • Версий: {total_versions}")
        print(f"   • Зависимостей: {total_deps}")
    
    print("\n📋 Выберите тип обновления:")
    print("   1️⃣ - Только загрузки (быстро, ~15 мин)")
    print("   2️⃣ - Только зависимости (однократно, ~30 мин)")
    print("   3️⃣ - Полное обновление (медленно, ~3-4 часа)")
    print("   4️⃣ - АВТОМАТИЧЕСКИЙ сбор зависимостей (до стабилизации)")
    print("   0️⃣ - Выход")
    
    update_type = input("\n👉 Ваш выбор: ").strip()
    
    if update_type == "0":
        print("👋 До свидания!")
        await pool.close()
        return
    
    if update_type not in ("1", "2", "3", "4"):
        print("❌ Неверный выбор!")
        await pool.close()
        return
    
    if update_type in ("1", "2", "3"):
        print("\n📋 Выберите количество модов:")
        print("   1️⃣ - Топ-1000")
        print("   2️⃣ - Топ-5000")
        print("   3️⃣ - Топ-10000")
        print("   4️⃣ - Все моды")
        print("   5️⃣ - Свой вариант")
        
        choice = input("\n👉 Ваш выбор: ").strip()
        
        if choice == "1":
            limit = 1000
        elif choice == "2":
            limit = 5000
        elif choice == "3":
            limit = 10000
        elif choice == "4":
            limit = total_mods
        elif choice == "5":
            limit = int(input("🔢 Введите количество: ").strip())
        else:
            print("❌ Неверный выбор!")
            await pool.close()
            return
        
        mod_ids = await get_mod_ids(pool, limit)
        total = len(mod_ids)
    else:
        limit = total_mods
        mod_ids = await get_mod_ids(pool, limit)
        total = len(mod_ids)
    
    print(f"\n🚀 Начинаем обновление...")
    start_time = time.time()
    
    if update_type == "1":
        print("\n📥 ОБНОВЛЕНИЕ ЗАГРУЗОК")
        print("=" * 60)
        updated = 0
        async with aiohttp.ClientSession() as session:
            for i in range(0, total, BATCH_SIZE):
                batch = mod_ids[i:i + BATCH_SIZE]
                count = await update_downloads_batch(pool, session, batch)
                updated += count
                
                if (i + BATCH_SIZE) % 1000 == 0:
                    print(f"📊 Прогресс: {min(i+BATCH_SIZE, total)}/{total} | Обновлено: {updated}")
        
        elapsed = time.time() - start_time
        print(f"\n✅ ОБНОВЛЕНИЕ ЗАВЕРШЕНО за {elapsed/60:.1f} мин")
        print(f"   • Обновлено загрузок: {updated}")
    
    elif update_type == "2":
        print("\n📦 СБОР ЗАВИСИМОСТЕЙ (ОДНОКРАТНО)")
        print("=" * 60)
        added = 0
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        async with aiohttp.ClientSession() as session:
            tasks = [collect_single_mod_dependencies(pool, session, mod_id, semaphore) for mod_id in mod_ids]
            for i, task in enumerate(asyncio.as_completed(tasks)):
                success, _, deps = await task
                if success:
                    added += deps
                
                if (i + 1) % 100 == 0:
                    print(f"📊 Прогресс: {i+1}/{total} | Добавлено зависимостей: {added}")
        
        elapsed = time.time() - start_time
        print(f"\n✅ СБОР ЗАВЕРШЁН за {elapsed/60:.1f} мин")
        print(f"   • Добавлено зависимостей: {added}")
    
    elif update_type == "3":
        print("\n🔄 ПОЛНОЕ ОБНОВЛЕНИЕ")
        print("=" * 60)
        updated = 0
        total_new_versions = 0
        total_deps = 0
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        async with aiohttp.ClientSession() as session:
            tasks = [update_single_mod_full(pool, session, mod_id, semaphore) for mod_id in mod_ids]
            for i, task in enumerate(asyncio.as_completed(tasks)):
                success, new_v, _, deps = await task
                if success:
                    updated += 1
                    total_new_versions += new_v
                    total_deps += deps
                
                if (i + 1) % 50 == 0:
                    print(f"📊 Прогресс: {i+1}/{total} | Новых версий: {total_new_versions} | Зависимостей: {total_deps}")
        
        elapsed = time.time() - start_time
        print(f"\n✅ ОБНОВЛЕНИЕ ЗАВЕРШЕНО за {elapsed/60:.1f} мин")
        print(f"   • Обновлено модов: {updated}")
        print(f"   • Добавлено новых версий: {total_new_versions}")
        print(f"   • Добавлено зависимостей: {total_deps}")
    
    elif update_type == "4":
        async with aiohttp.ClientSession() as session:
            await collect_all_dependencies_auto(pool, session, max_rounds=10)
    
    async with pool.acquire() as conn:
        total_mods = await conn.fetchval("SELECT COUNT(*) FROM mods")
        total_versions = await conn.fetchval("SELECT COUNT(*) FROM versions")
        total_deps = await conn.fetchval("SELECT COUNT(*) FROM dependencies")
        print(f"\n📦 ТЕКУЩЕЕ СОСТОЯНИЕ БД:")
        print(f"   • Модов: {total_mods}")
        print(f"   • Версий: {total_versions}")
        print(f"   • Зависимостей: {total_deps}")
    
    await pool.close()
    print("\n👋 До свидания!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️ Прервано пользователем")