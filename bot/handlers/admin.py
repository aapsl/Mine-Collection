import asyncio
import logging
import sqlite3
from aiogram import types
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import ADMIN_IDS, DB_PATH
from bot.database import get_all_users, get_users_count, get_mod_stats
from bot.utils import load_mod_aliases, load_mod_names_cache
from bot.cache import clear_cache

async def cmd_stats(user_id: int, chat_id: int, bot):
    """Показывает статистику базы данных"""
    logging.info(f"Пользователь {user_id} запросил статистику. ADMIN_IDS: {ADMIN_IDS}")
    
    if user_id not in ADMIN_IDS:
        logging.warning(f"Пользователь {user_id} не имеет прав администратора")
        await bot.send_message(chat_id, "❌ У вас нет прав для выполнения этой команды")
        return
    
    try:
        stats = get_mod_stats()
        users_count = get_users_count()
        
        stats_message = (
            f"📊 <b>Статистика базы данных:</b>\n\n"
            f"<b>Модов в базе:</b> {stats.get('mods_count', 0)}\n"
            f"<b>Версий в базе:</b> {stats.get('versions_count', 0)}\n"
            f"<b>Пользователей бота:</b> {users_count}\n"
            f"<b>Последнее обновление:</b> {stats.get('last_updated', 'Неизвестно')[:10] if stats.get('last_updated') else 'Неизвестно'}"
        )
        
        await bot.send_message(chat_id, text=stats_message, parse_mode="HTML")
        
    except Exception as e:
        logging.error(f"Ошибка при получении статистики: {e}")
        await bot.send_message(chat_id, "❌ Не удалось получить статистику базы данных")

async def cmd_check_db(user_id: int, chat_id: int, bot):
    """Проверка подключения к базе данных и содержимого"""
    logging.info(f"Пользователь {user_id} запросил проверку БД. ADMIN_IDS: {ADMIN_IDS}")
    
    if user_id not in ADMIN_IDS:
        logging.warning(f"Пользователь {user_id} не имеет прав администратора")
        await bot.send_message(
            chat_id=chat_id,
            text="❌ У вас нет прав для выполнения этой команды"
        )
        return
    
    try:
        stats = get_mod_stats()
        users_count = get_users_count()
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT title FROM mods WHERE title LIKE '%greg%' OR title LIKE '%Greg%'")
            greg_mods = cursor.fetchall()
        
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
                response += f"• {mod[0]}\n"
            if len(greg_mods) > 5:
                response += f"• ... и еще {len(greg_mods) - 5}\n"
        
        await bot.send_message(chat_id, response, parse_mode="HTML")
        
    except Exception as e:
        logging.error(f"Ошибка при проверке базы данных: {e}")
        await bot.send_message(chat_id, "❌ Ошибка при подключении к базе данных")

async def cmd_reload_cache(user_id: int, chat_id: int, bot):
    """Перезагружает кэш поиска"""
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id, "❌ У вас нет прав для выполнения этой команды")
        return
    
    try:
        load_mod_names_cache()
        from bot.utils import search_mods_cached
        search_mods_cached.cache_clear()
        await bot.send_message(chat_id, "✅ Кэш поиска успешно перезагружен")
    except Exception as e:
        logging.error(f"Ошибка при перезагрузке кэша: {e}")
        await bot.send_message(chat_id, "❌ Не удалось перезагрузить кэш поиска")

async def cmd_reload_aliases(user_id: int, chat_id: int, bot):
    """Перезагружает псевдонимы модов из файла"""
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id, "❌ У вас нет прав для выполнения этой команды")
        return
    
    try:
        load_mod_aliases()
        from bot.utils import COMMON_MOD_ALIASES
        await bot.send_message(chat_id, f"✅ Псевдонимы модов успешно перезагружены. Загружено {len(COMMON_MOD_ALIASES)} записей.")
    except Exception as e:
        logging.error(f"Ошибка при перезагрузке псевдонимов: {e}")
        await bot.send_message(chat_id, "❌ Не удалось перезагрузить псевдонимы модов")

async def cmd_reset_cache(user_id: int, chat_id: int, bot):
    """Полный сброс кэша"""
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id, "❌ У вас нет прав для выполнения этой команды")
        return
    
    try:
        from bot.utils import mod_names_cache, load_mod_names_cache
        mod_names_cache = {}
        load_mod_names_cache()
        
        from bot.utils import search_mods_cached
        search_mods_cached.cache_clear()
        
        if clear_cache():
            logging.info("Кэш Redis полностью очищен")
        
        await bot.send_message(chat_id, "✅ Все кэши успешно сброшены и перезагружены")
    except Exception as e:
        logging.error(f"Ошибка при сбросе кэша: {e}")
        await bot.send_message(chat_id, "❌ Не удалось сбросить кэш")

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
    
    users = get_all_users()
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
    
    users_count = get_users_count()
    
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
    exists = check_mod_exists(mod_name)
    
    await bot.send_message(chat_id, f"Мод '{mod_name}' {'найден' if exists else 'не найден'} в базе данных")