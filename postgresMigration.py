import sqlite3
import asyncpg
import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any

class SQLiteToPostgresMigrator:
    def __init__(self, sqlite_path: str, postgres_config: Dict[str, Any]):
        self.sqlite_path = sqlite_path
        self.postgres_config = postgres_config
        self.pool = None
    
    async def init_postgres(self):
        """Инициализация подключения к PostgreSQL"""
        self.pool = await asyncpg.create_pool(**self.postgres_config)
        
        # Создаем таблицы в PostgreSQL, если они еще не существуют
        async with self.pool.acquire() as conn:
            await self.create_tables(conn)
    
    async def create_tables(self, conn):
        """Создание таблиц в PostgreSQL с правильными типами данных"""
        
        # Таблица пользователей - используем TEXT для user_id
        await conn.execute('''
            CREATE TABLE users (
                user_id TEXT PRIMARY KEY,  -- Изменено на TEXT
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица подписок - используем TEXT для user_id
        await conn.execute('''
            CREATE TABLE subscriptions (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(user_id),  -- Изменено на TEXT
                mod_id TEXT NOT NULL REFERENCES mods(id),
                mod_name TEXT NOT NULL,
                last_version TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, mod_id)
            )
        ''')
        
        # Создаем остальные таблицы, если они еще не существуют
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS mods (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                slug TEXT UNIQUE,
                downloads INTEGER DEFAULT 0,
                updated_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_checked TIMESTAMP,
                categories TEXT[],
                license TEXT,
                client_side TEXT,
                server_side TEXT
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS versions (
                id TEXT PRIMARY KEY,
                mod_id TEXT NOT NULL REFERENCES mods(id) ON DELETE CASCADE,
                version_number TEXT NOT NULL,
                loaders TEXT[] NOT NULL,
                game_versions TEXT[] NOT NULL,
                download_url TEXT NOT NULL,
                filename TEXT,
                published_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                dependencies JSONB,
                changelog TEXT,
                version_type TEXT,
                file_size INTEGER,
                sha512_hash TEXT
            )
        ''')
        
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
        
        # Создаем индексы, если они еще не существуют
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_mods_downloads ON mods(downloads)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_mods_updated ON mods(updated_at)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_mods_last_checked ON mods(last_checked)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_mods_categories ON mods USING GIN(categories)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_versions_mod ON versions(mod_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_versions_game ON versions USING GIN(game_versions)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_versions_loaders ON versions USING GIN(loaders)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_dependencies_version ON dependencies(version_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id)')
        await conn.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_mod ON subscriptions(mod_id)')
    
    def get_sqlite_connection(self):
        """Получение соединения с SQLite"""
        return sqlite3.connect(self.sqlite_path)
    
    def parse_sqlite_array(self, array_str):
        """Парсинг массива из SQLite (строка с разделителями) в список Python"""
        if not array_str:
            return []
        
        if isinstance(array_str, list):
            return array_str
            
        # Убираем возможные пробелы и разбиваем по запятой
        return [item.strip() for item in array_str.split(',') if item.strip()]
    
    def parse_sqlite_datetime(self, datetime_str):
        """Парсинг даты из SQLite в объект datetime"""
        if not datetime_str:
            return None
        
        if isinstance(datetime_str, datetime):
            return datetime_str
            
        try:
            # Пробуем разные форматы дат
            if 'T' in datetime_str:
                # ISO формат
                if datetime_str.endswith('Z'):
                    datetime_str = datetime_str[:-1] + '+00:00'
                return datetime.fromisoformat(datetime_str)
            else:
                # Другие форматы
                for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
                    try:
                        return datetime.strptime(datetime_str, fmt)
                    except ValueError:
                        continue
                return None
        except (ValueError, TypeError):
            return None
    
    async def migrate_mods(self):
        """Миграция таблицы mods"""
        sqlite_conn = self.get_sqlite_connection()
        sqlite_cursor = sqlite_conn.cursor()
        
        sqlite_cursor.execute("SELECT * FROM mods")
        mods = sqlite_cursor.fetchall()
        columns = [description[0] for description in sqlite_cursor.description]
        
        async with self.pool.acquire() as conn:
            for mod in mods:
                mod_dict = dict(zip(columns, mod))
                
                # Преобразуем данные для PostgreSQL
                categories = self.parse_sqlite_array(mod_dict.get('categories'))
                updated_at = self.parse_sqlite_datetime(mod_dict.get('updated_at'))
                created_at = self.parse_sqlite_datetime(mod_dict.get('created_at')) or datetime.now()
                last_checked = self.parse_sqlite_datetime(mod_dict.get('last_checked'))
                
                # Вставляем данные в PostgreSQL
                await conn.execute('''
                    INSERT INTO mods 
                    (id, title, description, slug, downloads, updated_at, created_at, last_checked, categories, license, client_side, server_side)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
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
                ''', 
                mod_dict['id'],
                mod_dict['title'],
                mod_dict.get('description'),
                mod_dict.get('slug'),
                mod_dict.get('downloads', 0),
                updated_at,
                created_at,
                last_checked,
                categories,
                mod_dict.get('license'),
                mod_dict.get('client_side'),
                mod_dict.get('server_side'))
        
        sqlite_conn.close()
        print(f"Перенесено {len(mods)} модов")
    
    async def migrate_versions(self):
        """Миграция таблицы versions с проверкой существования mod_id"""
        sqlite_conn = self.get_sqlite_connection()
        sqlite_cursor = sqlite_conn.cursor()
        
        sqlite_cursor.execute("SELECT * FROM versions")
        versions = sqlite_cursor.fetchall()
        columns = [description[0] for description in sqlite_cursor.description]
        
        async with self.pool.acquire() as conn:
            skipped_versions = 0
            
            for version in versions:
                version_dict = dict(zip(columns, version))
                mod_id = version_dict['mod_id']
                
                # Проверяем существование mod_id в таблице mods
                mod_exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM mods WHERE id = $1)", 
                    mod_id
                )
                
                if not mod_exists:
                    print(f"Пропускаем версию {version_dict['id']}: mod_id {mod_id} не существует в таблице mods")
                    skipped_versions += 1
                    continue
                
                # Преобразуем данные для PostgreSQL
                loaders = self.parse_sqlite_array(version_dict.get('loaders'))
                game_versions = self.parse_sqlite_array(version_dict.get('game_versions'))
                published_at = self.parse_sqlite_datetime(version_dict.get('published_at'))
                created_at = self.parse_sqlite_datetime(version_dict.get('created_at')) or datetime.now()
                
                # Получаем зависимости для этой версии
                dependencies = await self.get_dependencies_for_version(version_dict['id'])
                
                # Вставляем данные в PostgreSQL
                await conn.execute('''
                    INSERT INTO versions 
                    (id, mod_id, version_number, loaders, game_versions, download_url, filename, published_at, created_at, dependencies, changelog, version_type, file_size, sha512_hash)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    ON CONFLICT (id) DO UPDATE SET
                        mod_id = EXCLUDED.mod_id,
                        version_number = EXCLUDED.version_number,
                        loaders = EXCLUDED.loaders,
                        game_versions = EXCLUDED.game_versions,
                        download_url = EXCLUDED.download_url,
                        filename = EXCLUDED.filename,
                        published_at = EXCLUDED.published_at,
                        created_at = EXCLUDED.created_at,
                        dependencies = EXCLUDED.dependencies,
                        changelog = EXCLUDED.changelog,
                        version_type = EXCLUDED.version_type,
                        file_size = EXCLUDED.file_size,
                        sha512_hash = EXCLUDED.sha512_hash
                ''', 
                version_dict['id'],
                version_dict['mod_id'],
                version_dict['version_number'],
                loaders,
                game_versions,
                version_dict.get('download_url'),
                version_dict.get('filename'),
                published_at,
                created_at,
                dependencies,
                version_dict.get('changelog'),
                version_dict.get('version_type'),
                version_dict.get('file_size'),
                version_dict.get('sha512_hash'))
        
        sqlite_conn.close()
        print(f"Перенесено {len(versions) - skipped_versions} версий, пропущено {skipped_versions} версий")
    
    async def get_dependencies_for_version(self, version_id):
        """Получение зависимостей для версии и преобразование в JSON"""
        sqlite_conn = self.get_sqlite_connection()
        sqlite_cursor = sqlite_conn.cursor()
        
        sqlite_cursor.execute("SELECT * FROM dependencies WHERE version_id = ?", (version_id,))
        dependencies = sqlite_cursor.fetchall()
        columns = [description[0] for description in sqlite_cursor.description]
        
        dependencies_list = []
        for dep in dependencies:
            dep_dict = dict(zip(columns, dep))
            # Убираем ненужные поля
            for field in ['id', 'version_id']:
                if field in dep_dict:
                    del dep_dict[field]
            
            dependencies_list.append(dep_dict)
        
        sqlite_conn.close()
        return json.dumps(dependencies_list) if dependencies_list else None
    
    async def migrate_dependencies(self):
        """Миграция таблицы dependencies (если нужно сохранить отдельную таблицу)"""
        sqlite_conn = self.get_sqlite_connection()
        sqlite_cursor = sqlite_conn.cursor()
        
        sqlite_cursor.execute("SELECT * FROM dependencies")
        dependencies = sqlite_cursor.fetchall()
        columns = [description[0] for description in sqlite_cursor.description]
        
        async with self.pool.acquire() as conn:
            for dep in dependencies:
                dep_dict = dict(zip(columns, dep))
                
                # Вставляем данные в PostgreSQL
                await conn.execute('''
                    INSERT INTO dependencies 
                    (id, version_id, project_id, version_id_ref, dependency_type, file_name)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (id) DO UPDATE SET
                        version_id = EXCLUDED.version_id,
                        project_id = EXCLUDED.project_id,
                        version_id_ref = EXCLUDED.version_id_ref,
                        dependency_type = EXCLUDED.dependency_type,
                        file_name = EXCLUDED.file_name
                ''', 
                dep_dict['id'],
                dep_dict['version_id'],
                dep_dict.get('project_id'),
                dep_dict.get('version_id_ref'),
                dep_dict.get('dependency_type'),
                dep_dict.get('file_name'))
        
        sqlite_conn.close()
        print(f"Перенесено {len(dependencies)} зависимостей")
    
    async def migrate_users(self):
        """Миграция таблицы users"""
        sqlite_conn = self.get_sqlite_connection()
        sqlite_cursor = sqlite_conn.cursor()
        
        sqlite_cursor.execute("SELECT * FROM users")
        users = sqlite_cursor.fetchall()
        columns = [description[0] for description in sqlite_cursor.description]
        
        async with self.pool.acquire() as conn:
            for user in users:
                user_dict = dict(zip(columns, user))
                
                # Преобразуем даты
                created_at = self.parse_sqlite_datetime(user_dict.get('created_at')) or datetime.now()
                last_interaction = self.parse_sqlite_datetime(user_dict.get('last_interaction')) or datetime.now()
                
                # Явно преобразуем user_id в строку, чтобы избежать ошибок с большими числами
                user_id = str(user_dict['user_id'])
                
                # Вставляем данные в PostgreSQL
                await conn.execute('''
                    INSERT INTO users 
                    (user_id, username, first_name, last_name, language_code, created_at, last_interaction)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (user_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        language_code = EXCLUDED.language_code,
                        created_at = EXCLUDED.created_at,
                        last_interaction = EXCLUDED.last_interaction
                ''', 
                user_id,  # Передаем как строку
                user_dict.get('username'),
                user_dict.get('first_name'),
                user_dict.get('last_name'),
                user_dict.get('language_code'),
                created_at,
                last_interaction)
        
        sqlite_conn.close()
        print(f"Перенесено {len(users)} пользователей")
    
    async def migrate_subscriptions(self):
        """Миграция таблицы subscriptions с проверкой существования mod_id и user_id"""
        sqlite_conn = self.get_sqlite_connection()
        sqlite_cursor = sqlite_conn.cursor()
        
        sqlite_cursor.execute("SELECT * FROM subscriptions")
        subscriptions = sqlite_cursor.fetchall()
        columns = [description[0] for description in sqlite_cursor.description]
        
        async with self.pool.acquire() as conn:
            skipped_subscriptions = 0
            
            for sub in subscriptions:
                sub_dict = dict(zip(columns, sub))
                mod_id = sub_dict['mod_id']
                user_id = str(sub_dict['user_id'])  # Преобразуем в строку
                
                # Проверяем существование mod_id в таблице mods
                mod_exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM mods WHERE id = $1)", 
                    mod_id
                )
                
                # Проверяем существование user_id в таблице users
                user_exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM users WHERE user_id = $1)", 
                    user_id  # Уже преобразовано в строку
                )
                
                if not mod_exists or not user_exists:
                    reason = ""
                    if not mod_exists:
                        reason += f"mod_id {mod_id} не существует в таблице mods"
                    if not user_exists:
                        if reason:
                            reason += " и "
                        reason += f"user_id {user_id} не существует в таблице users"
                    
                    print(f"Пропускаем подписку {sub_dict['id']}: {reason}")
                    skipped_subscriptions += 1
                    continue
                
                # Преобразуем даты
                created_at = self.parse_sqlite_datetime(sub_dict.get('created_at')) or datetime.now()
                updated_at = self.parse_sqlite_datetime(sub_dict.get('updated_at')) or datetime.now()
                
                # Вставляем данные в PostgreSQL
                await conn.execute('''
                    INSERT INTO subscriptions 
                    (id, user_id, mod_id, mod_name, last_version, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        mod_id = EXCLUDED.mod_id,
                        mod_name = EXCLUDED.mod_name,
                        last_version = EXCLUDED.last_version,
                        created_at = EXCLUDED.created_at,
                        updated_at = EXCLUDED.updated_at
                ''', 
                sub_dict['id'],
                user_id,  # Передаем как строку
                sub_dict['mod_id'],
                sub_dict['mod_name'],
                sub_dict.get('last_version'),
                created_at,
                updated_at)
        
        sqlite_conn.close()
        print(f"Перенесено {len(subscriptions) - skipped_subscriptions} подписок, пропущено {skipped_subscriptions} подписок")
    
    async def run_migration(self):
        """Запуск полной миграции"""
        print("Начало миграции данных из SQLite в PostgreSQL...")
        
        try:
            await self.init_postgres()
            
            print("Миграция модов...")
            await self.migrate_mods()
            
            print("Миграция версий...")
            await self.migrate_versions()
            
            print("Миграция пользователей...")
            await self.migrate_users()
            
            print("Миграция подписок...")
            await self.migrate_subscriptions()

            print("Миграция зависимостей...")
            await self.migrate_dependencies()
            
            print("Миграция завершена успешно!")
            
        except Exception as e:
            print(f"Ошибка при миграции: {e}")
            raise
        finally:
            if self.pool:
                await self.pool.close()

# Использование
async def main():
    # Конфигурация PostgreSQL
    POSTGRES_CONFIG = {
        "host": "localhost",
        "port": 5432,
        "user": "postgres",
        "password": "20088002",
        "database": "MineCollection"
    }
    
    # Путь к SQLite базе
    SQLITE_PATH = "modrinth.db"  # Замените на реальный путь
    
    migrator = SQLiteToPostgresMigrator(SQLITE_PATH, POSTGRES_CONFIG)
    await migrator.run_migration()

if __name__ == "__main__":
    asyncio.run(main())