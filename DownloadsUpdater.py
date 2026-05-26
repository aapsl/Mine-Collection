"""
ПОЛНОЕ батчевое обновление ВСЕХ данных о модах
Запуск: python full_update.py
"""

import asyncio
import asyncpg
import aiohttp
import json
import os
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME", "MineCollection")
}

API_TOKEN = os.getenv("MODRINTH_API_TOKEN")
HEADERS = {"User-Agent": "MineCollection-Updater/1.0"}
if API_TOKEN:
    HEADERS["Authorization"] = API_TOKEN
    print("✅ API токен установлен")

def parse_datetime(dt_str: str):
    if not dt_str:
        return None
    try:
        if dt_str.endswith('Z'):
            dt_str = dt_str[:-1] + '+00:00'
        return datetime.fromisoformat(dt_str)
    except:
        return None


async def full_update():
    print("🚀 ПОЛНОЕ батчевое обновление данных модов...")
    
    pool = await asyncpg.create_pool(**DB_CONFIG)
    
    # Получаем все ID
    async with pool.acquire() as conn:
        mods = await conn.fetch("SELECT id FROM mods")
        all_ids = [row['id'] for row in mods]
        print(f"📊 Всего модов: {len(all_ids)}")
    
    updated = 0
    errors = 0
    batch_size = 100
    request_count = 0
    start_time = time.time()
    
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for i in range(0, len(all_ids), batch_size):
            batch = all_ids[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(all_ids) + batch_size - 1) // batch_size
            
            try:
                ids_param = json.dumps(batch)
                
                async with session.get(
                    "https://api.modrinth.com/v2/projects",
                    params={"ids": ids_param}
                ) as resp:
                    
                    request_count += 1
                    
                    if resp.status == 429:
                        retry_after = int(resp.headers.get('Retry-After', 5))
                        print(f"⚠️ Rate limit! Ждём {retry_after} сек...")
                        await asyncio.sleep(retry_after)
                        continue
                    
                    if resp.status != 200:
                        print(f"❌ Ошибка API (батч {batch_num}): {resp.status}")
                        errors += len(batch)
                        continue
                    
                    projects = await resp.json()
                    
                    async with pool.acquire() as conn:
                        for project in projects:
                            if not project:
                                continue
                            
                            # Обновляем ВСЕ поля
                            await conn.execute("""
                                UPDATE mods SET
                                    title = $2,
                                    description = $3,
                                    slug = $4,
                                    downloads = $5,
                                    updated_at = $6,
                                    last_checked = CURRENT_TIMESTAMP,
                                    categories = $7,
                                    license = $8,
                                    client_side = $9,
                                    server_side = $10
                                WHERE id = $1
                            """,
                                project['id'],
                                project.get('title', ''),
                                project.get('description', '')[:2000],
                                project.get('slug', ''),
                                project.get('downloads', 0),
                                parse_datetime(project.get('updated')),
                                project.get('categories', []),
                                project.get('license', {}).get('id', '') if isinstance(project.get('license'), dict) else project.get('license', ''),
                                project.get('client_side', 'unknown'),
                                project.get('server_side', 'unknown')
                            )
                            updated += 1
                    
                    elapsed = time.time() - start_time
                    rpm = request_count / elapsed * 60 if elapsed > 0 else 0
                    print(f"📊 Батч {batch_num}/{total_batches}: +{len(projects)} модов, RPM: {rpm:.0f}")
                    
                    await asyncio.sleep(0.3)  # Безопасная пауза
                    
            except Exception as e:
                print(f"❌ Ошибка батча {batch_num}: {e}")
                errors += len(batch)
    
    elapsed = time.time() - start_time
    print(f"\n✅ Готово за {elapsed/60:.1f} мин!")
    print(f"📊 Обновлено: {updated}, ошибок: {errors}")
    print(f"📊 Запросов: {request_count}, RPM: {request_count / elapsed * 60:.0f}")
    
    await pool.close()


async def fast_downloads_only():
    """Быстрое обновление ТОЛЬКО загрузок (ещё быстрее)"""
    print("🚀 Быстрое обновление ТОЛЬКО загрузок...")
    
    pool = await asyncpg.create_pool(**DB_CONFIG)
    
    async with pool.acquire() as conn:
        mods = await conn.fetch("SELECT id FROM mods")
        all_ids = [row['id'] for row in mods]
    
    batch_size = 100
    request_count = 0
    start_time = time.time()
    
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for i in range(0, len(all_ids), batch_size):
            batch = all_ids[i:i + batch_size]
            
            ids_param = json.dumps(batch)
            async with session.get(
                "https://api.modrinth.com/v2/projects",
                params={"ids": ids_param}
            ) as resp:
                request_count += 1
                
                if resp.status != 200:
                    continue
                
                projects = await resp.json()
                
                async with pool.acquire() as conn:
                    for project in projects:
                        if project:
                            await conn.execute(
                                "UPDATE mods SET downloads = $1 WHERE id = $2",
                                project.get('downloads', 0),
                                project['id']
                            )
                
                await asyncio.sleep(0.3)
    
    elapsed = time.time() - start_time
    print(f"✅ Загрузки обновлены за {elapsed/60:.1f} мин!")
    print(f"📊 Запросов: {request_count}")
    
    await pool.close()


if __name__ == "__main__":
    print("\nВыберите режим обновления:")
    print("1️⃣ - ПОЛНОЕ обновление (все данные)")
    print("2️⃣ - Только загрузки (быстро)")
    
    choice = input("👉 Ваш выбор: ").strip()
    
    if choice == "1":
        asyncio.run(full_update())
    elif choice == "2":
        asyncio.run(fast_downloads_only())
    else:
        print("❌ Неверный выбор")