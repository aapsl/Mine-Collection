import re
import json
import logging
import os
import time
from rapidfuzz import process, fuzz

from bot.config import MOD_ALIASES_PATH
from bot.cache import get_cached_search, set_cached_search
from bot.database import get_pool

COMMON_MOD_ALIASES = {}
mod_names_cache = {}


def load_mod_aliases():
    """Загружает псевдонимы модов из JSON файла"""
    global COMMON_MOD_ALIASES
    try:
        if not os.path.exists(MOD_ALIASES_PATH):
            example_aliases = {
                "jei": "Just Enough Items",
                "just enough items": "Just Enough Items",
                "sodium": "Sodium",
                "lithium": "Lithium",
                "create": "Create",
                "aeronautics": "Create Aeronautics",
                "create aeronautics": "Create Aeronautics",
                "ae2": "Applied Energistics 2",
                "applied energistics": "Applied Energistics 2",
                "rei": "Roughly Enough Items",
                "roughly enough items": "Roughly Enough Items",
                "jade": "Jade",
                "waila": "Jade",
                "the one probe": "The One Probe",
                "top": "The One Probe",
                "xaeros": "Xaero's Minimap",
                "xaero": "Xaero's Minimap",
                "minimap": "Xaero's Minimap"
            }
            with open(MOD_ALIASES_PATH, 'w', encoding='utf-8') as f:
                json.dump(example_aliases, f, ensure_ascii=False, indent=2)
            COMMON_MOD_ALIASES = example_aliases
        else:
            with open(MOD_ALIASES_PATH, 'r', encoding='utf-8') as f:
                COMMON_MOD_ALIASES = json.load(f)
        logging.info(f"✅ Загружено {len(COMMON_MOD_ALIASES)} псевдонимов")
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        COMMON_MOD_ALIASES = {}


async def load_mod_names_cache():
    """Загружает все названия модов в кэш"""
    global mod_names_cache
    pool = get_pool()
    if pool is None:
        return
    
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, title FROM mods")
            mod_names_cache = {row['id']: row['title'] for row in rows}
        logging.info(f"✅ Загружено {len(mod_names_cache)} модов")
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        mod_names_cache = {}


def normalize_text(text: str) -> str:
    """Нормализация текста"""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def preprocess_search_query(search_query: str):
    """Обработка запроса с псевдонимами"""
    if not search_query:
        return search_query, False
    
    normalized = normalize_text(search_query)
    
    # Точное совпадение
    if normalized in COMMON_MOD_ALIASES:
        return COMMON_MOD_ALIASES[normalized], True
    
    # Нечёткое совпадение (только для коротких запросов)
    if len(normalized) < 20:
        best_match = None
        best_score = 0
        for alias, full_name in COMMON_MOD_ALIASES.items():
            score = fuzz.ratio(normalized, alias)
            if score > 75 and score > best_score:
                best_score = score
                best_match = full_name
        
        if best_match:
            return best_match, True
    
    return search_query, False


async def search_mods_in_db(search_query: str, limit: int = 50) -> list:
    """Поиск модов в базе данных"""
    pool = get_pool()
    if pool is None:
        return []
    
    start_time = time.time()
    processed_query, is_alias = preprocess_search_query(search_query)
    
    alias_results = []
    other_results = []
    
    async with pool.acquire() as conn:
        # 1. Поиск по псевдониму
        if is_alias:
            rows = await conn.fetch("""
                SELECT id, title, description, slug, downloads
                FROM mods 
                WHERE title ILIKE $1
                ORDER BY downloads DESC
                LIMIT $2
            """, f'%{processed_query}%', limit)
            
            for row in rows:
                mod = dict(row)
                mod['is_alias_match'] = True
                alias_results.append(mod)
        
        # 2. Поиск по оригинальному запросу
        if len(alias_results) < limit:
            like_pattern = f'%{search_query}%'
            exclude_ids = [m['id'] for m in alias_results]
            
            if exclude_ids:
                rows = await conn.fetch("""
                    SELECT id, title, description, slug, downloads
                    FROM mods 
                    WHERE (title ILIKE $1 OR slug ILIKE $1)
                    AND id != ALL($2::text[])
                    ORDER BY downloads DESC
                    LIMIT $3
                """, like_pattern, exclude_ids, limit - len(alias_results))
            else:
                rows = await conn.fetch("""
                    SELECT id, title, description, slug, downloads
                    FROM mods 
                    WHERE title ILIKE $1 OR slug ILIKE $1
                    ORDER BY downloads DESC
                    LIMIT $2
                """, like_pattern, limit)
            
            for row in rows:
                mod = dict(row)
                mod['is_alias_match'] = False
                other_results.append(mod)
    
    results = alias_results + other_results
    elapsed = (time.time() - start_time) * 1000
    logging.info(f"📊 Поиск '{search_query}': {len(alias_results)} псевдоним + {len(other_results)} других = {len(results)} ({elapsed:.0f} мс)")
    
    return results[:limit]


async def search_mods_cached(search_query: str, limit: int = 50) -> list:
    """Поиск с кэшированием"""
    cached = get_cached_search(search_query, limit)
    if cached is not None:
        return cached
    
    results = await search_mods_in_db(search_query, limit)
    set_cached_search(search_query, limit, results)
    return results


def format_mod_message(mod_data: dict, version_data: dict = None, all_loaders: list = None, total_versions: int = 0) -> str:
    """Форматирование сообщения о моде (данные в столбик)"""
    title = mod_data.get('title', 'Неизвестно')
    description = mod_data.get('description', 'Описание отсутствует')
    slug = mod_data.get('slug', '')
    downloads = mod_data.get('downloads', 0)
    
    # Категории
    categories = mod_data.get('categories', [])
    categories_str = ", ".join(categories[:3]) if categories else "Не указаны"
    if len(categories) > 3:
        categories_str += f" +{len(categories) - 3}"
    
    # Лицензия
    license_info = mod_data.get('license', '')
    if not license_info:
        license_str = "Не указана"
    elif license_info.startswith("LicenseRef-"):
        license_str = license_info.replace("LicenseRef-", "").replace("-", " ")
    else:
        license_str = license_info
    
    # Поддержка клиент/сервер
    client_side = mod_data.get('client_side', '')
    server_side = mod_data.get('server_side', '')
    
    client_str = "требуется" if client_side == 'required' else "опционально" if client_side == 'optional' else "не поддерживается"
    server_str = "требуется" if server_side == 'required' else "опционально" if server_side == 'optional' else "не поддерживается"
    
    # Эмодзи для лицензии
    license_emoji = "🔓" if "MIT" in license_str or "LGPL" in license_str or "Apache" in license_str else "🔒"
    
    # Обрезаем описание
    if description and len(description) > 300:
        description = description[:297] + "..."
    
    if version_data:
        version_number = version_data.get('version_number', 'Не указана')
        published_at = version_data.get('published_at')
        file_size = version_data.get('file_size', 0)
        version_type = version_data.get('version_type', 'release')
        
        # Тип версии
        type_emoji = "🟢"
        type_name = "Релиз"
        if version_type == 'beta':
            type_emoji = "🔵"
            type_name = "Бета"
        elif version_type == 'alpha':
            type_emoji = "🟣"
            type_name = "Альфа"
        
        # Размер файла
        if file_size:
            if file_size < 1024 * 1024:
                size_str = f"{file_size / 1024:.1f} КБ"
            else:
                size_str = f"{file_size / (1024 * 1024):.1f} МБ"
        else:
            size_str = "Неизвестно"
        
        # Дата
        date_str = published_at.strftime('%Y-%m-%d') if published_at else "Неизвестно"
        
        return (
            f"🎮 <b>{title}</b>\n"
            f"└─ 📂 {categories_str}\n"
            f"└─ 📜 {license_str} {license_emoji}\n\n"
            f"📥 {downloads:,} загрузок  |  📦 {total_versions} версий\n\n"
            f"<i>{description}</i>\n\n"
            f"🔧 <b>Информация о версии:</b>\n"
            f"└─ 🏷️ {type_emoji} {type_name}\n"
            f"└─ 📌 {version_number}\n"
            f"└─ 📦 {size_str}\n"
            f"└─ 📅 {date_str}\n\n"
            f"🖥️ Клиент: {client_str}\n"
            f"🖧 Сервер: {server_str}\n\n"
            f"🔗 <a href='https://modrinth.com/mod/{slug}'>Открыть на Modrinth</a>"
        )
    else:
        return (
            f"🎮 <b>{title}</b>\n"
            f"└─ 📂 {categories_str}\n"
            f"└─ 📜 {license_str} {license_emoji}\n\n"
            f"📥 {downloads:,} загрузок  |  📦 {total_versions} версий\n\n"
            f"<i>{description}</i>\n\n"
            f"🖥️ Клиент: {client_str}\n"
            f"🖧 Сервер: {server_str}\n\n"
            f"🔗 <a href='https://modrinth.com/mod/{slug}'>Открыть на Modrinth</a>"
        )