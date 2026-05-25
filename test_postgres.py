import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def test_postgres():
    """Тестирует подключение к PostgreSQL"""
    print("🔍 Тестирование подключения к PostgreSQL...")
    
    # Параметры из .env
    db_config = {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", 5432)),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME", "postgres")  # Сначала пробуем подключиться к стандартной БД
    }
    
    print(f"📊 Параметры подключения:")
    for key, value in db_config.items():
        if key != "password":
            print(f"   {key}: {value}")
        else:
            print(f"   {key}: {'*' * len(value) if value else 'не указан'}")
    
    try:
        # Пробуем подключиться к стандартной базе данных postgres
        conn = await asyncpg.connect(**db_config)
        version = await conn.fetchval("SELECT version()")
        print(f"✅ Подключение к PostgreSQL успешно!")
        print(f"📋 Версия: {version.split(',')[0]}")
        
        # Проверяем существование нашей базы данных
        db_exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", 
            os.getenv("DB_NAME", "modrinth")
        )
        
        if db_exists:
            print(f"✅ База данных '{os.getenv('DB_NAME', 'modrinth')}' существует")
        else:
            print(f"❌ База данных '{os.getenv('DB_NAME', 'modrinth')}' не существует")
            print("   Создайте базу данных командой: CREATE DATABASE modrinth;")
        
        await conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        print("\n🔧 Возможные причины и решения:")
        print("1. PostgreSQL не запущен")
        print("2. Неправильный пароль")
        print("3. База данных не существует") 
        print("4. Проблемы с сетевыми настройками")
        print("5. Брандмауэр блокирует порт 5432")
        return False

if __name__ == "__main__":
    asyncio.run(test_postgres())