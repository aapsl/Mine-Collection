import logging
import math
import sqlite3
from aiogram import types

from bot.config import DB_PATH

from .database import get_user_subscriptions

import re

def sanitize_callback_data(text: str, max_length: int = 50) -> str:
    """Очищает текст для использования в callback_data"""
    if not text:
        return ""
    # Заменяем недопустимые символы
    text = re.sub(r'[^a-zA-Z0-9_\-\s]', '', text)
    # Убираем множественные пробелы
    text = re.sub(r'\s+', ' ', text)
    # Обрезаем до максимальной длины
    return text.strip()[:max_length]

def create_mod_list_keyboard(mods, page=0, search_query="", page_size=10):  # Изменили page_size с 10 на 20
    """Создает клавиатуру со списком модов и пагинацией"""
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    
    total_pages = math.ceil(len(mods) / page_size)
    start_idx = page * page_size
    end_idx = min(start_idx + page_size, len(mods))
    
    # Очищаем search_query для callback_data
    safe_search_query = sanitize_callback_data(search_query)
    
    for i in range(start_idx, end_idx):
        mod = mods[i]
        title = mod['title']
        
        # Добавляем звездочку к результатам, найденным по псевдониму
        if mod.get('is_alias_match', False):
            title = "⭐ " + title
        
        if len(title) > 35:
            title = title[:32] + "..."
        
        # Создаем безопасный callback_data
        callback_data = f"show_mod:{mod['id']}:{safe_search_query}:{page}"
        if len(callback_data) > 64:  # Ограничение Telegram
            callback_data = f"show_mod:{mod['id']}:::{page}"  # Упрощаем если слишком длинный
        
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(
                text=f"{title} ({mod['downloads']:,})",
                callback_data=callback_data
            )
        ])
    
    pagination_buttons = []
    
    if page > 0:
        pagination_buttons.append(types.InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"mods_page:{page-1}:{safe_search_query}"
        ))
    
    if end_idx < len(mods):
        pagination_buttons.append(types.InlineKeyboardButton(
            text="➡️ Вперед",
            callback_data=f"mods_page:{page+1}:{safe_search_query}"
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

def create_version_buttons(mod_id, versions, search_query="", mod_page=0, version_page=0, user_id=None, bot_id=None):
    """Создаем кнопки для выбора версий Minecraft с загрузчиками и подпиской"""
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    
    # Очищаем search_query для callback_data
    safe_search_query = sanitize_callback_data(search_query)
    
    # Проверяем, подписан ли пользователь на этот мод
    is_subscribed = False
    if user_id and user_id != bot_id:
        try:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id = ? AND mod_id = ?", 
                              (user_id, mod_id))
                is_subscribed = cursor.fetchone()[0] > 0
        except sqlite3.Error as e:
            logging.error(f"Ошибка при проверке подписки: {e}")
    
    # Определяем, нужно ли использовать пагинацию
    total_versions = len(versions)
    use_pagination = total_versions > 50
    
    logging.info(f"Мод {mod_id}: всего версий = {total_versions}, использовать пагинацию = {use_pagination}")
    
    if use_pagination:
        VERSIONS_PER_PAGE = 10
        total_pages = max(1, (total_versions + VERSIONS_PER_PAGE - 1) // VERSIONS_PER_PAGE)
        
        # Обеспечиваем, чтобы version_page был в допустимых пределах
        version_page = max(0, min(version_page, total_pages - 1))
        
        # Получаем версии для текущей страницы
        start_idx = version_page * VERSIONS_PER_PAGE
        end_idx = min(start_idx + VERSIONS_PER_PAGE, total_versions)
        page_versions = versions[start_idx:end_idx]
        
        logging.info(f"Пагинация: страница {version_page+1}/{total_pages}, версии {start_idx+1}-{end_idx} из {total_versions}")
    else:
        # Если версий <= 50, показываем ВСЕ версии
        page_versions = versions
        total_pages = 1
        version_page = 0
        logging.info(f"Без пагинации: показываем все {total_versions} версий")
    
    # Создаем кнопки для КАЖДОЙ версии отдельно (не группируем)
    buttons_per_row = 2
    row = []
    skipped_count = 0
    
    for i, version in enumerate(page_versions):
        if version.get('game_versions') and version.get('loaders'):
            game_versions = version['game_versions'].split(',')
            loaders = version['loaders'].split(',')
            
            # Берем первую версию Minecraft и первый лоадер для отображения
            mc_ver = game_versions[0] if game_versions else "Unknown"
            loader = loaders[0] if loaders else "Unknown"
            
            # Формируем текст кнопки
            version_number = version.get('version_number', 'Unknown')
            button_text = f"MC {mc_ver} ({loader})"
            
            # Ограничиваем длину текста кнопки
            if len(button_text) > 30:
                button_text = button_text[:27] + "..."
            
            # Создаем безопасный callback_data
            callback_data = f"mc_version:{mod_id}:{version['id']}:{mc_ver}:{loader}:{safe_search_query}:{mod_page}:{version_page}"
            if len(callback_data) > 64:
                callback_data = f"mc_version:{mod_id}:{version['id']}:::{safe_search_query}:{mod_page}:{version_page}"
            
            # Добавляем кнопку в ряд
            row.append(types.InlineKeyboardButton(
                text=button_text,
                callback_data=callback_data
            ))
            
            # Если ряд заполнен, добавляем его в клавиатуру
            if len(row) >= buttons_per_row:
                keyboard.inline_keyboard.append(row)
                row = []
        else:
            skipped_count += 1
    
    # Добавляем оставшиеся кнопки, если они есть
    if row:
        keyboard.inline_keyboard.append(row)
    
    logging.info(f"Мод {mod_id}: создано {len(keyboard.inline_keyboard) * buttons_per_row - (buttons_per_row - len(row)) if row else len(keyboard.inline_keyboard) * buttons_per_row} кнопок, пропущено {skipped_count} версий (без game_versions или loaders)")
    
    # Показываем пагинацию только если есть более одной страницы и используем пагинацию
    if use_pagination and total_pages > 1:
        pagination_buttons = []
        
        if version_page > 0:
            pagination_buttons.append(types.InlineKeyboardButton(
                text="⬅️ Версии",
                callback_data=f"ver_page:{mod_id}:{version_page-1}:{safe_search_query}:{mod_page}"
            ))
        
        pagination_buttons.append(types.InlineKeyboardButton(
            text=f"Стр. {version_page+1}/{total_pages}",
            callback_data="no_op"  # Заглушка, ничего не делает
        ))
        
        if version_page < total_pages - 1:
            pagination_buttons.append(types.InlineKeyboardButton(
                text="Версии ➡️",
                callback_data=f"ver_page:{mod_id}:{version_page+1}:{safe_search_query}:{mod_page}"
            ))
        
        keyboard.inline_keyboard.append(pagination_buttons)
    
    # Кнопка подписки/отписки
    subscribe_text = "❌ Отписаться" if is_subscribed else "🔔 Подписаться на обновления"
    subscribe_data = f"unsubscribe:{mod_id}:{safe_search_query}:{mod_page}:{version_page}" if is_subscribed else f"subscribe:{mod_id}:{safe_search_query}:{mod_page}:{version_page}"
    
    keyboard.inline_keyboard.append([
        types.InlineKeyboardButton(
            text=subscribe_text,
            callback_data=subscribe_data
        )
    ])
    
    # Кнопка возврата к списку модов
    keyboard.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="⬅️ Назад к списку модов",
            callback_data=f"back_to_list:{safe_search_query}:{mod_page}"
        )
    ])
    
    # Кнопка перехода на Modrinth
    keyboard.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="🌐 Все версии на Modrinth", 
            url=f"https://modrinth.com/mod/{mod_id}/versions"
        )
    ])
    
    return keyboard

def create_subscriptions_keyboard(subscriptions, page=0, page_size=10):
    """Создает клавиатуру для списка подписок"""
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
    
    total_pages = math.ceil(len(subscriptions) / page_size)
    start_idx = page * page_size
    end_idx = min(start_idx + page_size, len(subscriptions))
    
    for i in range(start_idx, end_idx):
        sub = subscriptions[i]
        mod_name = sub.get('mod_title') or sub.get('mod_name', 'Неизвестный мод')
        if len(mod_name) > 30:
            mod_name = mod_name[:27] + "..."
        
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(
                text=f"{i+1}. {mod_name}",
                callback_data=f"subs_show:{sub['mod_id']}:{page}"
            )
        ])
    
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
    
    # Добавляем кнопки обновления и выхода в главное меню
    keyboard.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="🔄 Обновить список",
            callback_data="subs_refresh"
        )
    ])
    
    keyboard.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="🏠 Выход в главное меню",
            callback_data="main_menu"
        )
    ])
    
    return keyboard
