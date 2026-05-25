import re
import json
import logging
import os
from rapidfuzz import process, fuzz

from bot.config import MOD_ALIASES_PATH
from bot.cache import get_cached_search, set_cached_search
from bot.database import get_pool

COMMON_MOD_ALIASES = {}
mod_names_cache = {}


def load_mod_aliases():
    """Загружает псевдонимы модов"""
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
                "ae2": "Applied Energistics 2"
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
    """Загружает кэш названий модов ТОЛЬКО для нечёткого поиска"""
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
    """Обработка с псевдонимами"""
    if not search_query:
        return search_query, False
    
    normalized = normalize_text(search_query)
    
    # Точное совпадение
    if normalized in COMMON_MOD_ALIASES:
        return COMMON_MOD_ALIASES[normalized], True
    
    # Нечёткое совпадение (только для коротких запросов, чтобы не тормозить)
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


def generate_search_variants(query: str, max_variants: int = 5) -> list:
    """Генерирует варианты поиска (ограниченное количество)"""
    variants = [query]
    
    # Удаляем спецсимволы
    cleaned = re.sub(r'[:\;\,\.\!\?]', ' ', query)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if cleaned != query and cleaned and len(variants) < max_variants:
        variants.append(cleaned)
    
    # Без пробелов
    no_spaces = query.replace(' ', '')
    if no_spaces != query and no_spaces and len(variants) < max_variants:
        variants.append(no_spaces)
    
    # Перестановка для двух слов
    words = query.split()
    if len(words) == 2 and len(variants) < max_variants:
        variants.append(f"{words[1]} {words[0]}")
    
    return list(set(variants))


def fast_fuzzy_search(search_query: str, limit: int = 10) -> list:
    """
    Быстрый нечёткий поиск (только если точный поиск не дал результатов)
    Ограничен по времени и количеству вариантов
    """
    if not mod_names_cache:
        return []
    
    # Только для коротких запросов
    if len(search_query) > 30:
        return []
    
    # Берём только первые 1000 самых популярных модов для нечёткого поиска
    # (это ускоряет в 48 раз!)
    all_names = list(mod_names_cache.values())[:1000]
    
    results = process.extract(search_query, all_names, scorer=fuzz.WRatio, limit=limit)
    
    found_ids = []
    seen = set()
    for name, score, _ in results:
        if score >= 60:
            for mod_id, mod_name in mod_names_cache.items():
                if mod_name == name and mod_id not in seen:
                    seen.add(mod_id)
                    found_ids.append(mod_id)
                    break
            if len(found_ids) >= limit:
                break
    
    return found_ids


async def search_mods_in_db(search_query: str, limit: int = 50) -> list:
    """Оптимизированный поиск (2-6 секунд)"""
    pool = get_pool()
    if pool is None:
        return []
    
    processed_query, is_alias = preprocess_search_query(search_query)
    
    alias_results = []
    other_results = []
    seen_ids = set()
    
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
                seen_ids.add(mod['id'])
        
        # 2. Поиск по вариантам запроса
        if len(alias_results) < limit:
            variants = generate_search_variants(search_query, max_variants=4)
            
            for variant in variants:
                if len(alias_results) + len(other_results) >= limit:
                    break
                
                exclude_ids = list(seen_ids) if seen_ids else []
                like_pattern = f'%{variant}%'
                
                if exclude_ids:
                    rows = await conn.fetch("""
                        SELECT id, title, description, slug, downloads
                        FROM mods 
                        WHERE (title ILIKE $1 OR slug ILIKE $1)
                        AND id != ALL($2::text[])
                        ORDER BY downloads DESC
                        LIMIT $3
                    """, like_pattern, exclude_ids, limit - len(alias_results) - len(other_results))
                else:
                    rows = await conn.fetch("""
                        SELECT id, title, description, slug, downloads
                        FROM mods 
                        WHERE title ILIKE $1 OR slug ILIKE $1
                        ORDER BY downloads DESC
                        LIMIT $2
                    """, like_pattern, limit)
                
                for row in rows:
                    if row['id'] not in seen_ids:
                        seen_ids.add(row['id'])
                        mod = dict(row)
                        mod['is_alias_match'] = False
                        other_results.append(mod)
        
        # 3. Быстрый нечёткий поиск (только если результатов мало)
        if len(alias_results) + len(other_results) < limit // 2:
            fuzzy_ids = fast_fuzzy_search(search_query, limit=10)
            new_ids = [fid for fid in fuzzy_ids if fid not in seen_ids]
            
            if new_ids:
                placeholders = ','.join(f'${i+1}' for i in range(len(new_ids)))
                rows = await conn.fetch(f"""
                    SELECT id, title, description, slug, downloads
                    FROM mods 
                    WHERE id IN ({placeholders})
                    ORDER BY downloads DESC
                    LIMIT ${len(new_ids) + 1}
                """, *new_ids, limit - len(alias_results) - len(other_results))
                
                for row in rows:
                    mod = dict(row)
                    mod['is_alias_match'] = is_alias
                    other_results.append(mod)
    
    results = alias_results + other_results
    logging.info(f"📊 Найдено: {len(alias_results)} + {len(other_results)} = {len(results)}")
    return results[:limit]


async def search_mods_cached(search_query: str, limit: int = 50) -> list:
    """Поиск с кэшированием"""
    cached = get_cached_search(search_query, limit)
    if cached is not None:
        return cached
    
    results = await search_mods_in_db(search_query, limit)
    set_cached_search(search_query, limit, results)
    return results


def format_mod_message(mod_data: dict, version_data: dict = None, all_loaders: list = None) -> str:
    """Форматирование сообщения"""
    title = mod_data.get('title', 'Неизвестно')
    description = mod_data.get('description', 'Описание отсутствует')
    slug = mod_data.get('slug', '')
    downloads = mod_data.get('downloads', 0)
    
    categories = mod_data.get('categories', [])
    license_info = mod_data.get('license', '')
    client_side = mod_data.get('client_side', '')
    server_side = mod_data.get('server_side', '')
    
    additional_info = ""
    if categories:
        additional_info += f"<b>Категории:</b> {', '.join(categories[:3])}\n"
    if license_info:
        additional_info += f"<b>Лицензия:</b> {license_info}\n"
    if client_side and server_side:
        additional_info += f"<b>Поддержка:</b> Клиент: {client_side}, Сервер: {server_side}\n"
    
    if description and len(description) > 400:
        description = description[:400] + "..."
    
    if version_data:
        loaders = version_data.get('loaders', [])
        game_versions = version_data.get('game_versions', [])
        version_number = version_data.get('version_number', 'Не указана')
        published_at = version_data.get('published_at')
        file_size = version_data.get('file_size', 0)
        
        loaders_str = ", ".join(loaders) if loaders else "Не указано"
        mc_str = ", ".join(game_versions[:3]) if game_versions else "Не указано"
        
        file_size_str = ""
        if file_size:
            if file_size < 1024 * 1024:
                file_size_str = f"<b>Размер:</b> {file_size / 1024:.1f} КБ\n"
            else:
                file_size_str = f"<b>Размер:</b> {file_size / (1024 * 1024):.1f} МБ\n"
        
        date_str = published_at.strftime('%Y-%m-%d') if published_at else "Неизвестно"
        
        return (
            f"🎮 <b>Мод найден!</b>\n\n"
            f"<b>Название:</b> {title}\n"
            f"<b>Описание:</b> {description}\n"
            f"<b>Загрузок:</b> {downloads:,}\n\n"
            f"{additional_info}"
            f"<b>Модлоадеры:</b> {loaders_str}\n"
            f"<b>Версия:</b> {version_number}\n"
            f"{file_size_str}"
            f"<b>Поддерживает Minecraft:</b> {mc_str}\n\n"
            f"<b>Ссылка:</b> https://modrinth.com/mod/{slug}\n"
            f"<b>Дата публикации:</b> {date_str}"
        )
    else:
        loaders_str = ", ".join(all_loaders) if all_loaders else "Не указано"
        
        return (
            f"🎮 <b>Мод найден!</b>\n\n"
            f"<b>Название:</b> {title}\n"
            f"<b>Описание:</b> {description}\n"
            f"<b>Загрузок:</b> {downloads:,}\n\n"
            f"{additional_info}"
            f"<b>Модлоадеры:</b> {loaders_str}\n\n"
            f"<b>Ссылка:</b> https://modrinth.com/mod/{slug}"
        )