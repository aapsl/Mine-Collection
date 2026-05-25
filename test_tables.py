# test_tables.py
import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def test_tables():
    """Проверяет существование таблиц в базе данных"""
    conn = await asyncpg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME", "MineCollection")
    )
    
    try:
        # Проверяем таблицы
        tables = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        
        print("📊 Таблицы в базе данных:")
        for table in tables:
            print(f"   - {table['table_name']}")
        
        # Проверяем количество записей
        for table in ['mods', 'versions', 'dependencies']:
            if table in [t['table_name'] for t in tables]:
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                print(f"   {table}: {count} записей")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(test_tables())