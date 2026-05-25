import math
import re
from aiogram import types

def sanitize(text: str, max_len: int = 50) -> str:
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
    safe_query = sanitize(query)
    
    for i in range(start, end):
        m = mods[i]
        title = m['title'][:32] + "..." if len(m['title']) > 35 else m['title']
        
        if m.get('is_alias_match', False):
            title = "⭐ " + title
        
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
            text="Вперед ➡️",
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

def versions_keyboard(mod_id: str, versions: list, query: str, mod_page: int, 
                       ver_page: int = 0, is_subscribed: bool = False) -> types.InlineKeyboardMarkup:
    """Клавиатура выбора версии"""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[])
    safe_query = sanitize(query)
    
    total = len(versions)
    
    # Если нет версий, показываем сообщение
    if total == 0:
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="❌ Нет доступных версий",
                callback_data="noop"
            )
        ])
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"back:{safe_query}:{mod_page}"
            )
        ])
        return kb
    
    per_page = 10
    start = ver_page * per_page
    end = min(start + per_page, total)
    
    # Заголовок с количеством версий
    version_title = f"📦 Версии ({total})"
    if total > per_page:
        total_pages = (total + per_page - 1) // per_page
        version_title += f" [стр. {ver_page + 1}/{total_pages}]"
    
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(
            text=version_title,
            callback_data="noop"
        )
    ])
    
    # Кнопки версий (по 2 в ряд)
    row = []
    for v in versions[start:end]:
        mc = v['game_versions'][0] if v.get('game_versions') else "?"
        loader = v['loaders'][0] if v.get('loaders') else "?"
        text = f"MC {mc} ({loader})"
        
        # Добавляем эмодзи для beta/alpha
        version_type = v.get('version_type', 'release')
        if version_type == 'beta':
            text = f"🔵 {text}"
        elif version_type == 'alpha':
            text = f"🟣 {text}"
        
        row.append(types.InlineKeyboardButton(
            text=text[:30],
            callback_data=f"version:{mod_id}:{v['id']}:{safe_query}:{mod_page}:{ver_page}"
        ))
        if len(row) >= 2:
            kb.inline_keyboard.append(row)
            row = []
    if row:
        kb.inline_keyboard.append(row)
    
    # Пагинация версий
    if total > per_page:
        nav = []
        if ver_page > 0:
            nav.append(types.InlineKeyboardButton(
                text="⬅️ Предыдущие",
                callback_data=f"ver_page:{mod_id}:{ver_page-1}:{safe_query}:{mod_page}"
            ))
        if end < total:
            nav.append(types.InlineKeyboardButton(
                text="Следующие ➡️",
                callback_data=f"ver_page:{mod_id}:{ver_page+1}:{safe_query}:{mod_page}"
            ))
        if nav:
            kb.inline_keyboard.append(nav)
    
    # Подписка/отписка
    if is_subscribed:
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="❌ Отписаться",
                callback_data=f"unsub:{mod_id}:{safe_query}:{mod_page}:{ver_page}"
            )
        ])
    else:
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="🔔 Подписаться",
                callback_data=f"sub:{mod_id}:{safe_query}:{mod_page}:{ver_page}"
            )
        ])
    
    # Назад к списку
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="⬅️ Назад к списку",
            callback_data=f"back:{safe_query}:{mod_page}"
        )
    ])
    
    # Ссылка на Modrinth
    kb.inline_keyboard.append([
        types.InlineKeyboardButton(
            text="🌐 Все версии на Modrinth",
            url=f"https://modrinth.com/mod/{mod_id}/versions"
        )
    ])
    
    return kb

def subscriptions_keyboard(subs: list, page: int = 0, page_size: int = 10) -> types.InlineKeyboardMarkup:
    """Клавиатура списка подписок"""
    kb = types.InlineKeyboardMarkup(inline_keyboard=[])
    
    total = len(subs)
    start = page * page_size
    end = min(start + page_size, total)
    
    # Заголовок с информацией о странице
    if total > 0:
        title = f"📋 Ваши подписки ({total})"
        if total > page_size:
            total_pages = (total + page_size - 1) // page_size
            title += f" [стр. {page + 1}/{total_pages}]"
        
        kb.inline_keyboard.append([
            types.InlineKeyboardButton(text=title, callback_data="noop")
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
                text="Вперед ➡️",
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