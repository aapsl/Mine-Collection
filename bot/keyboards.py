import logging
import math
import re
from aiogram import types

def sanitize(text: str, max_len: int = 50) -> str:
    """Очищает текст для callback_data"""
    if not text:
        return ""
    text = re.sub(r'[^a-zA-Z0-9_\-]', '', text)
    return text[:max_len]


def mods_keyboard(mods: list, page: int, query: str, page_size: int = 10) -> types.InlineKeyboardMarkup:
    """Клавиатура списка модов"""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[])
    
    total = len(mods)
    start = page * page_size
    end = min(start + page_size, total)
    
    # Кодируем query для безопасной передачи
    import urllib.parse
    safe_query = urllib.parse.quote(query, safe='')
    
    for i in range(start, end):
        m = mods[i]
        title = m['title'][:32] + "..." if len(m['title']) > 35 else m['title']
        
        if m.get('is_alias_match', False):
            title = "⭐ " + title
        
        # ПЕРЕДАЁМ QUERY
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text=f"{title} ({m['downloads']:,})",
                callback_data=f"mod:{m['id']}:{safe_query}:{page}"
            )
        ])
    
    # Пагинация
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"page:{page-1}:{safe_query}"
        ))
    if end < total:
        nav.append(types.InlineKeyboardButton(
            text="Вперёд ➡️",
            callback_data=f"page:{page+1}:{safe_query}"
        ))
    if nav:
        kb.inline_keyboard.append(nav)
    
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="🔍 Новый поиск",
            callback_data="new_search"
        )
    ])
    
    return kb


def mod_details_keyboard(mod_id: str, query: str, mod_page: int, is_subscribed: bool = False, total_versions: int = 0, source: str = "search") -> types.InlineKeyboardMarkup:
    """Клавиатура для карточки мода"""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[])
    
    import urllib.parse
    logging.info(f"🔍 mod_details_keyboard: входной query = '{query}'")   # <--- ЭТА СТРОКА
    safe_query = urllib.parse.quote(query, safe='')

    # Кнопки действий
    action_row = []
    action_row.append(types.InlineKeyboardButton(
        text="📥 Скачать",
        callback_data=f"download_latest:{mod_id}"
    ))
    if total_versions > 0:
        action_row.append(types.InlineKeyboardButton(
            text=f"📦 Версии ({total_versions})",
            callback_data=f"show_versions:{mod_id}:{safe_query}:{mod_page}"
        ))
    kb.inline_keyboard.append(action_row)
    
    # Подписка/отписка
    if is_subscribed:
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="❌ Отписаться",
                callback_data=f"unsubscribe:{mod_id}:{safe_query}:{mod_page}:0"
            )
        ])
    else:
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="🔔 Подписаться",
                callback_data=f"subscribe:{mod_id}:{safe_query}:{mod_page}:0"
            )
        ])
    
    # Навигация
    if source == "subs":
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="⬅️ Назад к подпискам",
                callback_data=f"back_to_subs:{mod_page}"
            ),
            types.InlineKeyboardButton(
                text="🌐 Modrinth",
                url=f"https://modrinth.com/mod/{mod_id}"
            )
        ])
    else:
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="⬅️ Назад к списку",
                callback_data=f"back:{safe_query}:{mod_page}"
            ),
            types.InlineKeyboardButton(
                text="🌐 Modrinth",
                url=f"https://modrinth.com/mod/{mod_id}"
            )
        ])
    
    return kb

def version_detail_keyboard_subs(mod_id: str, version_id: str, version_number: str, download_url: str, subs_page: int, ver_page: int) -> types.InlineKeyboardMarkup:
    """Клавиатура для конкретной версии (из подписок)"""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[])
    
    MAX_SIZE = 50 * 1024 * 1024
    
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="📥 Скачать",
            callback_data=f"download_version:{version_id}"
        )
    ])
    
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="⬅️ Назад к версиям",
            callback_data=f"back_to_versions_subs:{mod_id}:{subs_page}:{ver_page}"
        ),
        types.InlineKeyboardButton(
            text="🌐 Modrinth",
            url=f"https://modrinth.com/mod/{mod_id}/version/{version_id}"
        )
    ])
    
    return kb


def versions_list_keyboard(mod_id: str, versions: list, query: str, mod_page: int, ver_page: int = 0) -> types.InlineKeyboardMarkup:
    """Клавиатура для списка версий (отдельное меню)"""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[])
    import urllib.parse
    safe_query = urllib.parse.quote(query, safe='')
    logging.info(f"versions_list_keyboard: исходный query = '{query}', закодированный = '{safe_query}'")
    
    total = len(versions)
    per_page = 8
    start = ver_page * per_page
    end = min(start + per_page, total)
    total_pages = (total + per_page - 1) // per_page
    
    # Заголовок с пагинацией
    title = f"📦 Версии ({total})"
    if total_pages > 1:
        title += f" • стр. {ver_page + 1}/{total_pages}"
    
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(
            text=title,
            callback_data="noop"
        )
    ])
    
    # ЛЕГЕНДА — теперь на КАЖДОЙ странице
    legend = "🟢 Релиз  |  🔵 Бета  |  🟣 Альфа"
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(
            text=legend,
            callback_data="noop"
        )
    ])
    
    # Список версий
    for v in versions[start:end]:
        version_number = v.get('version_number', '?')
        version_type = v.get('version_type', 'release')
        published_at = v.get('published_at')
        loaders = v.get('loaders', [])
        
        # Эмодзи для типа версии
        if version_type == 'beta':
            type_emoji = "🔵"
        elif version_type == 'alpha':
            type_emoji = "🟣"
        else:
            type_emoji = "🟢"
        
        # Информация о загрузчиках
        loader_icons = {"fabric": "🧵", "forge": "⚒️", "quilt": "🪡", "neoforge": "🔧"}
        loader_emoji = loader_icons.get(loaders[0].lower(), "⚙️") if loaders else "⚙️"
        
        # Дата
        date_str = ""
        if published_at:
            if hasattr(published_at, 'strftime'):
                date_str = f" 📅 {published_at.strftime('%Y-%m-%d')}"
        
        # Номер версии (сокращаем если длинный)
        display_version = version_number[:25] + "..." if len(version_number) > 25 else version_number
        
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text=f"{type_emoji} {display_version} {loader_emoji}{date_str}",
                callback_data=f"select_version:{mod_id}:{v['id']}:{safe_query}:{mod_page}:{ver_page}"
            )
        ])
    
    # Пагинация
    if total_pages > 1:
        nav = []
        if ver_page > 0:
            nav.append(types.InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"versions_page:{mod_id}:{ver_page-1}:{safe_query}:{mod_page}"
            ))
        if end < total:
            nav.append(types.InlineKeyboardButton(
                text="Вперёд ➡️",
                callback_data=f"versions_page:{mod_id}:{ver_page+1}:{safe_query}:{mod_page}"
            ))
        if nav:
            kb.inline_keyboard.append(nav)
    
    # Кнопка возврата к карточке мода
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="⬅️ Назад к моду",
            callback_data=f"back_to_mod:{mod_id}:{safe_query}:{mod_page}"
        )
    ])
    
    return kb

def versions_list_keyboard_subs(mod_id: str, versions: list, subs_page: int, ver_page: int = 0) -> types.InlineKeyboardMarkup:
    """Клавиатура для списка версий (из подписок)"""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[])
    
    total = len(versions)
    per_page = 8
    start = ver_page * per_page
    end = min(start + per_page, total)
    total_pages = (total + per_page - 1) // per_page
    
    # Заголовок с пагинацией
    title = f"📦 Версии ({total})"
    if total_pages > 1:
        title += f" • стр. {ver_page + 1}/{total_pages}"
    
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(text=title, callback_data="noop")
    ])
    
    # Легенда
    legend = "🟢 Релиз  |  🔵 Бета  |  🟣 Альфа"
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(text=legend, callback_data="noop")
    ])
    
    # Список версий
    for v in versions[start:end]:
        version_number = v.get('version_number', '?')
        version_type = v.get('version_type', 'release')
        published_at = v.get('published_at')
        loaders = v.get('loaders', [])
        
        if version_type == 'beta':
            type_emoji = "🔵"
        elif version_type == 'alpha':
            type_emoji = "🟣"
        else:
            type_emoji = "🟢"
        
        loader_icons = {"fabric": "🧵", "forge": "⚒️", "quilt": "🪡", "neoforge": "🔧"}
        loader_emoji = loader_icons.get(loaders[0].lower(), "⚙️") if loaders else "⚙️"
        
        date_str = ""
        if published_at:
            if hasattr(published_at, 'strftime'):
                date_str = f" 📅 {published_at.strftime('%Y-%m-%d')}"
        
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text=f"{type_emoji} {version_number} {loader_emoji}{date_str}",
                callback_data=f"select_version_subs:{mod_id}:{v['id']}:{subs_page}:{ver_page}"
            )
        ])
    
    # Пагинация
    if total_pages > 1:
        nav = []
        if ver_page > 0:
            nav.append(types.InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"versions_page_subs:{mod_id}:{ver_page-1}:{subs_page}"
            ))
        if end < total:
            nav.append(types.InlineKeyboardButton(
                text="Вперёд ➡️",
                callback_data=f"versions_page_subs:{mod_id}:{ver_page+1}:{subs_page}"
            ))
        if nav:
            kb.inline_keyboard.append(nav)
    
    # Кнопка возврата к карточке мода (в подписки)
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="⬅️ Назад к моду",
            callback_data=f"back_to_mod_subs:{mod_id}:{subs_page}"
        )
    ])
    
    return kb

def version_detail_keyboard(mod_id: str, version_id: str, version_number: str, download_url: str, query: str, mod_page: int, ver_page: int, file_size: int = 0) -> types.InlineKeyboardMarkup:
    """Клавиатура для конкретной версии"""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[])
    import urllib.parse
    safe_query = urllib.parse.quote(query, safe='')
    logging.info(f"version_detail_keyboard: исходный query = '{query}', закодированный = '{safe_query}'")
    
    MAX_SIZE = 50 * 1024 * 1024
    
    if file_size > MAX_SIZE:
        # Если файл больше 50 МБ, показываем только ссылку на Modrinth
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="🌐 Скачать с Modrinth",
                url=download_url
            )
        ])
    else:
        # Если файл меньше 50 МБ, показываем кнопку скачивания через бота
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="📥 Скачать",
                callback_data=f"download_version:{version_id}"
            )
        ])
    
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="⬅️ Назад к версиям",
            callback_data=f"back_to_versions:{mod_id}:{safe_query}:{mod_page}:{ver_page}"
        ),
        types.InlineKeyboardButton(
            text="🌐 Modrinth",
            url=f"https://modrinth.com/mod/{mod_id}/version/{version_id}"
        )
    ])
    
    return kb

def new_func(query):
    safe_query = sanitize(query)
    return safe_query


def subscriptions_keyboard(subs: list, page: int = 0, page_size: int = 10) -> types.InlineKeyboardMarkup:
    """Клавиатура списка подписок"""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[])
    
    total = len(subs)
    start = page * page_size
    end = min(start + page_size, total)
    
    if total > 0:
        title = f"📋 Ваши подписки ({total})"
        if total > page_size:
            total_pages = (total + page_size - 1) // page_size
            title += f" • стр. {page + 1}/{total_pages}"
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text=title,
                callback_data="noop"
            )
        ])
    
    for i in range(start, end):
        s = subs[i]
        name = s.get('mod_title', s.get('mod_name', 'Неизвестно'))
        name = name[:30] + "..." if len(name) > 33 else name
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text=f"{i+1}. {name}",
                callback_data=f"sub_show:{s['mod_id']}:{page}"
            )
        ])
    
    # Пагинация
    if total > page_size:
        nav = []
        if page > 0:
            nav.append(types.InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"subs_page:{page-1}"
            ))
        if end < total:
            nav.append(types.InlineKeyboardButton(
                text="Вперёд ➡️",
                callback_data=f"subs_page:{page+1}"
            ))
        if nav:
            kb.inline_keyboard.append(nav)
    
    # Кнопки управления
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="🔄 Обновить",
            callback_data="subs_refresh"
        ),
        types.InlineKeyboardButton(
            text="🏠 Главное меню",
            callback_data="main_menu"
        )
    ])
    
    return kb