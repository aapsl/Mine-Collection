import logging
from aiogram import types, F
from aiogram.types import Message

from bot.utils import search_mods_cached
from bot.keyboards import create_mod_list_keyboard

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
    
    mods = search_mods_cached(search_query, limit=100)
    
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
    
    # Проверяем, использовался ли псевдоним
    from bot.utils import preprocess_search_query, COMMON_MOD_ALIASES
    processed_query = preprocess_search_query(search_query)
    used_alias = processed_query != search_query and search_query.lower() in COMMON_MOD_ALIASES
    
    # Считаем сколько результатов найдено по псевдониму
    alias_match_count = sum(1 for mod in mods if mod.get('is_alias_match', False))
    
    result_message = (
        f"🔍 <b>Результаты поиска по запросу:</b> \"{search_query}\"\n\n"
    )
    
    if used_alias:
        result_message += f"💡 <i>Использован псевдоним: \"{search_query}\" → \"{processed_query}\"</i>\n"
        result_message += f"⭐ <i>Найдено точных совпадений: {alias_match_count}</i>\n\n"
    
    result_message += f"📦 <b>Найдено модов:</b> {len(mods)}\n\n"
    result_message += "Выбери мод из списка ниже:"
    
    keyboard = create_mod_list_keyboard(mods, 0, search_query)
    
    await message.answer(result_message, parse_mode="HTML", reply_markup=keyboard)