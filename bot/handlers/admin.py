import asyncio
import logging
import asyncpg
from aiogram import types
from aiogram.filters import Command
from aiogram.types import Message

import bot
from bot.config import ADMIN_IDS
from bot.database import get_all_users, get_users_count, get_mod_stats, pool
from bot.utils import load_mod_aliases, load_mod_names_cache
from bot.cache import clear_cache

async def cmd_stats(message: Message):
    """
    Показывает статистику базы данных.

    Args:
        message (aiogram.types.Message): Сообщение, вызвавшее команду.

    Raises:
        Exception: В случае ошибки при получении статистики базы данных.
    """

    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return
    
    
    logging.info(f"Пользователь {message.from_user.id} вызвал команду /stats")

    try: 
        stats = await get_mod_stats()
        users_count = await get_users_count()
        
        stats_message = (
            f"📊 <b>Статистика базы данных:</b>\n\n"
            f"<b>Модов в базе:</b> {stats.get('mods_count', 0)}\n"
            f"<b>Версий в базе:</b> {stats.get('versions_count', 0)}\n"
            f"<b>Пользователей бота:</b> {users_count}\n"
            f"<b>Последнее обновление:</b> {stats.get('last_updated', 'Неизвестно')[:10] if stats.get('last_updated') else 'Неизвестно'}"
        )
        
        await message.answer(stats_message, parse_mode="HTML")
        
    except Exception as e:
        logging.error(f"Ошибка при получении статистики: {e}")
        await message.answer("❌ Не удалось получить статистику базы данных")

async def cmd_check_db(message: Message): 
    """Проверка подключения к базе данных и содержимого"""
    logging.info(f"Пользователь {message.from_user.id} запросил проверку БД. ADMIN_IDS: {ADMIN_IDS}")
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return
    
    from bot.database import pool
    if pool is None:
        await message.answer("❌ База данных не инициализирована")
        return

    try:
        stats = await get_mod_stats()
        users_count = await get_users_count()
        
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT title FROM mods WHERE title ILIKE '%greg%' OR title ILIKE '%Greg%'")
            greg_mods = [row['title'] for row in rows]
        
        response = (
            f"📊 <b>Проверка базы данных:</b>\n\n"
            f"<b>Модов в базе:</b> {stats.get('mods_count', 0)}\n"
            f"<b>Версий в базе:</b> {stats.get('versions_count', 0)}\n"
            f"<b>Пользователей бота:</b> {users_count}\n"
            f"<b>Моды с 'greg' в названии:</b> {len(greg_mods)}\n"
        )
        
        if greg_mods:
            response += "\n<b>Найденные моды:</b>\n"
            for i, mod in enumerate(greg_mods[:5]):
                response += f"• {mod}\n"
            if len(greg_mods) > 5:
                response += f"• ... и еще {len(greg_mods) - 5}\n"
        
        await message.answer(response, parse_mode="HTML")
        
    except Exception as e: 
        logging.error(f"Ошибка при проверке базы данных: {e}")
        await message.answer("❌ Ошибка при подключении к базе данных")

async def cmd_reload_cache(message: Message):
    """Перезагружает кэш поиска"""
    user_id = message.from_user.id
    chat_id = message.chat.id

    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return

    try:
        await bot.utils.load_mod_names_cache()
        from bot.utils import search_mods_cached
        bot.utils.search_mods_cached.cache_clear()
        await message.answer("✅ Кэш поиска успешно перезагружен")
    except Exception as e:
        logging.error(f"Ошибка при перезагрузке кэша: {e}")
        await message.answer("❌ Не удалось перезагрузить кэш поиска")

async def cmd_reload_aliases(message: Message):
    """Перезагружает псевдонимы модов из файла"""
    user_id = message.from_user.id
    chat_id = message.chat.id

    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return
    
    try:
        load_mod_aliases()
        from bot.utils import COMMON_MOD_ALIASES
        await message.answer(f"✅ Псевдонимы модов успешно перезагружены. Загружено {len(COMMON_MOD_ALIASES)} записей.")
    except Exception as e:
        logging.error(f"Ошибка при перезагрузке псевдонимов: {e}")
        await message.answer("❌ Не удалось перезагрузить псевдонимы модов")

async def cmd_reset_cache(message: Message):
    """Полный сброс кэша"""
    user_id = message.from_user.id
    chat_id = message.chat.id

    if user_id not in ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return
    
    try:
        import bot.utils
        bot.utils.mod_names_cache.clear()
        await bot.utils.load_mod_names_cache()
        bot.utils.search_mods_cached.cache_clear()
        
        if clear_cache():
            logging.info("Кэш Redis полностью очищен")
        
        await message.answer("✅ Все кэши успешно сброшены и перезагружены")
    except Exception as e:
        logging.error(f"Ошибка при сбросе кэша: {e}")
        await message.answer("❌ Не удалось сбросить кэш")

async def cmd_broadcast(message: Message, bot):
    """Рассылка сообщения всем пользователям (только для администраторов)"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id, "❌ У вас нет прав для выполнения этой команды")
        return
    
    # Получаем текст сообщения из команды
    command_parts = message.text.split(' ', 1)
    if len(command_parts) < 2:
        await bot.send_message(chat_id, "❌ Укажите текст для рассылки после команды /broadcast")
        return
    
    broadcast_text = command_parts[1].strip()
    
    if not broadcast_text:
        await bot.send_message(chat_id, "❌ Укажите текст для рассылки после команды /broadcast")
        return
    
    users = await get_all_users()
    total_users = len(users)
    
    if total_users == 0:
        await bot.send_message(chat_id, "❌ Нет пользователей для рассылки")
        return
    
    await bot.send_message(chat_id, f"📨 Начинаю рассылку для {total_users} пользователей...")
    
    success_count = 0
    fail_count = 0
    
    for user_id in users:
        try:
            await bot.send_message(chat_id=user_id, text=broadcast_text)
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
    
    await bot.send_message(chat_id, report_message, parse_mode="HTML")

async def cmd_user_stats(user_id: int, chat_id: int, bot):
    """Показывает статистику пользователей"""
    if user_id not in ADMIN_IDS:
        await bot.send_message(
            chat_id=chat_id,
            text="❌ У вас нет прав для выполнения этой команды"
        )
        return
    
    users_count = await get_users_count()
    
    stats_message = (
        f"👥 <b>Статистика пользователей:</b>\n\n"
        f"<b>Всего пользователей:</b> {users_count}\n\n"
        f"Для рассылки сообщения используйте команду:\n"
        f"<code>/broadcast Ваше сообщение</code>"
    )
    
    await bot.send_message(
        chat_id=chat_id,
        text=stats_message,
        parse_mode="HTML"
    )

async def cmd_check_mod(message: Message, bot):
    """Проверяет наличие мода в базе данных"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id, "❌ У вас нет прав для выполнения этой команды")
        return
    
    # Получаем название мода из команды
    command_parts = message.text.split(' ', 1)
    if len(command_parts) < 2:
        await bot.send_message(chat_id, "❌ Укажите название мода после команды /check_mod")
        return
    
    mod_name = command_parts[1].strip()
    
    if not mod_name:
        await bot.send_message(chat_id, "❌ Укажите название мода после команды /check_mod")
        return
    
    from bot.database import check_mod_exists
    exists = await check_mod_exists(mod_name)
    
    await bot.send_message(chat_id, f"Мод '{mod_name}' {'найден' if exists else 'не найден'} в базе данных")