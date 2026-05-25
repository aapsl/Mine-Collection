# update_mods.py - обновление модов с выбором количества
import asyncio
import asyncpg
import aiohttp
import json
import os
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

def parse_datetime(dt_str: str):
    if not dt_str:
        return None
    try:
        if dt_str.endswith('Z'):
            dt_str = dt_str[:-1] + '+00:00'
        return datetime.fromisoformat(dt_str)
    except:
        return None

async def update_mod(pool, mod_id: str):
    """Обновляет информацию о моде"""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.modrinth.com/v2/project/{mod_id}") as resp:
            if resp.status != 200:
                return False, 0, 0
            mod = await resp.json()
        
        async with session.get(f"https://api.modrinth.com/v2/project/{mod_id}/version") as resp:
            if resp.status != 200:
                versions = []
            else:
                versions = await resp.json()
    
    async with pool.acquire() as conn:
        # Обновляем мод
        categories = mod.get("categories", [])
        license_info = mod.get("license", {}).get("id", "") if isinstance(mod.get("license"), dict) else mod.get("license", "")
        updated_at = parse_datetime(mod.get("updated"))
        
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
            mod.get("client_side", "unknown"), mod.get("server_side", "unknown")
        )
        
        # Обновляем версии
        new_versions = 0
        updated_versions = 0
        
        for version in versions[:100]:
            exists = await conn.fetchval("SELECT 1 FROM versions WHERE id = $1", version["id"])
            
            primary_file = None
            for f in version.get("files", []):
                if f.get("primary"):
                    primary_file = f
                    break
            if not primary_file and version.get("files"):
                primary_file = version["files"][0]
            
            if not primary_file:
                continue
            
            published_at = parse_datetime(version.get("date_published"))
            
            if exists:
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
                updated_versions += 1
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
                new_versions += 1
        
        return True, new_versions, updated_versions

async def main():
    print("=" * 50)
    print("🔄 ОБНОВЛЕНИЕ МОДОВ")
    print("=" * 50)
    
    pool = await asyncpg.create_pool(**DB_CONFIG)
    
    # Получаем общее количество модов
    async with pool.acquire() as conn:
        total_mods = await conn.fetchval("SELECT COUNT(*) FROM mods")
        print(f"\n📊 В базе данных: {total_mods} модов")
    
    # Меню выбора
    print("\n📋 Выберите режим обновления:")
    print("   1️⃣ - Только топ-1000 модов (быстро, ~10-15 минут)")
    print("   2️⃣ - Топ-5000 модов (средне, ~1-2 часа)")
    print("   3️⃣ - Топ-10000 модов (долго, ~3-4 часа)")
    print("   4️⃣ - ВСЕ моды (очень долго, ~10-15 часов)")
    print("   5️⃣ - Свой вариант (введите количество)")
    print("   0️⃣ - Выход")
    
    choice = input("\n👉 Ваш выбор: ").strip()
    
    if choice == "0":
        print("👋 До свидания!")
        await pool.close()
        return
    
    # Определяем количество модов для обновления
    if choice == "1":
        limit = 1000
        mode_name = "топ-1000"
    elif choice == "2":
        limit = 5000
        mode_name = "топ-5000"
    elif choice == "3":
        limit = 10000
        mode_name = "топ-10000"
    elif choice == "4":
        limit = total_mods
        mode_name = "все"
    elif choice == "5":
        custom = input("🔢 Введите количество модов: ").strip()
        try:
            limit = int(custom)
            mode_name = f"первые {limit}"
        except:
            print("❌ Неверное число!")
            await pool.close()
            return
    else:
        print("❌ Неверный выбор!")
        await pool.close()
        return
    
    # Подтверждение
    print(f"\n⚠️ Вы выбрали обновление {mode_name} модов (всего {limit} шт.)")
    confirm = input("✅ Продолжить? (y/n): ").strip().lower()
    
    if confirm != 'y':
        print("👋 Отменено!")
        await pool.close()
        return
    
    # Получаем список модов для обновления
    async with pool.acquire() as conn:
        mods = await conn.fetch("""
            SELECT id FROM mods 
            ORDER BY downloads DESC 
            LIMIT $1
        """, limit)
    
    print(f"\n🚀 Начинаем обновление {len(mods)} модов...")
    print("=" * 50)
    
    start_time = datetime.now()
    updated = 0
    total_new_versions = 0
    total_updated_versions = 0
    errors = 0
    
    for i, mod in enumerate(mods):
        mod_id = mod['id']
        
        # Прогресс в процентах
        percent = (i + 1) / len(mods) * 100
        bar_length = 30
        filled = int(bar_length * (i + 1) // len(mods))
        bar = '█' * filled + '░' * (bar_length - filled)
        
        print(f"\r[{bar}] {percent:.1f}% - [{i+1}/{len(mods)}] {mod_id[:20]}...", end="", flush=True)
        
        try:
            success, new_versions, updated_versions = await update_mod(pool, mod_id)
            if success:
                updated += 1
                total_new_versions += new_versions
                total_updated_versions += updated_versions
            else:
                errors += 1
        except Exception as e:
            print(f"❌ Ошибка при обновлении мода {mod_id}: {e}")
            errors += 1
        
        # Пауза каждые 50 модов
        if (i + 1) % 50 == 0:
            await asyncio.sleep(0.5)
    
    elapsed = (datetime.now() - start_time).total_seconds()
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    seconds = int(elapsed % 60)
    
    print("\n" + "=" * 50)
    print("✅ ОБНОВЛЕНИЕ ЗАВЕРШЕНО!")
    print("=" * 50)
    print(f"📊 Статистика:")
    print(f"   • Обработано модов: {len(mods)}")
    print(f"   • Успешно обновлено: {updated}")
    print(f"   • Ошибок: {errors}")
    print(f"   • Добавлено новых версий: {total_new_versions}")
    print(f"   • Обновлено существующих версий: {total_updated_versions}")
    print(f"   • Затрачено времени: {hours}ч {minutes}м {seconds}с")
    
    # Финальная статистика БД
    async with pool.acquire() as conn:
        total_mods = await conn.fetchval("SELECT COUNT(*) FROM mods")
        total_versions = await conn.fetchval("SELECT COUNT(*) FROM versions")
        print(f"\n📦 Текущее состояние БД:")
        print(f"   • Модов: {total_mods}")
        print(f"   • Версий: {total_versions}")
    
    await pool.close()
    print("\n👋 До свидания!")

if __name__ == "__main__":
    asyncio.run(main())