import asyncio
import sqlite3
import logging
import os
import re
import json
import math
import signal
from datetime import datetime
from functools import lru_cache

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest
from rapidfuzz import process, fuzz
from dotenv import load_dotenv

# Добавляем импорт Redis
import redis

# Загрузка переменных окружения из .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Получение переменных из .env
ADMIN_IDS = [1649504565]  # Замените на ваш ID пользователя Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "modrinth.db")
MOD_ALIASES_PATH = os.getenv("MOD_ALIASES_PATH", "mod_aliases.json")

# Проверка наличия обязательных переменных
if not BOT_TOKEN:
    logging.error("Не указан BOT_TOKEN в .env файле")
    exit(1)

# Инициализация Redis
REDIS_AVAILABLE = False
redis_client = None
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0)
    redis_client.ping()
    logging.info("Успешное подключение к Redis")
    REDIS_AVAILABLE = True
except (redis.ConnectionError, Exception) as e:
    logging.warning(f"Не удалось подключиться к Redis: {e}. Будет использоваться встроенный кэш.")

# Загрузка словаря популярных модов из JSON файла
COMMON_MOD_ALIASES = {}
mod_names_cache = {}

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Получаем ID бота
try:
    bot_info = asyncio.run(bot.get_me())
    BOT_ID = bot_info.id
    logging.info(f"ID бота: {BOT_ID}")
except Exception as e:
    logging.error(f"Не удалось получить ID бота: {e}")
    BOT_ID = None

# Проверка существования базы данных
if not os.path.exists(DB_PATH):
    logging.error(f"База данных {DB_PATH} не найдена")
    exit(1)

def init_users_table():
    """Создает таблицу пользователей, если она не существует"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    language_code TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_interaction TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logging.info("Таблица пользователей готова")
    except sqlite3.Error as e:
        logging.error(f"Ошибка при создании таблицы пользователей: {e}")

def init_subscriptions_table():
    """Создает таблицу подписок, если она не существует"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    mod_id TEXT NOT NULL,
                    mod_name TEXT NOT NULL,
                    last_version TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, mod_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions (user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_mod ON subscriptions (mod_id)")
            logging.info("Таблица подписок готова")
    except sqlite3.Error as e:
        logging.error(f"Ошибка при создании таблицы подписок: {e}")

def load_mod_aliases():
    """Загружает псевдонимы модов из JSON файла"""
    global COMMON_MOD_ALIASES
    try:
        if not os.path.exists(MOD_ALIASES_PATH):
            logging.warning(f"Файл с псевдонимами модов {MOD_ALIASES_PATH} не найден. Создаем пустой файл.")
            example_aliases = {
                "jei": "Just Enough Items",
                "just enough items": "Just Enough Items",
                "lithium": "Lithium",
                "sodium": "Sodium"
            }
            with open(MOD_ALIASES_PATH, 'w', encoding='utf-8') as f:
                json.dump(example_aliases, f, ensure_ascii=False, indent=2)
            COMMON_MOD_ALIASES = example_aliases
            logging.info(f"Создан файл с примерами псевдонимов: {MOD_ALIASES_PATH}")
        else:
            with open(MOD_ALIASES_PATH, 'r', encoding='utf-8') as f:
                COMMON_MOD_ALIASES = json.load(f)
            logging.info(f"Загружено {len(COMMON_MOD_ALIASES)} псевдонимов модов из {MOD_ALIASES_PATH}")
    except (json.JSONDecodeError, Exception) as e:
        logging.error(f"Ошибка при загрузке псевдонимов модов: {e}")
        COMMON_MOD_ALIASES = {}

def load_mod_names_cache():
    """Загружает все названия модов в кэш для нечеткого поиска"""
    global mod_names_cache
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title FROM mods")
            mod_names_cache = {row[0]: row[1] for row in cursor.fetchall()}
        logging.info(f"Загружено {len(mod_names_cache)} модов в кэш для поиска")
    except sqlite3.Error as e:
        logging.error(f"Ошибка при загрузке кэша модов: {e}")

# Инициализация таблиц и кэшей
init_users_table()
init_subscriptions_table()
load_mod_aliases()
load_mod_names_cache()

# Функции для работы с базой данных
def register_user(user_id: int, username: str, first_name: str, last_name: str, language_code: str):
    """Регистрирует или обновляет информацию о пользователе"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, language_code, last_interaction)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (user_id, username, first_name, last_name, language_code))
            conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Ошибка при регистрации пользователя: {e}")

def add_subscription(user_id: int, mod_id: str, mod_name: str, last_version: str = None):
    """Добавляет подписку пользователя на мод"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            
            # Сначала проверяем, существует ли уже подписка
            cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id = ? AND mod_id = ?", 
                          (user_id, mod_id))
            exists = cursor.fetchone()[0] > 0
            
            if exists:
                # Обновляем существующую подписку
                cursor.execute("""
                    UPDATE subscriptions 
                    SET mod_name = ?, last_version = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND mod_id = ?
                """, (mod_name, last_version, user_id, mod_id))
                logging.info(f"Обновлена подписка пользователя {user_id} на мод {mod_name} ({mod_id})")
            else:
                # Добавляем новую подписку
                cursor.execute("""
                    INSERT INTO subscriptions (user_id, mod_id, mod_name, last_version, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (user_id, mod_id, mod_name, last_version))
                logging.info(f"Добавлена подписка пользователя {user_id} на мод {mod_name} ({mod_id})")
            
            conn.commit()
            return True
            
    except sqlite3.Error as e:
        logging.error(f"Ошибка при добавлении/обновлении подписки: {e}")
        return False

def remove_subscription(user_id: int, mod_id: str):
    """Удаляет подписку пользователя на мод"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM subscriptions WHERE user_id = ? AND mod_id = ?", (user_id, mod_id))
            conn.commit()
            logging.info(f"Пользователь {user_id} отписался от мода {mod_id}")
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logging.error(f"Ошибка при удалении подписки: {e}")
        return False

def get_user_subscriptions(user_id: int):
    """Возвращает все подписки пользователя"""
    if user_id == BOT_ID:
        logging.warning("Запрос подписок для бота пропущен")
        return []
    
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Используем LEFT JOIN для получения информации о моде, даже если его нет в таблице mods
            cursor.execute("""
                SELECT s.*, 
                       COALESCE(m.title, s.mod_name) as mod_title, 
                       COALESCE(m.slug, s.mod_id) as mod_slug
                FROM subscriptions s
                LEFT JOIN mods m ON s.mod_id = m.id
                WHERE s.user_id = ?
                ORDER BY s.mod_name
            """, (user_id,))
            
            subscriptions = [dict(row) for row in cursor.fetchall()]
            logging.info(f"Найдено {len(subscriptions)} подписок для пользователя {user_id}")
            return subscriptions
            
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении подписок пользователя {user_id}: {e}")
        return []

def get_subscriptions_for_mod(mod_id: str):
    """Возвращает всех пользователей, подписанных на мод"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscriptions WHERE mod_id = ?", (mod_id,))
            return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении подписок на мод: {e}")
        return []

def update_subscription_version(mod_id: str, new_version: str):
    """Обновляет последнюю версию для всех подписок на мод"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE subscriptions 
                SET last_version = ?, updated_at = CURRENT_TIMESTAMP
                WHERE mod_id = ?
            """, (new_version, mod_id))
            conn.commit()
            logging.info(f"Обновлена версия для подписок на мод {mod_id}: {new_version}")
            return cursor.rowcount
    except sqlite3.Error as e:
        logging.error(f"Ошибка при обновлении версии подписки: {e}")
        return 0

def get_all_users():
    """Возвращает список всех пользователей"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении списка пользователей: {e}")
        return []

def get_users_count():
    """Возвращает количество пользователей"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            return cursor.fetchone()[0]
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении количества пользователей: {e}")
        return 0

# Функции для работы с Redis
def get_cached_search(query, limit=10):
    """Проверяет, есть ли результаты поиска в кэше"""
    if not REDIS_AVAILABLE:
        return None
    try:
        cache_key = f"search:{query}:{limit}"
        cached_data = redis_client.get(cache_key)
        if cached_data:
            logging.info(f"Найдены кэшированные результаты для: {query}")
            return json.loads(cached_data)
    except Exception as e:
        logging.error(f"Ошибка при получении из кэша: {e}")
    return None

def set_cached_search(query, limit=10, results=None):
    """Сохраняет результаты поиска в кэш"""
    if not REDIS_AVAILABLE or results is None:
        return
    try:
        cache_key = f"search:{query}:{limit}"
        redis_client.setex(cache_key, 3600, json.dumps(results))
        logging.info(f"Результаты для '{query}' сохранены в кэш")
    except Exception as e:
        logging.error(f"Ошибка при сохранении в кэш: {e}")

# Функции для поиска и обработки модов
def normalize_text(text):
    """Нормализация текста для поиска"""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^a-z0-9\s]', '', text)
    return text

def preprocess_search_query(search_query: str):
    """Предварительная обработка поискового запроса с улучшенным сопоставлением псевдонимов"""
    if not search_query or not search_query.strip():
        return search_query
    
    if not isinstance(search_query, str):
        logging.warning(f"search_query не является строкой в preprocess_search_query: {type(search_query)}")
        search_query = str(search_query)
    
    normalized = normalize_text(search_query)
    logging.info(f"Исходный запрос: '{search_query}', нормализованный: '{normalized}'")
    
    if not normalized:
        return search_query
    
    if normalized in COMMON_MOD_ALIASES:
        result = COMMON_MOD_ALIASES[normalized]
        logging.info(f"Найдено точное совпадение псевдонима: '{normalized}' -> '{result}'")
        return result
    
    best_match = None
    best_score = 0
    
    for alias, full_name in COMMON_MOD_ALIASES.items():
        score = fuzz.ratio(normalized, alias)
        if score > 75 and score > best_score:
            best_score = score
            best_match = full_name
    
    if best_match:
        logging.info(f"Найден псевдоним по нечеткому совпадению: '{search_query}' -> '{best_match}' (score: {best_score})")
        return best_match
    
    logging.info(f"Псевдонимы не найдены, используем оригинальный запрос: '{search_query}'")
    return search_query

def advanced_fuzzy_search_mods(search_query: str, limit: int = 5):
    """Улучшенный нечеткий поиск модов по названию"""
    if not mod_names_cache:
        logging.error("Кэш названий модов пуст!")
        return []
    
    if not isinstance(search_query, str):
        logging.warning(f"search_query не является строкой в advanced_fuzzy_search_mods: {type(search_query)}")
        search_query = str(search_query)
    
    processed_query = preprocess_search_query(search_query)
    logging.info(f"Обработанный запрос: '{search_query}' -> '{processed_query}'")
    
    if processed_query != search_query:
        try:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT m.id, m.title, m.description, m.slug, m.downloads
                    FROM mods m
                    WHERE m.title LIKE ? 
                    ORDER BY m.downloads DESC
                    LIMIT ?
                """, (f'%{processed_query}%', limit))
                exact_results = cursor.fetchall()
                if exact_results:
                    logging.info(f"Найдены точные совпадения для '{processed_query}'")
                    return [row['id'] for row in exact_results]
        except sqlite3.Error as e:
            logging.error(f"Ошибка при точном поиске: {e}")
    
    normalized_query = normalize_text(processed_query)
    all_mod_names = list(mod_names_cache.values())
    
    search_variants = [
        normalized_query,
        normalized_query.replace(' ', ''),
        normalized_query.replace(' ', '_'),
    ]
    
    if ' ' in normalized_query:
        words = normalized_query.split()
        if len(words) == 2:
            search_variants.append(f"{words[1]} {words[0]}")
            search_variants.append(words[0] + words[1])
            search_variants.append(words[1] + words[0])
    
    search_variants = list(set(search_variants))
    all_results = []
    
    for variant in search_variants:
        results = process.extract(
            variant, 
            all_mod_names, 
            scorer=fuzz.WRatio, 
            limit=limit * 2
        )
        all_results.extend(results)
    
    filtered_results = []
    seen_mods = set()
    
    for name, score, _ in all_results:
        threshold = 55 if ' ' in normalized_query else 60
        if score >= threshold:
            for mod_id, mod_name in mod_names_cache.items():
                if mod_name == name and mod_id not in seen_mods:
                    seen_mods.add(mod_id)
                    filtered_results.append((mod_id, score))
                    break
    
    filtered_results.sort(key=lambda x: x[1], reverse=True)
    return [mod_id for mod_id, score in filtered_results[:limit]]

@lru_cache(maxsize=100)
def search_mods_cached(search_query: str, limit: int = 5):
    """Кэшированная версия поиска модов"""
    cached_results = get_cached_search(search_query, limit)
    if cached_results is not None:
        return cached_results
    
    results = search_mods_in_db(search_query, limit)
    set_cached_search(search_query, limit, results)
    return results

def search_mods_in_db(search_query: str, limit: int = 50):
    """Поиск модов в базе данных по названию"""
    try:
        if not isinstance(search_query, str):
            logging.warning(f"search_query не является строкой: {type(search_query)}, значение: {search_query}")
            search_query = str(search_query)
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT DISTINCT m.id, m.title, m.description, m.slug, m.downloads
                FROM mods m
                WHERE m.title LIKE ? 
                ORDER BY m.downloads DESC
                LIMIT ?
            """, (f'%{search_query}%', limit))
            
            exact_results = cursor.fetchall()
            
            if exact_results:
                logging.info(f"Найдены точные совпадения для '{search_query}': {len(exact_results)} результатов")
                return [dict(row) for row in exact_results]
            
            logging.info(f"Точных совпадений для '{search_query}' не найдено, используем нечеткий поиск")
            fuzzy_mod_ids = advanced_fuzzy_search_mods(search_query, limit)
            
            if not fuzzy_mod_ids:
                logging.info(f"Нечеткий поиск не дал результатов для '{search_query}'")
                return []
            
            placeholders = ','.join('?' for _ in fuzzy_mod_ids)
            query = f"""
                SELECT DISTINCT m.id, m.title, m.description, m.slug, m.downloads
                FROM mods m
                WHERE m.id IN ({placeholders})
                ORDER BY m.downloads DESC
                LIMIT ?
            """
            
            logging.info(f"Выполняем запрос для нечеткого поиска: {query}")
            logging.info(f"Параметры запроса: {fuzzy_mod_ids + [limit]}")
            
            cursor.execute(query, fuzzy_mod_ids + [limit])
            fuzzy_results = cursor.fetchall()
            
            logging.info(f"Нечеткий поиск дал {len(fuzzy_results)} результатов для '{search_query}'")
            return [dict(row) for row in fuzzy_results]
            
    except sqlite3.Error as e:
        logging.error(f"Ошибка при поиске в базе данных: {e}")
        return []
    except Exception as e:
        logging.error(f"Неожиданная ошибка в search_mods_in_db: {e}")
        return []

def get_mod_versions(mod_id: str):
    """Получаем все версии мода с поддержкой разных версий Minecraft"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT v.id, v.version_number, v.loaders, v.game_versions, 
                       v.download_url, v.filename, v.published_at
                FROM versions v
                WHERE v.mod_id = ?
                ORDER BY v.published_at DESC
            """, (mod_id,))
            return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении версий мода: {e}")
        return []

def get_all_mod_loaders(mod_id: str):
    """Получаем все уникальные загрузчики для мода"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT v.loaders
                FROM versions v
                WHERE v.mod_id = ?
            """, (mod_id,))
            
            loaders = set()
            for row in cursor.fetchall():
                if row[0]:
                    loaders.update(row[0].split(','))
            
            return sorted(loaders)
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении загрузчиков мода: {e}")
        return []

def format_mod_message(mod_data, version_data=None, all_loaders=None):
    """Форматирование сообщения с информацией о моде"""
    mod_id = mod_data['id']
    title = mod_data['title']
    description = mod_data['description']
    slug = mod_data['slug']
    downloads = mod_data['downloads']
    
    if version_data:
        loaders = version_data['loaders']
        game_versions = version_data['game_versions']
        version_number = version_data['version_number']
        published_at = version_data['published_at']
        
        if loaders:
            loaders_list = loaders.split(',')
            loaders_str = ", ".join(loaders_list)
        else:
            loaders_str = "Не указано"
            
        if game_versions:
            mc_versions = game_versions.split(',')
            mc_versions_str = ", ".join(mc_versions)
        else:
            mc_versions_str = "Не указано"
            
        version_info = f"<b>Версия мода:</b> {version_number or 'Не указана'}\n"
        minecraft_versions_info = f"<b>Поддерживаемые версии Minecraft:</b> {mc_versions_str}\n"
        
    else:
        loaders = mod_data.get('loaders', '')
        game_versions = mod_data.get('game_versions', '')
        version_number = mod_data.get('version_number', '')
        published_at = mod_data.get('published_at', '')
        
        if all_loaders:
            loaders_str = ", ".join(all_loaders)
        else:
            if loaders:
                loaders_list = loaders.split(',')
                loaders_str = ", ".join(loaders_list)
            else:
                loaders_str = "Не указано"
                
        if game_versions:
            mc_versions = game_versions.split(',')
            mc_versions_str = ", ".join(mc_versions)
        else:
            mc_versions_str = "Не указано"
            
        version_info = f"<b>Последняя версия мода:</b> {version_number or 'Не указана'}\n"
        minecraft_versions_info = f"<b>Последняя поддерживаемая версия Minecraft:</b> {mc_versions_str}\n"
    
    if description and len(description) > 400:
        description = description[:400] + "..."
    
    message = (
        f"🎮 <b>Мод найден!</b>\n\n"
        f"<b>Название:</b> {title}\n"
        f"<b>Описание:</b> {description or 'Отсутствует'}\n"
        f"<b>Загрузок:</b> {downloads:,}\n\n"
        f"<b>Модлоадеры:</b> {loaders_str}\n"
        f"{version_info}"
        f"{minecraft_versions_info}\n"
        f"<b>Ссылка на Modrinth:</b> https://modrinth.com/mod/{slug}\n"
        f"<b>Дата публикации:</b> {published_at[:10] if published_at else 'Неизвестно'}"
    )
    
    return message

def create_mod_list_keyboard(mods, page=0, search_query="", page_size=10):
    """Создает клавиатуру со списком модов и пагинацией"""
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    
    total_pages = math.ceil(len(mods) / page_size)
    start_idx = page * page_size
    end_idx = min(start_idx + page_size, len(mods))
    
    for i in range(start_idx, end_idx):
        mod = mods[i]
        title = mod['title']
        if len(title) > 35:
            title = title[:32] + "..."
        
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(
                text=f"{title} ({mod['downloads']:,})",
                callback_data=f"show_mod:{mod['id']}:{search_query}:{page}"
            )
        ])
    
    pagination_buttons = []
    
    if page > 0:
        pagination_buttons.append(types.InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"mods_page:{page-1}:{search_query}"
        ))
    
    if end_idx < len(mods):
        pagination_buttons.append(types.InlineKeyboardButton(
            text="➡️ Вперед",
            callback_data=f"mods_page:{page+1}:{search_query}"
        ))
    
    if pagination_buttons:
        keyboard.inline_keyboard.append(pagination_buttons)
    
    keyboard.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="🔍 Новый поиск",
            callback_data="new_search"
        )
    ])
    
    return keyboard

def create_version_buttons(mod_id, versions, search_query="", mod_page=0, user_id=None):
    """Создаем кнопки для выбора версий Minecraft с загрузчиками и подпиской"""
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    
    # Проверяем, подписан ли пользователь на этот мод
    is_subscribed = False
    if user_id and user_id != BOT_ID:  # Используем BOT_ID вместо bot.id
        try:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id = ? AND mod_id = ?", 
                              (user_id, mod_id))
                is_subscribed = cursor.fetchone()[0] > 0
                logging.info(f"Проверка подписки пользователя {user_id} на мод {mod_id}: {is_subscribed}")
        except sqlite3.Error as e:
            logging.error(f"Ошибка при проверке подписки: {e}")
    
    version_buttons = {}
    for version in versions:
        if version['game_versions'] and version['loaders']:
            game_versions = version['game_versions'].split(',')
            loaders = version['loaders'].split(',')
            
            for mc_ver in game_versions:
                for loader in loaders:
                    key = f"{mc_ver}_{loader}"
                    if key not in version_buttons:
                        version_buttons[key] = {
                            'mc_version': mc_ver,
                            'loader': loader,
                            'version_id': version['id']
                        }
    
    buttons_per_row = 2
    row = []
    
    for i, key in enumerate(sorted(version_buttons.keys(), reverse=True)):
        if i > 0 and i % buttons_per_row == 0:
            keyboard.inline_keyboard.append(row)
            row = []
        
        version_info = version_buttons[key]
        button_text = f"MC {version_info['mc_version']} ({version_info['loader']})"
        row.append(types.InlineKeyboardButton(
            text=button_text,
            callback_data=f"mc_version:{mod_id}:{version_info['version_id']}:{version_info['mc_version']}:{version_info['loader']}:{search_query}:{mod_page}"
        ))
    
    if row:
        keyboard.inline_keyboard.append(row)
    
    subscribe_text = "❌ Отписаться" if is_subscribed else "🔔 Подписаться на обновления"
    subscribe_data = f"unsubscribe:{mod_id}:{search_query}:{mod_page}" if is_subscribed else f"subscribe:{mod_id}:{search_query}:{mod_page}"
    
    keyboard.inline_keyboard.append([
        types.InlineKeyboardButton(
            text=subscribe_text,
            callback_data=subscribe_data
        )
    ])
    
    keyboard.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="⬅️ Назад к списку модов",
            callback_data=f"back_to_list:{search_query}:{mod_page}"
        )
    ])
    
    keyboard.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="🌐 Открыть на Modrinth", 
            url=f"https://modrinth.com/mod/{mod_id}"
        )
    ])
    
    return keyboard

# Фоновая задача для проверки обновлений модов
async def check_mod_updates():
    """Фоновая задача для проверки обновлений модов"""
    try:
        while True:
            try:
                logging.info("Начинаем проверку обновлений модов...")
            
                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT DISTINCT mod_id FROM subscriptions")
                    mods_with_subs = [row[0] for row in cursor.fetchall()]
            
                logging.info(f"Проверяем обновления для {len(mods_with_subs)} модов с подписками")
            
                for mod_id in mods_with_subs:
                    try:
                        with sqlite3.connect(DB_PATH, timeout=30) as conn:
                            conn.row_factory = sqlite3.Row
                            cursor = conn.cursor()
                            cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
                            mod_data = cursor.fetchone()
                    
                        if not mod_data:
                            continue
                    
                        versions = get_mod_versions(mod_id)
                        if not versions:
                            continue
                    
                        latest_version = versions[0]['version_number']
                    
                        cursor.execute("SELECT last_version FROM subscriptions WHERE mod_id = ? LIMIT 1", (mod_id,))
                        last_known_version_row = cursor.fetchone()
                        last_known_version = last_known_version_row[0] if last_known_version_row else None
                    
                        if latest_version and latest_version != last_known_version:
                            logging.info(f"Обнаружено обновление для мода {mod_data['title']}: {last_known_version} -> {latest_version}")
                        
                            update_subscription_version(mod_id, latest_version)
                            subscribers = get_subscriptions_for_mod(mod_id)
                        
                            for sub in subscribers:
                                try:
                                    user_id = sub['user_id']
                                    message_text = (
                                        f"🔄 <b>Обновление мода!</b>\n\n"
                                        f"Мод <b>{mod_data['title']}</b> обновлен:\n"
                                        f"• Было: {last_known_version or 'Неизвестно'}\n"
                                        f"• Стало: {latest_version}\n\n"
                                        f"<a href=\"https://modrinth.com/mod/{mod_data['slug']}\">Страница мода на Modrinth</a>"
                                    )
                                
                                    await bot.send_message(
                                        chat_id=user_id,
                                        text=message_text,
                                        parse_mode="HTML",
                                        disable_web_page_preview=True
                                    )
                                
                                    await asyncio.sleep(0.1)
                                
                                except Exception as e:
                                    logging.error(f"Ошибка при отправке уведомления пользователю {sub['user_id']}: {e}")
                                    if "bot was blocked" in str(e).lower():
                                        remove_subscription(sub['user_id'], mod_id)
                
                    except Exception as e:
                        logging.error(f"Ошибка при проверке обновлений для мода {mod_id}: {e}")
                        continue
            
                logging.info("Проверка обновлений завершена. Следующая проверка через 1 час.")
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                logging.info("Задача проверки обновлений остановлена по запросу")
                break
            except Exception as e:
                logging.error(f"Ошибка в фоновой задаче проверки обновлений: {e}")
                await asyncio.sleep(300)
            except Exception as e:
                logging.error(f"Ошибка в фоновой задаче проверки обновлений: {e}")
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                logging.info("Задача проверки обновлений остановлена по запросу")
                break
            except Exception as e:
                logging.error(f"Ошибка в фоновой задаче проверки обновлений: {e}")
                await asyncio.sleep(300)
    except asyncio.CancelledError:
        logging.info("Задача проверки обновлений полностью остановлена")
    except Exception as e:
        logging.error(f"Неожиданная ошибка в фоновой задаче: {e}")
    

# Обработчики команд
@dp.message(Command("start", "help"))
async def cmd_start(message: Message):
    """Обработчик команд /start и /help"""
    # Регистрируем пользователя
    register_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        language_code=message.from_user.language_code
    )
    
    welcome_text = (
        "👋 <b>Добро пожаловать в Modrinth Search Bot!</b>\n\n"
        "Я помогу найти моды для Minecraft на Modrinth.\n\n"
        "🔍 <b>Просто напиши название мода</b>, который хочешь найти, "
        "и я покажу всю доступную информацию о нем!\n\n"
        "✨ <b>Новая функция:</b> Подписка на обновления модов!\n"
        "Теперь вы можете подписаться на мод и получать уведомления о новых версиях.\n\n"
    )
    
    # Создаем клавиатуру с основными командами
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔍 Поиск модов", switch_inline_query_current_chat="")],
        [types.InlineKeyboardButton(text="📋 Мои подписки", callback_data="mysubs_menu")],
        [types.InlineKeyboardButton(text="📊 Статистика", callback_data="stats_menu")]
    ])
    
    await message.answer(welcome_text, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(F.data == "mysubs_menu")
async def mysubs_menu_callback(callback: types.CallbackQuery):
    """Обработчик кнопки перехода к подпискам"""
    await cmd_my_subscriptions(callback.message)
    await callback.answer()

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Показывает статистику базы данных"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM mods")
            mods_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM versions")
            versions_count = cursor.fetchone()[0]
            
            users_count = get_users_count()
            
            cursor.execute("SELECT MAX(last_checked) FROM mods")
            last_updated = cursor.fetchone()[0]
            
            stats_message = (
                f"📊 <b>Статистика базы данных:</b>\n\n"
                f"<b>Модов в базе:</b> {mods_count}\n"
                f"<b>Версий в базе:</b> {versions_count}\n"
                f"<b>Пользователей бота:</b> {users_count}\n"
                f"<b>Последнее обновление:</b> {last_updated[:10] if last_updated else 'Неизвестно'}"
            )
            
            await message.answer(stats_message, parse_mode="HTML")
            
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении статистики: {e}")
        await message.answer("❌ Не удалось получить статистику базы данных")

@dp.message(Command("check_db"))
async def cmd_check_db(message: Message):
    """Проверка подключения к базе данных и содержимого"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM mods")
            mods_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM versions")
            versions_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT title FROM mods WHERE title LIKE '%greg%' OR title LIKE '%Greg%'")
            greg_mods = cursor.fetchall()
            
            response = (
                f"📊 <b>Проверка базы данных:</b>\n\n"
                f"<b>Модов в базе:</b> {mods_count}\n"
                f"<b>Версий в базе:</b> {versions_count}\n"
                f"<b>Моды с 'greg' в названии:</b> {len(greg_mods)}\n"
            )
            
            if greg_mods:
                response += "\n<b>Найденные моды:</b>\n"
                for i, mod in enumerate(greg_mods[:5]):
                    response += f"• {mod[0]}\n"
                if len(greg_mods) > 5:
                    response += f"• ... и еще {len(greg_mods) - 5}\n"
            
            await message.answer(response, parse_mode="HTML")
            
    except sqlite3.Error as e:
        logging.error(f"Ошибка при проверке базы данных: {e}")
        await message.answer("❌ Ошибка при подключении к базе данных")

@dp.message(Command("reload_cache"))
async def cmd_reload_cache(message: Message):
    """Перезагружает кэш поиска"""
    try:
        load_mod_names_cache()
        search_mods_cached.cache_clear()
        await message.answer("✅ Кэш поиска успешно перезагружен")
    except Exception as e:
        logging.error(f"Ошибка при перезагрузке кэша: {e}")
        await message.answer("❌ Не удалось перезагрузить кэш поиска")

@dp.message(Command("reload_aliases"))
async def cmd_reload_aliases(message: Message):
    """Перезагружает псевдонимы модов из файла"""
    try:
        load_mod_aliases()
        await message.answer(f"✅ Псевдонимы модов успешно перезагружены. Загружено {len(COMMON_MOD_ALIASES)} записей.")
    except Exception as e:
        logging.error(f"Ошибка при перезагрузке псевдонимов: {e}")
        await message.answer("❌ Не удалось перезагрузить псевдонимы модов")

@dp.message(Command("reset_cache"))
async def cmd_reset_cache(message: Message):
    """Полный сброс кэша"""
    try:
        global mod_names_cache
        mod_names_cache = {}
        load_mod_names_cache()
        
        search_mods_cached.cache_clear()
        
        if REDIS_AVAILABLE:
            redis_client.flushdb()
            logging.info("Кэш Redis полностью очищен")
        
        await message.answer("✅ Все кэши успешно сброшены и перезагружены")
    except Exception as e:
        logging.error(f"Ошибка при сбросе кэша: {e}")
        await message.answer("❌ Не удалось сбросить кэш")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    """Рассылка сообщения всем пользователям (только для администраторов)"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return
    
    broadcast_text = message.text.replace('/broadcast', '').strip()
    
    if not broadcast_text:
        await message.answer("❌ Укажите текст для рассылки после команды /broadcast")
        return
    
    users = get_all_users()
    total_users = len(users)
    
    if total_users == 0:
        await message.answer("❌ Нет пользователей для рассылки")
        return
    
    await message.answer(f"📨 Начинаю рассылку для {total_users} пользователей...")
    
    success_count = 0
    fail_count = 0
    
    for user_id in users:
        try:
            await bot.send_message(chat_id=user_id, text=broadcast_text, parse_mode="HTML")
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            logging.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
            fail_count += 1
    
    report_message = (
        f"📊 <b>Отчет о рассылке:</b>\n\n"
        f"• Всего пользователей: {total_users}\n"
        f"• Успешно отправлено: {success_count}\n"
        f"• Не удалось отправить: {fail_count}\n"
        f"• Текст сообщения: {broadcast_text[:100]}..."
    )
    
    await message.answer(report_message, parse_mode="HTML")

@dp.message(Command("user_stats"))
async def cmd_user_stats(message: Message):
    """Показывает статистику пользователей"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return
    
    users_count = get_users_count()
    
    stats_message = (
        f"👥 <b>Статистика пользователей:</b>\n\n"
        f"<b>Всего пользователей:</b> {users_count}\n\n"
        f"Для рассылки сообщения используйте команду:\n"
        f"<code>/broadcast Ваше сообщение</code>"
    )
    
    await message.answer(stats_message, parse_mode="HTML")

@dp.message(Command("mysubs"))
async def cmd_my_subscriptions(message: Message):
    """Показывает подписки пользователя с интерактивными кнопками"""
    user_id = message.from_user.id
    
    # Проверяем, что это не бот
    if user_id == BOT_ID:
        logging.warning("Бот запросил свои собственные подписки")
        await message.answer("Бот не может иметь подписки на моды")
        return
    
    try:
        subscriptions = get_user_subscriptions(user_id)
        
        if not subscriptions:
            await message.answer(
                "📋 У вас пока нет подписок на обновления модов.\n\n"
                "Чтобы подписаться, откройте информацию о моде и нажмите кнопку \"🔔 Подписаться на обновления\""
            )
            return
        
        # Логируем информацию о подписках для отладки
        logging.info(f"Пользователь {user_id} имеет {len(subscriptions)} подписок")
        for sub in subscriptions:
            logging.info(f"Подписка: {sub.get('mod_id')} - {sub.get('mod_title')}")
    
    except Exception as e:
        logging.error(f"Ошибка в cmd_my_subscriptions: {e}")
        await message.answer("❌ Произошла ошибка при получении списка подписок")
    
    # Формируем сообщение
    subs_text = "📋 <b>Ваши подписки на обновления модов:</b>\n\n"
    subs_text += "Выберите мод для управления подпиской:\n\n"
    
    # Создаем клавиатуру с кнопками
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    
    # Добавляем кнопки для каждого мода
    for i, sub in enumerate(subscriptions, 1):
        mod_name = sub.get('mod_title') or sub.get('mod_name', 'Неизвестный мод')
        # Обрезаем длинные названия
        if len(mod_name) > 30:
            mod_name = mod_name[:27] + "..."
        
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(
                text=f"{i}. {mod_name}",
                callback_data=f"subs_show:{sub['mod_id']}:0"
            )
        ])
    
    # Добавляем кнопки пагинации, если подписок много
    page_size = 10
    total_pages = (len(subscriptions) + page_size - 1) // page_size
    
    if total_pages > 1:
        pagination_buttons = []
        if total_pages > 1:
            pagination_buttons.append(types.InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"subs_page:0"  # Первая страница
            ))
        if total_pages > 1:
            pagination_buttons.append(types.InlineKeyboardButton(
                text="➡️ Вперед",
                callback_data=f"subs_page:1"  # Вторая страница
            ))
        
        keyboard.inline_keyboard.append(pagination_buttons)
    
    # Кнопка обновления списка
    keyboard.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="🔄 Обновить список",
            callback_data="subs_refresh"
        )
    ])
    
    await message.answer(subs_text, parse_mode="HTML", reply_markup=keyboard)

@dp.message(F.text.startswith("/unsubscribe_"))
async def cmd_unsubscribe(message: Message):
    """Обработчик команды отписки"""
    try:
        mod_id = message.text.replace("/unsubscribe_", "").strip()
        user_id = message.from_user.id
        
        if not mod_id:
            await message.answer("❌ Укажите ID мода для отписки. Например: /unsubscribe_abc123")
            return
        
        success = remove_subscription(user_id, mod_id)
        
        if success:
            await message.answer("✅ Вы успешно отписались от обновлений мода")
        else:
            await message.answer("❌ Не удалось найти подписку на этот мод")
    
    except Exception as e:
        logging.error(f"Ошибка при отписке: {e}")
        await message.answer("❌ Произошла ошибка при отписке")

@dp.message(Command("debug_subs"))
async def cmd_debug_subs(message: Message):
    """Команда для отладки подписок"""
    user_id = message.from_user.id
    
    # Показываем информацию о подписках пользователя
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            
            # Получаем все подписки пользователя
            cursor.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,))
            subscriptions = cursor.fetchall()
            
            # Получаем информацию о модах
            cursor.execute("""
                SELECT s.mod_id, m.title, s.mod_name 
                FROM subscriptions s 
                LEFT JOIN mods m ON s.mod_id = m.id 
                WHERE s.user_id = ?
            """, (user_id,))
            mods_info = cursor.fetchall()
            
            debug_text = (
                f"🔧 <b>Отладочная информация о подписках:</b>\n\n"
                f"<b>User ID:</b> {user_id}\n"
                f"<b>Всего подписок в базе:</b> {len(subscriptions)}\n\n"
                f"<b>Детальная информация:</b>\n"
            )
            
            for i, (mod_id, mod_title, mod_name) in enumerate(mods_info, 1):
                debug_text += f"{i}. ID: {mod_id}\n"
                debug_text += f"   Название в mods: {mod_title or 'Нет'}\n"
                debug_text += f"   Название в подписке: {mod_name}\n\n"
            
            await message.answer(debug_text, parse_mode="HTML")
            
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении отладочной информации: {e}")
        await message.answer("❌ Ошибка при получении информации о подписках")

@dp.message(F.text)
async def search_mods(message: Message):
    """Обработчик поиска модов"""
    if message.text.startswith('/'):
        return
    
    search_query = message.text.strip()
    logging.info(f"Получен запрос: '{search_query}' (тип: {type(search_query)})")
    
    if len(search_query) < 2:
        await message.answer("❌ Слишком короткий запрос. Введите хотя бы 2 символа.")
        return
    
    await message.chat.do("typing")
    
    mods = search_mods_cached(search_query, limit=50)
    
    logging.info(f"Результаты поиска для '{search_query}': {len(mods)} модов")
    
    if not mods:
        logging.info(f"По запросу '{search_query}' ничего не найдено")
        await message.answer(
            f"🔍 По запросу \"{search_query}\" ничего не найдено.\n\n"
            "Попробуй:\n"
            "• Проверить написание\n"
            "• Использовать английское название\n"
            "• Искать более популярные моды"
        )
        return
    
    result_message = (
        f"🔍 <b>Результаты поиска по запросу:</b> \"{search_query}\"\n\n"
        f"📦 <b>Найдено модов:</b> {len(mods)}\n\n"
        f"Выбери мод из списка ниже:"
    )
    
    keyboard = create_mod_list_keyboard(mods, 0, search_query)
    
    await message.answer(result_message, parse_mode="HTML", reply_markup=keyboard)

# Обработчики callback-запросов
@dp.callback_query(F.data.startswith("mods_page:"))
async def mods_page_callback(callback: types.CallbackQuery):
    """Обработчик переключения страниц со списком модов"""
    try:
        _, page, search_query = callback.data.split(":", 2)
        page = int(page)
        
        mods = search_mods_cached(search_query, limit=100)
        
        if not mods:
            await callback.answer("Моды не найдены")
            return
        
        result_message = (
            f"🔍 <b>Результаты поиска по запросу:</b> \"{search_query}\"\n\n"
            f"📦 <b>Найдено модов:</b> {len(mods)}\n\n"
            f"Выбери мод из списка ниже:"
        )
        
        keyboard = create_mod_list_keyboard(mods, page, search_query)
        
        await callback.message.edit_text(result_message, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    
    except Exception as e:
        logging.error(f"Ошибка в mods_page_callback: {e}")
        await callback.answer("Страница уже открыта")

@dp.callback_query(F.data.startswith("show_mod:"))
async def show_mod_callback(callback: types.CallbackQuery):
    """Обработчик выбора мода из списка"""
    try:
        _, mod_id, search_query, mod_page = callback.data.split(":", 3)
        mod_page = int(mod_page)
        user_id = callback.from_user.id
        
        # Добавляем проверку, что это не бот
        if user_id == BOT_ID:
            logging.warning("Бот пытается проверить подписки самого себя")
            await callback.answer("Ошибка: неверный пользователь")
            return
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
            mod_data = cursor.fetchone()
        
        if not mod_data:
            await callback.answer("Мод не найден")
            return
        
        versions = get_mod_versions(mod_id)
        
        if not versions:
            await callback.answer("Для этого мода нет версий")
            return
        
        all_loaders = get_all_mod_loaders(mod_id)
        mod_message = format_mod_message(mod_data, versions[0], all_loaders)
        
        user_subs = get_user_subscriptions(callback.from_user.id)
        is_subscribed = any(sub['mod_id'] == mod_id for sub in user_subs)
        
        if is_subscribed:
            mod_message += "\n\n🔔 Вы подписаны на обновления этого мода"
        
        keyboard = create_version_buttons(
            mod_id, versions, search_query, mod_page, callback.from_user.id
        )
        
        try:
            await callback.message.edit_text(mod_message, parse_mode="HTML", reply_markup=keyboard)
            await callback.answer()
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback.answer()
            else:
                raise e
    
    except Exception as e:
        logging.error(f"Ошибка в show_mod_callback: {e}")
        await callback.answer("Произошла ошибка при обработке запроса")

@dp.callback_query(F.data.startswith("mc_version:"))
async def mc_version_callback(callback: types.CallbackQuery):
    """Обработчик выбора версии Minecraft"""
    try:
        _, mod_id, version_id, mc_ver, loader, search_query, mod_page = callback.data.split(":", 6)
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
            mod_data = cursor.fetchone()
            cursor.execute("SELECT * FROM versions WHERE id = ?", (version_id,))
            version_data = cursor.fetchone()
        
        if not mod_data or not version_data:
            await callback.answer("Информация о моде не найдена")
            return
        
        mod_message = format_mod_message(mod_data, version_data)
        versions = get_mod_versions(mod_id)
        keyboard = create_version_buttons(mod_id, versions, search_query, mod_page)
        
        await callback.message.edit_text(mod_message, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer(f"Выбрана версия для Minecraft {mc_ver} с {loader}")
    
    except Exception as e:
        logging.error(f"Ошибка в mc_version_callback: {e}")
        await callback.answer("Страница уже открыта")

@dp.callback_query(F.data.startswith("back_to_list:"))
async def back_to_list_callback(callback: types.CallbackQuery):
    """Обработчик возврата к списку модов"""
    try:
        _, search_query, mod_page = callback.data.split(":", 2)
        mod_page = int(mod_page)
        
        mods = search_mods_cached(search_query, limit=100)
        
        if not mods:
            await callback.answer("Моды не найдены")
            return
        
        result_message = (
            f"🔍 <b>Результаты поиска по запросу:</b> \"{search_query}\"\n\n"
            f"📦 <b>Найдено модов:</b> {len(mods)}\n\n"
            f"Выбери мод из списка ниже:"
        )
        
        keyboard = create_mod_list_keyboard(mods, mod_page, search_query)
        
        await callback.message.edit_text(result_message, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    
    except Exception as e:
        logging.error(f"Ошибка в back_to_list_callback: {e}")
        await callback.answer("Страница уже открыта")

@dp.callback_query(F.data == "new_search")
async def new_search_callback(callback: types.CallbackQuery):
    """Обработчик начала нового поиска"""
    await callback.message.edit_text(
        "🔍 Введите название мода для поиска:",
        parse_mode="HTML",
        reply_markup=None
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("subscribe:"))
async def subscribe_callback(callback: types.CallbackQuery):
    """Обработчик подписки на мод"""
    try:
        _, mod_id, search_query, mod_page = callback.data.split(":", 3)
        user_id = callback.from_user.id
        
        # Проверяем, что это не бот
        if user_id == BOT_ID:
            logging.warning("Бот пытается подписаться сам на себя")
            await callback.answer("Ошибка: неверный пользователь")
            return
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT title FROM mods WHERE id = ?", (mod_id,))
            mod_data = cursor.fetchone()
        
        if not mod_data:
            await callback.answer("Мод не найден")
            return
        
        versions = get_mod_versions(mod_id)
        last_version = versions[0]['version_number'] if versions else None
        
        success = add_subscription(user_id, mod_id, mod_data['title'], last_version)
        
        if success:
            # Получаем обновленные данные для сообщения
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
                mod_data = cursor.fetchone()
            
            versions = get_mod_versions(mod_id)
            all_loaders = get_all_mod_loaders(mod_id)
            mod_message = format_mod_message(mod_data, versions[0], all_loaders)
            
            # Проверяем подписку для отображения статуса
            user_subs = get_user_subscriptions(user_id)
            is_subscribed = any(sub['mod_id'] == mod_id for sub in user_subs)
            if is_subscribed:
                mod_message += "\n\n🔔 Вы подписаны на обновления этого мода"
            
            keyboard = create_version_buttons(mod_id, versions, search_query, int(mod_page), user_id)
            
            await callback.message.edit_text(mod_message, parse_mode="HTML", reply_markup=keyboard)
            await callback.answer(f"Вы подписались на обновления {mod_data['title']}")
        else:
            await callback.answer("❌ Не удалось оформить подписку")
    
    except Exception as e:
        logging.error(f"Ошибка в subscribe_callback: {e}")
        await callback.answer("Произошла ошибка при подписке")

@dp.callback_query(F.data.startswith("subs_show:"))
async def subs_show_callback(callback: types.CallbackQuery):
    """Показывает информацию о моде из списка подписок"""
    try:
        _, mod_id, page = callback.data.split(":")
        page = int(page)
        user_id = callback.from_user.id
        
        # Получаем информацию о моде
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
            mod_data = cursor.fetchone()
        
        if not mod_data:
            await callback.answer("Мод не найден")
            return
        
        # Получаем все версии мода
        versions = get_mod_versions(mod_id)
        
        if not versions:
            await callback.answer("Для этого мода нет версий")
            return
        
        # Получаем все загрузчики для мода
        all_loaders = get_all_mod_loaders(mod_id)
        
        # Формируем сообщение
        mod_message = format_mod_message(mod_data, versions[0], all_loaders)
        mod_message += "\n\n📋 <b>Этот мод есть в ваших подписках</b>"
        
        # Создаем клавиатуру с кнопкой отписки
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
        
        # Кнопка отписки
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="❌ Отписаться от этого мода",
                callback_data=f"subs_unsubscribe:{mod_id}:{page}"
            )
        ])
        
        # Кнопка возврата к списку подписок
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="⬅️ Назад к списку подписок",
                callback_data=f"subs_back:{page}"
            )
        ])
        
        # Кнопка для перехода на Modrinth
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="🌐 Открыть на Modrinth", 
                url=f"https://modrinth.com/mod/{mod_data['slug']}"
            )
        ])
        
        await callback.message.edit_text(mod_message, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    
    except Exception as e:
        logging.error(f"Ошибка в subs_show_callback: {e}")
        await callback.answer("Произошла ошибка")

@dp.callback_query(F.data.startswith("subs_unsubscribe:"))
async def subs_unsubscribe_callback(callback: types.CallbackQuery):
    """Обработчик отписки из списка подписок"""
    try:
        _, mod_id, page = callback.data.split(":")
        page = int(page)
        user_id = callback.from_user.id
        
        # Получаем название мода для сообщения
        mod_name = "Неизвестный мод"
        try:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT title FROM mods WHERE id = ?", (mod_id,))
                result = cursor.fetchone()
                if result:
                    mod_name = result[0]
        except sqlite3.Error as e:
            logging.error(f"Ошибка при получении названия мода: {e}")
        
        # Удаляем подписку
        success = remove_subscription(user_id, mod_id)
        
        if success:
            # Показываем сообщение об успешной отписке
            await callback.message.edit_text(
                f"✅ Вы успешно отписались от обновлений мода \"{mod_name}\"\n\n"
                f"Нажмите кнопку ниже, чтобы вернуться к списку подписок.",
                parse_mode="HTML",
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(
                        text="⬅️ Вернуться к списку подписок",
                        callback_data=f"subs_back:{page}"
                    )]
                ])
            )
            await callback.answer(f"Отписались от {mod_name}")
        else:
            await callback.answer("❌ Не удалось отписаться")
    
    except Exception as e:
        logging.error(f"Ошибка в subs_unsubscribe_callback: {e}")
        await callback.answer("Произошла ошибка при отписке")

@dp.callback_query(F.data.startswith("subs_back:"))
async def subs_back_callback(callback: types.CallbackQuery):
    """Возврат к списку подписок"""
    try:
        # Просто вызываем команду mysubs заново
        await cmd_my_subscriptions(callback.message)
        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка в subs_back_callback: {e}")
        await callback.answer("Произошла ошибка")

@dp.callback_query(F.data == "subs_refresh")
async def subs_refresh_callback(callback: types.CallbackQuery):
    """Обновление списка подписок"""
    try:
        await cmd_my_subscriptions(callback.message)
        await callback.answer("✅ Список обновлен")
    except Exception as e:
        logging.error(f"Ошибка в subs_refresh_callback: {e}")
        await callback.answer("Произошла ошибка")

@dp.callback_query(F.data.startswith("subs_page:"))
async def subs_page_callback(callback: types.CallbackQuery):
    """Переключение страниц в списке подписок"""
    try:
        _, page = callback.data.split(":")
        page = int(page)
        user_id = callback.from_user.id
        
        subscriptions = get_user_subscriptions(user_id)
        
        if not subscriptions:
            await callback.answer("Нет подписок")
            return
        
        # Формируем сообщение
        subs_text = "📋 <b>Ваши подписки на обновления модов:</b>\n\n"
        subs_text += "Выберите мод для управления подпиской:\n\n"
        
        # Создаем клавиатуру с кнопками
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
        
        # Определяем, какие моды показывать на этой странице
        page_size = 10
        start_idx = page * page_size
        end_idx = min(start_idx + page_size, len(subscriptions))
        
        # Добавляем кнопки для модов на текущей странице
        for i in range(start_idx, end_idx):
            sub = subscriptions[i]
            mod_name = sub.get('mod_title') or sub.get('mod_name', 'Неизвестный мод')
            # Обрезаем длинные названия
            if len(mod_name) > 30:
                mod_name = mod_name[:27] + "..."
            
            keyboard.inline_keyboard.append([
                types.InlineKeyboardButton(
                    text=f"{i+1}. {mod_name}",
                    callback_data=f"subs_show:{sub['mod_id']}:{page}"
                )
            ])
        
        # Добавляем кнопки пагинации
        total_pages = (len(subscriptions) + page_size - 1) // page_size
        pagination_buttons = []
        
        if page > 0:
            pagination_buttons.append(types.InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"subs_page:{page-1}"
            ))
        
        if end_idx < len(subscriptions):
            pagination_buttons.append(types.InlineKeyboardButton(
                text="➡️ Вперед",
                callback_data=f"subs_page:{page+1}"
            ))
        
        if pagination_buttons:
            keyboard.inline_keyboard.append(pagination_buttons)
        
        # Кнопка обновления списка
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="🔄 Обновить список",
                callback_data="subs_refresh"
            )
        ])
        
        await callback.message.edit_text(subs_text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    
    except Exception as e:
        logging.error(f"Ошибка в subs_page_callback: {e}")
        await callback.answer("Произошла ошибка")

@dp.callback_query(F.data.startswith("unsubscribe:"))
async def unsubscribe_callback(callback: types.CallbackQuery):
    """Обработчик отписки от мода (из обычного просмотра мода)"""
    try:
        _, mod_id, search_query, mod_page = callback.data.split(":", 3)
        user_id = callback.from_user.id
        
        # Получаем название мода для сообщения
        mod_name = "Неизвестный мод"
        try:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT title FROM mods WHERE id = ?", (mod_id,))
                result = cursor.fetchone()
                if result:
                    mod_name = result[0]
        except sqlite3.Error as e:
            logging.error(f"Ошибка при получении названия мода: {e}")
        
        # Удаляем подписку
        success = remove_subscription(user_id, mod_id)
        
        if success:
            # Обновляем сообщение с информацией о моде
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
                mod_data = cursor.fetchone()
            
            versions = get_mod_versions(mod_id)
            all_loaders = get_all_mod_loaders(mod_id)
            mod_message = format_mod_message(mod_data, versions[0], all_loaders)
            
            # Добавляем сообщение об отписке
            mod_message += "\n\n❌ Вы отписались от обновлений этого мода"
            
            # Создаем клавиатуру с кнопкой подписки
            keyboard = create_version_buttons(mod_id, versions, search_query, int(mod_page), user_id)
            
            await callback.message.edit_text(mod_message, parse_mode="HTML", reply_markup=keyboard)
            await callback.answer(f"Отписались от {mod_name}")
        else:
            await callback.answer("❌ Не удалось отписаться")
    
    except Exception as e:
        logging.error(f"Ошибка в unsubscribe_callback: {e}")
        await callback.answer("Произошла ошибка при отписке")

import signal

async def shutdown(signal, loop, update_task):
    """Обработчик сигналов завершения"""
    logging.info(f"Получен сигнал {signal}, начинаем остановку...")
    
    # Отменяем все задачи
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    
    # Ждем завершения задач
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    
    # Останавливаем event loop
    loop.stop()

async def graceful_shutdown():
    """Корректное завершение работы всех компонентов"""
    logging.info("Начинаем корректное завершение работы...")
    
    # 1. Останавливаем polling
    try:
        await dp.stop_polling()
        logging.info("Polling остановлен")
    except Exception as e:
        logging.error(f"Ошибка при остановке polling: {e}")
    
    # 2. Закрываем сессию бота
    try:
        await bot.session.close()
        logging.info("Сессия бота закрыта")
    except Exception as e:
        logging.error(f"Ошибка при закрытии сессии бота: {e}")
    
    # 3. Закрываем Redis соединение, если оно есть
    if REDIS_AVAILABLE and redis_client:
        try:
            redis_client.close()
            logging.info("Соединение с Redis закрыто")
        except Exception as e:
            logging.error(f"Ошибка при закрытии Redis: {e}")
    
    logging.info("Все компоненты корректно остановлены")

# ... (предыдущий код остается без изменений) ...

async def main():
    """Основная функция запуска бота"""
    logging.info("Запуск бота...")
    
    init_subscriptions_table()
    
    # Создаем фоновую задачу
    update_task = asyncio.create_task(check_mod_updates())
    
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logging.info("Работа бота прервана")
    except Exception as e:
        logging.error(f"Ошибка в основном цикле бота: {e}")
    finally:
        # Останавливаем фоновую задачу
        if not update_task.done():
            update_task.cancel()
            try:
                await update_task
            except asyncio.CancelledError:
                logging.info("Фоновая задача проверки обновлений остановлена")
            except Exception as e:
                logging.error(f"Ошибка при остановке фоновой задачи: {e}")
        
        # Закрываем сессию бота
        try:
            await bot.session.close()
            logging.info("Сессия бота закрыта")
        except Exception as e:
            logging.error(f"Ошибка при закрытии сессии бота: {e}")

if __name__ == "__main__":
    try:
        # Простой запуск с asyncio.run()
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен пользователем")
    except Exception as e:
        logging.error(f"Неожиданная ошибка: {e}")
    finally:
        logging.info("Работа бота завершена")