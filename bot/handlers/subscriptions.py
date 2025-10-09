import logging
import sqlite3
from aiogram import types
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import ADMIN_IDS, DB_PATH
from bot.database import get_all_mod_loaders, get_mod_versions, get_user_subscriptions, remove_subscription, add_subscription
from bot.keyboards import create_subscriptions_keyboard, create_version_buttons
from bot.utils import format_mod_message

async def cmd_my_subscriptions(user_id: int, chat_id: int, bot):
    """Показывает подписки пользователя с интерактивными кнопками"""
    
    # Правильная проверка: сравниваем ID пользователя с ID бота
    if user_id == bot.id:
        logging.warning("Бот запросил свои собственные подписки")
        await bot.send_message(chat_id, "Бот не может иметь подписки на моды")
        return
    
    try:
        subscriptions = get_user_subscriptions(user_id)
        
        if not subscriptions:
            await bot.send_message(
                chat_id,
                "📋 У вас пока нет подписок на обновления модов.\n\n"
                "Чтобы подписаться, откройте информацию о моде и нажмите кнопку \"🔔 Подписаться на обновления\""
            )
            return
        
        logging.info(f"Пользователь {user_id} имеет {len(subscriptions)} подписок")
    
    except Exception as e:
        logging.error(f"Ошибка в cmd_my_subscriptions: {e}")
        await bot.send_message(chat_id, "❌ Произошла ошибка при получении списка подписок")
        return
    
    # Формируем сообщение
    subs_text = "📋 <b>Ваши подписки на обновления модов:</b>\n\n"
    subs_text += "Выберите мод для управления подпиской:\n\n"
    
    # Создаем клавиатуру с кнопками
    keyboard = create_subscriptions_keyboard(subscriptions, 0)
    
    await bot.send_message(chat_id, text=subs_text, parse_mode="HTML", reply_markup=keyboard)

async def cmd_unsubscribe(message: Message):
    """Обработчик команды отписки"""
    try:
        mod_id = message.text.replace("/unsubscribe_", "").strip()
        user_id = message.from_user.id
        
        if not mod_id:
            await message.answer("❌ Укажите ID мода для отписки. Например: /unsubscribe_abc123")
            return
        
        success = remove_subscription(user_id, mod_id)
        
        if success:
            await message.answer("✅ Вы успешно отписались от обновлений мода")
        else:
            await message.answer("❌ Не удалось найти подписку на этот мод")
    
    except Exception as e:
        logging.error(f"Ошибка при отписке: {e}")
        await message.answer("❌ Произошла ошибка при отписке")

async def cmd_debug_subs(user_id: int, chat_id: int, bot):
    """Команда для отладки подписок"""
    # Проверяем права администратора
    if user_id not in ADMIN_IDS:
        await bot.send_message(chat_id, "❌ У вас нет прав для выполнения этой команды")
        return

    # Показываем информацию о подписках пользователя
    try:
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            cursor = conn.cursor()
            
            # Получаем все подписки пользователя
            cursor.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,))
            subscriptions = cursor.fetchall()
            
            # Получаем информацию о модах
            cursor.execute("""
                SELECT s.mod_id, m.title, s.mod_name 
                FROM subscriptions s 
                LEFT JOIN mods m ON s.mod_id = m.id 
                WHERE s.user_id = ?
            """, (user_id,))
            mods_info = cursor.fetchall()
            
            debug_text = (
                f"🔧 <b>Отладочная информация о подписках:</b>\n\n"
                f"<b>User ID:</b> {user_id}\n"
                f"<b>Всего подписок в базе:</b> {len(subscriptions)}\n\n"
                f"<b>Детальная информация:</b>\n"
            )
            
            for i, (mod_id, mod_title, mod_name) in enumerate(mods_info, 1):
                debug_text += f"{i}. ID: {mod_id}\n"
                debug_text += f"   Название в mods: {mod_title or 'Нет'}\n"
                debug_text += f"   Название в подписке: {mod_name}\n\n"
            
            await bot.send_message(chat_id, debug_text, parse_mode="HTML")
            
    except sqlite3.Error as e:
        logging.error(f"Ошибка при получении отладочной информации: {e}")
        await bot.send_message(chat_id, "❌ Ошибка при получении информации о подписках")

async def subscribe_callback(callback: types.CallbackQuery, bot):
    """Обработчик подписки на мод"""
    try:
        parts = callback.data.split(":")
        # Новый формат: subscribe:mod_id:search_query:mod_page:version_page
        if len(parts) < 5:
            await callback.answer("Неверный формат данных")
            return
            
        mod_id = parts[1]
        search_query = parts[2]
        mod_page = int(parts[3])
        version_page = int(parts[4])
        
        # Остальной код без изменений...
        user_id = callback.from_user.id
        
        # Проверяем, что это не бот
        if user_id == bot.id:
            logging.warning("Бот пытается подписаться сам на себя")
            await callback.answer("Ошибка: неверный пользователь")
            return
        
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT title FROM mods WHERE id = ?", (mod_id,))
            mod_row = cursor.fetchone()
        
        if not mod_row:
            await callback.answer("Мод не найден")
            return
        
        # Преобразуем Row в словарь
        mod_data = dict(mod_row)
        
        versions = get_mod_versions(mod_id)
        last_version = versions[0]['version_number'] if versions else None
        
        success = add_subscription(user_id, mod_id, mod_data['title'], last_version)
        
        if success:
            # Получаем обновленные данные для сообщения
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
                mod_row = cursor.fetchone()
            
            # Преобразуем Row в словарь
            mod_data = dict(mod_row)
            
            versions = get_mod_versions(mod_id)
            all_loaders = get_all_mod_loaders(mod_id)
            mod_message = format_mod_message(mod_data, versions[0], all_loaders)
            
            # Проверяем подписку для отображения статуса
            user_subs = get_user_subscriptions(user_id)
            is_subscribed = any(sub['mod_id'] == mod_id for sub in user_subs)
            if is_subscribed:
                mod_message += "\n\n🔔 Вы подписаны на обновления этого мода"
            
            keyboard = create_version_buttons(mod_id, versions, search_query, mod_page, version_page, user_id, bot.id)
            
            await callback.message.edit_text(mod_message, parse_mode="HTML", reply_markup=keyboard)
            await callback.answer(f"Вы подписались на обновления {mod_data['title']}")
        else:
            await callback.answer("❌ Не удалось оформить подписку")
    
    except Exception as e:
        logging.error(f"Ошибка в subscribe_callback: {e}")
        await callback.answer("Произошла ошибка при подписке")

async def unsubscribe_callback(callback: types.CallbackQuery, bot):
    """Обработчик отписки от мода (из обычного просмотра мода)"""
    try:
        parts = callback.data.split(":")
        # Новый формат: unsubscribe:mod_id:search_query:mod_page:version_page
        if len(parts) < 5:
            await callback.answer("Неверный формат данных")
            return
            
        mod_id = parts[1]
        search_query = parts[2]
        mod_page = int(parts[3])
        version_page = int(parts[4])
        
        # Получаем название мода для сообщения
        mod_name = "Неизвестный мод"
        try:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT title FROM mods WHERE id = ?", (mod_id,))
                result = cursor.fetchone()
                if result:
                    mod_name = result[0]
        except sqlite3.Error as e:
            logging.error(f"Ошибка при получении названия мода: {e}")
        
        # Удаляем подписку
        success = remove_subscription(callback.from_user.id, mod_id)
        
        if success:
            # Обновляем сообщение с информацией о моде
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
                mod_row = cursor.fetchone()
            
            # Преобразуем Row в словарь
            mod_data = dict(mod_row)
            
            versions = get_mod_versions(mod_id)
            all_loaders = get_all_mod_loaders(mod_id)
            mod_message = format_mod_message(mod_data, versions[0], all_loaders)
            
            # Добавляем сообщение об отписке
            mod_message += "\n\n❌ Вы отписались от обновлений этого мода"
            
            # Создаем клавиатуру с кнопкой подписки
            keyboard = create_version_buttons(mod_id, versions, search_query, mod_page, version_page, callback.from_user.id, bot.id)
            
            await callback.message.edit_text(mod_message, parse_mode="HTML", reply_markup=keyboard)
            await callback.answer(f"Отписались от {mod_name}")
        else:
            await callback.answer("❌ Не удалось отписаться")
    
    except Exception as e:
        logging.error(f"Ошибка в unsubscribe_callback: {e}")
        await callback.answer("Произошла ошибка при отписке")

async def subs_show_callback(callback: types.CallbackQuery, bot):
    """Показывает информацию о моде из списка подписок"""
    try:
        _, mod_id, page = callback.data.split(":")
        page = int(page)
        user_id = callback.from_user.id
        
        # Получаем информацию о моде
        with sqlite3.connect(DB_PATH, timeout=30) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
            mod_row = cursor.fetchone()
        
        if not mod_row:
            await callback.answer("Мод не найден")
            return
        
        # Преобразуем Row в словарь
        mod_data = dict(mod_row)
        
        # Получаем все версии мода
        versions = get_mod_versions(mod_id)
        
        if not versions:
            await callback.answer("Для этого мода нет версий")
            return
        
        # Получаем все загрузчики для мода
        all_loaders = get_all_mod_loaders(mod_id)
        
        # Формируем сообщение
        mod_message = format_mod_message(mod_data, versions[0], all_loaders)
        mod_message += "\n\n📋 <b>Этот мод есть в ваших подписках</b>"
        
        # Создаем клавиатуру с кнопкой отписки
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
        
        # Кнопка отписки
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="❌ Отписаться от этого мода",
                callback_data=f"subs_unsubscribe:{mod_id}:{page}"
            )
        ])
        
        # Кнопка возврата к списку подписок
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="⬅️ Назад к списку подписок",
                callback_data=f"subs_back:{page}"
            )
        ])
        
        # Кнопка для перехода на Modrinth
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(
                text="🌐 Открыть на Modrinth", 
                url=f"https://modrinth.com/mod/{mod_data['slug']}"
            )
        ])
        
        await callback.message.edit_text(mod_message, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    
    except Exception as e:
        logging.error(f"Ошибка в subs_show_callback: {e}")
        await callback.answer("Произошла ошибка")

async def subs_unsubscribe_callback(callback: types.CallbackQuery, bot):
    """Обработчик отписки из списка подписок"""
    try:
        _, mod_id, page = callback.data.split(":")
        page = int(page)
        user_id = callback.from_user.id
        
        # Получаем название мода для сообщения
        mod_name = "Неизвестный мод"
        try:
            with sqlite3.connect(DB_PATH, timeout=30) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT title FROM mods WHERE id = ?", (mod_id,))
                result = cursor.fetchone()
                if result:
                    mod_name = result[0]
        except sqlite3.Error as e:
            logging.error(f"Ошибка при получении названия мода: {e}")
        
        # Удаляем подписку
        success = remove_subscription(user_id, mod_id)
        
        if success:
            # Показываем сообщение об успешной отписке
            await callback.message.edit_text(
                f"✅ Вы успешно отписались от обновлений мода \"{mod_name}\"\n\n"
                f"Нажмите кнопку ниже, чтобы вернуться к списку подписок.",
                parse_mode="HTML",
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(
                        text="⬅️ Вернуться к списку подписок",
                        callback_data=f"subs_back:{page}"
                    )]
                ])
            )
            await callback.answer(f"Отписались от {mod_name}")
        else:
            await callback.answer("❌ Не удалось отписаться")
    
    except Exception as e:
        logging.error(f"Ошибка в subs_unsubscribe_callback: {e}")
        await callback.answer("Произошла ошибка при отписке")

async def subs_back_callback(callback: types.CallbackQuery):
    """Возврат к списку подписок"""
    try:
        from .subscriptions import cmd_my_subscriptions
        await cmd_my_subscriptions(
            user_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
            bot=callback.bot
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка в subs_back_callback: {e}")
        await callback.answer("Произошла ошибка")

async def subs_refresh_callback(callback: types.CallbackQuery):
    """Обновление списка подписок"""
    try:
        from .subscriptions import cmd_my_subscriptions
        await cmd_my_subscriptions(
            user_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
            bot=callback.bot
        )
        await callback.answer("✅ Список обновлен")
    except Exception as e:
        logging.error(f"Ошибка в subs_refresh_callback: {e}")
        await callback.answer("Произошла ошибка")

async def subs_page_callback(callback: types.CallbackQuery, bot):
    """Переключение страниц в списке подписок"""
    try:
        _, page = callback.data.split(":")
        page = int(page)
        user_id = callback.from_user.id
        
        subscriptions = get_user_subscriptions(user_id)
        
        if not subscriptions:
            await callback.answer("Нет подписок")
            return
        
        # Формируем сообщение
        subs_text = "📋 <b>Ваши подписки на обновления модов:</b>\n\n"
        subs_text += "Выберите мод для управления подпиской:\n\n"
        
        # Создаем клавиатуру с кнопками
        keyboard = create_subscriptions_keyboard(subscriptions, page)
        
        await callback.message.edit_text(subs_text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    
    except Exception as e:
        logging.error(f"Ошибка в subs_page_callback: {e}")
        await callback.answer("Произошла ошибка")