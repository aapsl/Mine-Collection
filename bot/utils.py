import re
import json
import logging
import os
import sqlite3
from functools import lru_cache

from rapidfuzz import process, fuzz

from .config import MOD_ALIASES_PATH, DB_PATH
from .cache import get_cached_search, set_cached_search

# Глобальные переменные для кэшей
COMMON_MOD_ALIASES = {}
mod_names_cache = {}

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
            # Добавим отладочную информацию
            logging.info(f"Пример псевдонимов: {list(COMMON_MOD_ALIASES.items())[:3]}")
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

def advanced_fuzzy_search_mods(search_query: str, limit: int = 10):
    """Улучшенный нечеткий поиск модов по названию"""
    if not mod_names_cache:
        logging.error("Кэш названий модов пуст!")
        return []
    
    if not isinstance(search_query, str):
        logging.warning(f"search_query не является строкой в advanced_fuzzy_search_mods: {type(search_query)}")
        search_query = str(search_query)
    
    processed_query = preprocess_search_query(search_query)
    logging.info(f"Обработанный запрос: '{search_query}' -> '{processed_query}'")
    
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
    """Поиск модов в базе данных по названию с объединением результатов"""
    try:
        if not isinstance(search_query, str):
            logging.warning(f"search_query не является строкой: {type(search_query)}, значение: {search_query}")
            search_query = str(search_query)
        
        # Получаем обработанный запрос через псевдонимы
        processed_query = preprocess_search_query(search_query)
        is_alias_used = processed_query != search_query
        
        results = []
        
        # Всегда ищем по исходному запросу
        original_results = _search_by_query(search_query, limit * 2)
        
        # Если использовался псевдоним, ищем и по псевдониму
        if is_alias_used:
            logging.info(f"Использован псевдоним: '{search_query}' -> '{processed_query}'")
            
            # Ищем по псевдониму (полному названию)
            alias_results = _search_by_query(processed_query, limit * 2)
            
            # Помечаем результаты по псевдониму специальным флагом
            for mod in alias_results:
                mod['is_alias_match'] = True
            
            # Объединяем результаты, убирая дубликаты, но сохраняя приоритет псевдонима
            seen_ids = set()
            
            # Сначала добавляем результаты по псевдониму
            for mod in alias_results:
                if mod['id'] not in seen_ids:
                    results.append(mod)
                    seen_ids.add(mod['id'])
            
            # Затем добавляем результаты по исходному запросу
            for mod in original_results:
                if mod['id'] not in seen_ids:
                    mod['is_alias_match'] = False  # Помечаем как не псевдоним
                    results.append(mod)
                    seen_ids.add(mod['id'])
                    if len(results) >= limit:
                        break
        else:
            # Если псевдоним не использовался, используем только результаты по исходному запросу
            for mod in original_results:
                mod['is_alias_match'] = False
            results = original_results
        
        # Ограничиваем количество результатов
        results = results[:limit]
        
        logging.info(f"Найдено {len(results)} результатов для запроса '{search_query}'")
        return results
            
    except sqlite3.Error as e:
        logging.error(f"Ошибка при поиске в базе данных: {e}")
        return []
    except Exception as e:
        logging.error(f"Неожиданная ошибка в search_mods_in_db: {e}")
        return []

def _search_by_query(query: str, limit: int):
    """Вспомогательная функция для поиска по конкретному запросу"""
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Сначала проверяем точные совпадения
            cursor.execute("""
                SELECT DISTINCT m.id, m.title, m.description, m.slug, m.downloads
                FROM mods m
                WHERE m.title LIKE ? 
                ORDER BY m.downloads DESC
                LIMIT ?
            """, (f'%{query}%', limit))
            
            exact_results = cursor.fetchall()
            
            if exact_results:
                logging.info(f"Найдены точные совпадения для '{query}': {len(exact_results)} результатов")
                return [dict(row) for row in exact_results]
            
            logging.info(f"Точных совпадений для '{query}' не найдено, используем нечеткий поиск")
            fuzzy_mod_ids = advanced_fuzzy_search_mods(query, limit)
            
            if not fuzzy_mod_ids:
                logging.info(f"Нечеткий поиск не дал результатов для '{query}'")
                return []
            
            placeholders = ','.join('?' for _ in fuzzy_mod_ids)
            query_sql = f"""
                SELECT DISTINCT m.id, m.title, m.description, m.slug, m.downloads
                FROM mods m
                WHERE m.id IN ({placeholders})
                ORDER BY m.downloads DESC
                LIMIT ?
            """
            
            cursor.execute(query_sql, fuzzy_mod_ids + [limit])
            fuzzy_results = cursor.fetchall()
            
            logging.info(f"Нечеткий поиск дал {len(fuzzy_results)} результатов для '{query}'")
            return [dict(row) for row in fuzzy_results]
            
    except sqlite3.Error as e:
        logging.error(f"Ошибка при поиске в базе данных: {e}")
        return []
    except Exception as e:
        logging.error(f"Неожиданная ошибка в _search_by_query: {e}")
        return []

def format_mod_message(mod_data, version_data=None, all_loaders=None):
    """Форматирование сообщения с информацией о моде"""
    mod_id = mod_data['id']
    title = mod_data['title']
    description = mod_data['description']
    slug = mod_data['slug']
    downloads = mod_data['downloads']
    
    # Добавляем информацию о категориях и лицензии
    categories = mod_data.get('categories', '')
    license_info = mod_data.get('license', '')
    client_side = mod_data.get('client_side', '')
    server_side = mod_data.get('server_side', '')
    
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
    
    # Добавляем информацию о категориях и лицензии
    additional_info = ""
    if categories:
        additional_info += f"<b>Категории:</b> {categories}\n"
    if license_info:
        additional_info += f"<b>Лицензия:</b> {license_info}\n"
    
    # Добавляем информацию о поддержке клиент/сервер
    support_info = ""
    if client_side and server_side:
        support_info = f"<b>Поддержка:</b> Клиент: {client_side}, Сервер: {server_side}\n"
    
        # Добавляем информацию о размере файла и типе версии
    file_info = ""
    if version_data:
        file_size = version_data.get('file_size')
        version_type = version_data.get('version_type', 'release')
        
        if file_size:
            # Конвертируем байты в МБ
            file_size_mb = file_size / (1024 * 1024)
            file_info = f"<b>Размер файла:</b> {file_size_mb:.2f} МБ\n"
        
        if version_type and version_type != 'release':
            version_info = f"<b>Версия мода:</b> {version_number} ({version_type})\n"
    
    message = (
        f"🎮 <b>Мод найден!</b>\n\n"
        f"<b>Название:</b> {title}\n"
        f"<b>Описание:</b> {description or 'Отсутствует'}\n"
        f"<b>Загрузок:</b> {downloads:,}\n\n"
        f"{additional_info}"
        f"{support_info}"
        f"<b>Модлоадеры:</b> {loaders_str}\n"
        f"{version_info}"
        f"{file_info}"  # Добавляем информацию о размере файла
        f"{minecraft_versions_info}\n"
        f"<b>Ссылка на Modrinth:</b> https://modrinth.com/mod/{slug}\n"
        f"<b>Дата публикации:</b> {published_at[:10] if published_at else 'Неизвестно'}"
    )
    
    return message