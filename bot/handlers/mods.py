import logging
import sqlite3
from aiogram import types
from aiogram.exceptions import TelegramBadRequest

from bot.config import DB_PATH
from bot.database import get_mod_versions, get_all_mod_loaders
from bot.utils import format_mod_message
from bot.keyboards import create_mod_list_keyboard, create_version_buttons

async def mods_page_callback(callback: types.CallbackQuery, bot):
    """Обработчик переключения страниц со списком модов"""
    try:
        _, page, search_query = callback.data.split(":", 2)
        page = int(page)
        
        from bot.utils import search_mods_cached
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

async def show_mod_callback(callback: types.CallbackQuery, bot):
    """Обработчик выбора мода из списка"""
    try:
        parts = callback.data.split(":")
        if len(parts) < 4:
            await callback.answer("Неверный формат данных")
            return
            
        _, mod_id, search_query, mod_page = parts
        mod_page = int(mod_page)
        
        # Восстанавливаем оригинальный search_query
        search_query = search_query.replace('_', ' ')
        
        user_id = callback.from_user.id
        
        # Добавляем проверку, что это не бот
        if user_id == bot.id:
            logging.warning("Бот пытается проверить подписки самого себя")
            await callback.answer("Ошибка: неверный пользователь")
            return
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
            mod_row = cursor.fetchone()
        
        if not mod_row:
            await callback.answer("Мод не найден")
            return
        
        # Преобразуем Row объект в словарь
        mod_data = dict(mod_row)
        
        versions = get_mod_versions(mod_id) 
        
        if not versions:
            await callback.answer("Для этого мода нет версий")
            return
        
        # Добавляем информацию о количестве версий
        version_count = len(versions)
        
        # Получаем все загрузчики для мода
        all_loaders = get_all_mod_loaders(mod_id)
        
        # Формируем сообщение с информацией о количестве версий
        mod_message = format_mod_message(mod_data, versions[0], all_loaders)
        mod_message = mod_message.replace("🎮 <b>Мод найден!</b>", f"🎮 <b>Мод найден!</b>\n\n📦 <b>Всего версий:</b> {version_count}")
        
        from bot.database import get_user_subscriptions
        user_subs = get_user_subscriptions(callback.from_user.id)
        is_subscribed = any(sub['mod_id'] == mod_id for sub in user_subs)
        
        if is_subscribed:
            mod_message += "\n\n🔔 Вы подписаны на обновления этого мода"
        
        # Всегда начинаем с первой страницы версий
        keyboard = create_version_buttons(
            mod_id, versions, search_query, mod_page, 0, callback.from_user.id, bot.id
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

async def ver_page_callback(callback: types.CallbackQuery, bot):
    """Обработчик переключения страниц версий"""
    try:
        parts = callback.data.split(":")
        # Формат: ver_page:mod_id:version_page:search_query:mod_page
        if len(parts) < 5:
            await callback.answer("Неверный формат данных")
            return
            
        mod_id = parts[1]
        version_page = int(parts[2])
        search_query = parts[3]
        mod_page = int(parts[4])
        
        # Восстанавливаем оригинальный search_query
        search_query = search_query.replace('_', ' ')
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
            mod_row = cursor.fetchone()
        
        if not mod_row:
            await callback.answer("Мод не найден")
            return
        
        # Преобразуем Row объект в словарь
        mod_data = dict(mod_row)
        
        versions = get_mod_versions(mod_id)
        
        if not versions:
            await callback.answer("Для этого мода нет версий")
            return
        
        # Получаем все загрузчики для мода
        all_loaders = get_all_mod_loaders(mod_id)
        
        # Формируем сообщение
        mod_message = format_mod_message(mod_data, versions[0], all_loaders)
        
        from bot.database import get_user_subscriptions
        user_subs = get_user_subscriptions(callback.from_user.id)
        is_subscribed = any(sub['mod_id'] == mod_id for sub in user_subs)
        
        if is_subscribed:
            mod_message += "\n\n🔔 Вы подписаны на обновления этого мода"
        
        keyboard = create_version_buttons(
            mod_id, versions, search_query, mod_page, version_page, callback.from_user.id, bot.id
        )
        
        await callback.message.edit_text(mod_message, parse_mode="HTML", reply_markup=keyboard)
        
        # Проверяем, используется ли пагинация (версий больше 50)
        total_versions = len(versions)
        if total_versions > 50:
            total_pages = (total_versions + 9) // 10  # Округляем вверх
            await callback.answer(f"Страница версий {version_page + 1}/{total_pages}")
        else:
            await callback.answer()  # Без текста, если пагинация не используется
    
    except Exception as e:
        logging.error(f"Ошибка в ver_page_callback: {e}")
        await callback.answer("Произошла ошибка при переключении страницы")

async def mc_version_callback(callback: types.CallbackQuery, bot):
    """Обработчик выбора версии Minecraft"""
    try:
        parts = callback.data.split(":")
        # Формат: mc_version:mod_id:version_id:mc_ver:loader:search_query:mod_page:version_page
        if len(parts) < 8:
            await callback.answer("Неверный формат данных")
            return
            
        mod_id = parts[1]
        version_id = parts[2]
        mc_ver = parts[3]
        loader = parts[4]
        search_query = parts[5]
        mod_page = int(parts[6])
        version_page = int(parts[7])
        
        # Восстанавливаем оригинальный search_query
        search_query = search_query.replace('_', ' ')
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
            mod_row = cursor.fetchone()
            cursor.execute("SELECT * FROM versions WHERE id = ?", (version_id,))
            version_row = cursor.fetchone()
        
        if not mod_row or not version_row:
            await callback.answer("Информация о моде не найдена")
            return
        
        # Преобразуем Row объекты в словари
        mod_data = dict(mod_row)
        version_data = dict(version_row)
        
        versions = get_mod_versions(mod_id)
        
        # Сохраняем текущую страницу версий при обновлении клавиатуры
        keyboard = create_version_buttons(
            mod_id, versions, search_query, mod_page, version_page, callback.from_user.id, bot.id
        )
        
        mod_message = format_mod_message(mod_data, version_data)
        
        await callback.message.edit_text(mod_message, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer(f"Выбрана версия для Minecraft {mc_ver} с {loader}")
    
    except Exception as e:
        logging.error(f"Ошибка в mc_version_callback: {e}")
        await callback.answer("Страница уже открыта")

async def ver_page_callback(callback: types.CallbackQuery, bot):
    """Обработчик переключения страниц версий"""
    try:
        parts = callback.data.split(":")
        # Формат: ver_page:mod_id:version_page:search_query:mod_page
        if len(parts) < 5:
            await callback.answer("Неверный формат данных")
            return
            
        mod_id = parts[1]
        version_page = int(parts[2])
        search_query = parts[3]
        mod_page = int(parts[4])
        
        # Восстанавливаем оригинальный search_query
        search_query = search_query.replace('_', ' ')
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
            mod_row = cursor.fetchone()
        
        if not mod_row:
            await callback.answer("Мод не найден")
            return
        
        # Преобразуем Row объект в словарь
        mod_data = dict(mod_row)
        
        versions = get_mod_versions(mod_id)
        
        if not versions:
            await callback.answer("Для этого мода нет версий")
            return
        
        # Получаем все загрузчики для мода
        all_loaders = get_all_mod_loaders(mod_id)
        
        # Формируем сообщение
        mod_message = format_mod_message(mod_data, versions[0], all_loaders)
        
        from bot.database import get_user_subscriptions
        user_subs = get_user_subscriptions(callback.from_user.id)
        is_subscribed = any(sub['mod_id'] == mod_id for sub in user_subs)
        
        if is_subscribed:
            mod_message += "\n\n🔔 Вы подписаны на обновления этого мода"
        
        keyboard = create_version_buttons(
            mod_id, versions, search_query, mod_page, version_page, callback.from_user.id, bot.id
        )
        
        await callback.message.edit_text(mod_message, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer(f"Страница версий {version_page + 1}")
    
    except Exception as e:
        logging.error(f"Ошибка в ver_page_callback: {e}")
        await callback.answer("Произошла ошибка при переключении страницы")

async def back_to_list_callback(callback: types.CallbackQuery, bot):
    """Обработчик возврата к списку модов"""
    try:
        parts = callback.data.split(":")
        if len(parts) < 3:
            await callback.answer("Неверный формат данных")
            return
            
        _, search_query, mod_page = parts
        mod_page = int(mod_page)
        
        # Восстанавливаем оригинальный search_query
        search_query = search_query.replace('_', ':').replace('_', ';')
        
        from bot.utils import search_mods_cached
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

async def new_search_callback(callback: types.CallbackQuery):
    """Обработчик начала нового поиска"""
    await callback.message.edit_text(
        "🔍 Введите название мода для поиска:",
        parse_mode="HTML",
        reply_markup=None
    )
    await callback.answer()