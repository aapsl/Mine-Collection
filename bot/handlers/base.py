import logging
from aiogram import types, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.database import register_user
from bot.config import ADMIN_IDS
from bot.handlers.admin import cmd_stats
from bot.handlers.subscriptions import cmd_my_subscriptions

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Создаем функцию для главной клавиатуры
def get_main_keyboard():
    """Создает главную клавиатуру с основными кнопками"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Новый поиск")],
            [KeyboardButton(text="📋 Мои подписки")],
            [KeyboardButton(text="ℹ️ Помощь")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие или введите название мода"
    )

# Обновляем функцию cmd_start
async def cmd_start(message: Message):
    """Обработчик команд /start и /help"""
    # Регистрируем пользователя
    await register_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        language_code=message.from_user.language_code
    )
    
    welcome_text = (
        "👋 <b>Добро пожаловать в Modrinth Search Bot!</b>\n\n"
        "Я помогу найти моды для Minecraft на Modrinth.\n\n"
        "🔍 <b>Нажмите кнопку 'Новый поиск'</b> или просто введите название мода\n\n"
        "✨ <b>Новая функция:</b> Подписка на обновления модов!\n"
        "Теперь вы можете подписаться на мод и получать уведомления о новых версиях.\n\n"
        "📋 <b>Используйте кнопки ниже для навигации</b>"
    )
    
    # Получаем главную клавиатуру
    keyboard = get_main_keyboard()
    
    await message.answer(welcome_text, parse_mode="HTML", reply_markup=keyboard)

# Добавляем обработчики для кнопок
async def handle_search_button(message: Message):
    """Обработчик кнопки 'Новый поиск'"""
    await message.answer(
        "🔍 Введите название мода для поиска:",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()  # Сохраняем клавиатуру
    )

async def handle_my_subs_button(message: Message):
    """Обработчик кнопки 'Мои подписки'"""
    from .subscriptions import cmd_my_subscriptions
    await cmd_my_subscriptions(
        user_id=message.from_user.id,
        chat_id=message.chat.id
    )

async def handle_help_button(message: Message):
    """Обработчик кнопки 'Помощь'"""
    await cmd_help(message)

async def help_menu_callback(callback: types.CallbackQuery):
    """Обработчик кнопки перехода к помощи"""
    try:
        logging.info(f"Обработка help_menu_callback: {callback.data}")
        
        user_id = callback.from_user.id
        chat_id = callback.message.chat.id
        
        # Регистрируем пользователя
        from bot.database import register_user
        await register_user(
            user_id=user_id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
            language_code=callback.from_user.language_code
        )
        
        is_admin = user_id in ADMIN_IDS
        
        help_text = "🤖 <b>Modrinth Search Bot - Список команд</b>\n\n"
        
        help_text += "🔍 <b>Основные команды:</b>\n"
        help_text += "• /start - Начать работу с ботом\n"
        help_text += "• /help - Показать эту справку\n"
        help_text += "• /mysubs - Показать мои подписки на обновления модов\n"
        help_text += "• Просто введите название мода для поиска\n\n"
        
        help_text += "📋 <b>Команды для работы с подписками:</b>\n"
        help_text += "• /unsubscribe_[mod_id] - Отписаться от обновлений мода\n"
        help_text += "• /debug_subs - Отладочная информация о подписках\n\n"
        
        if is_admin:
            help_text += "⚙️ <b>Команды администратора:</b>\n"
            help_text += "• /stats - Статистика базы данных\n"
            help_text += "• /check_db - Проверить подключение к базе данных\n"
            help_text += "• /reload_cache - Перезагрузить кэш поиска\n"
            help_text += "• /reload_aliases - Перезагрузить псевдонимы модов\n"
            help_text += "• /reset_cache - Полный сброс кэша\n"
            help_text += "• /broadcast [сообщение] - Рассылка сообщений всем пользователям\n"
            help_text += "• /user_stats - Статистика пользователей\n"
            help_text += "• /check_mod [название] - Проверить наличие мода в базе данных\n\n"
        
        help_text += "💡 <b>Советы по использованию:</b>\n"
        help_text += "• Используйте кнопки под сообщениями для навигации\n"
        help_text += "• Подписывайтесь на моды, чтобы получать уведомления об обновлениях\n"
        help_text += "• Для поиска можно использовать как полные названия, так и псевдонимы (jei, sodium и т.д.)\n\n"
        
        help_text += "🌐 <b>Ссылки:</b>\n"
        help_text += "• <a href=\"https://modrinth.com/\">Modrinth - Лучший поиск модов для Minecraft</a>"
        
        # Используем метод answer для отправки нового сообщения
        await callback.message.answer(
            text=help_text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        await callback.answer()
        
    except Exception as e:
        logging.error(f"Ошибка в help_menu_callback: {e}")
        await callback.answer("Произошла ошибка при обработке запроса")

async def mysubs_menu_callback(callback: types.CallbackQuery):
    """Обработчик кнопки перехода к подпискам"""
    try:
        # Вызываем функцию напрямую с правильными аргументами
        from bot.handlers.subscriptions import cmd_my_subscriptions
        await cmd_my_subscriptions(
            user_id=callback.from_user.id,
            chat_id=callback.message.chat.id
            # Убираем bot
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка в mysubs_menu_callback: {e}")
        await callback.answer("Произошла ошибка")

async def stats_menu_callback(callback: types.CallbackQuery):
    """Обработчик кнопки статистики"""
    try:
        # Вызываем функцию напрямую с правильными аргументами
        from bot.handlers.admin import cmd_stats
        await cmd_stats(
            user_id=callback.from_user.id,
            chat_id=callback.message.chat.id,
            bot=callback.bot
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка в stats_menu_callback: {e}")
        await callback.answer("Произошла ошибка")

async def cmd_help(message: Message):
    """Обработчик команды /help - показывает все доступные команды"""
    # Регистрируем пользователя
    await register_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        language_code=message.from_user.language_code
    )
    
    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS
    
    help_text = "🤖 <b>Modrinth Search Bot - Список команд</b>\n\n"
    
    help_text += "🔍 <b>Как искать моды:</b>\n"
    help_text += "• Просто введите название мода в чат\n"
    help_text += "• Используйте английские названия для лучших результатов\n"
    help_text += "• Можно использовать псевдонимы (jei, sodium и т.д.)\n\n"
    
    help_text += "📋 <b>Команды:</b>\n"
    help_text += "• /start - Начать работу с ботом\n"
    help_text += "• /help - Показать эту справку\n"
    help_text += "• /mysubs - Показать мои подписки на обновления модов\n\n"
    
    help_text += "💡 <b>Советы по использованию:</b>\n"
    help_text += "• Используйте кнопки под сообщениями для навигации\n"
    help_text += "• Подписывайтесь на моды, чтобы получать уведомления об обновлениях\n"
    help_text += "• Для поиска можно использовать как полные названия, так и псевдонимы\n\n"
    
    if is_admin:
        help_text += "⚙️ <b>Команды администратора:</b>\n"
        help_text += "• /stats - Статистика базы данных\n"
        help_text += "• /check_db - Проверить подключение к базе данных\n"
        help_text += "• /reload_cache - Перезагрузить кэш поиска\n"
        help_text += "• /reload_aliases - Перезагрузить псевдонимы модов\n"
        help_text += "• /reset_cache - Полный сброс кэша\n"
        help_text += "• /broadcast [сообщение] - Рассылка сообщений всем пользователям\n"
        help_text += "• /user_stats - Статистика пользователей\n"
        help_text += "• /check_mod [название] - Проверить наличие мода в базе данных\n\n"
    
    help_text += "🌐 <b>Ссылки:</b>\n"
    help_text += "• <a href=\"https://modrinth.com/\">Modrinth - Лучший поиск модов для Minecraft</a>"
    
    await message.answer(help_text, parse_mode="HTML", disable_web_page_preview=True)

async def help_menu_callback(callback: types.CallbackQuery):
    """Обработчик кнопки перехода к помощи"""
    try:
        logging.info(f"Обработка help_menu_callback: {callback.data}")
        
        # Регистрируем пользователя
        await register_user(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
            language_code=callback.from_user.language_code
        )
        
        user_id = callback.from_user.id
        is_admin = user_id in ADMIN_IDS
        
        help_text = "🤖 <b>Modrinth Search Bot - Список команд</b>\n\n"
        
        help_text += "🔍 <b>Как искать моды:</b>\n"
        help_text += "• Просто введите название мода в чат\n"
        help_text += "• Используйте английские названия для лучших результатов\n"
        help_text += "• Можно использовать псевдонимы (jei, sodium и т.д.)\n\n"
        
        help_text += "📋 <b>Команды:</b>\n"
        help_text += "• /start - Начать работу с ботом\n"
        help_text += "• /help - Показать эту справку\n"
        help_text += "• /mysubs - Показать мои подписки на обновления модов\n\n"
        
        help_text += "💡 <b>Советы по использованию:</b>\n"
        help_text += "• Используйте кнопки под сообщениями для навигации\n"
        help_text += "• Подписывайтесь на моды, чтобы получать уведомления об обновлениях\n"
        help_text += "• Для поиска можно использовать как полные названия, так и псевдонимы\n\n"
        
        if is_admin:
            help_text += "⚙️ <b>Команды администратора:</b>\n"
            help_text += "• /stats - Статистика базы данных\n"
            help_text += "• /check_db - Проверить подключение к базе данных\n"
            help_text += "• /reload_cache - Перезагрузить кэш поиска\n"
            help_text += "• /reload_aliases - Перезагрузить псевдонимы модов\n"
            help_text += "• /reset_cache - Полный сброс кэша\n"
            help_text += "• /broadcast [сообщение] - Рассылка сообщений всем пользователям\n"
            help_text += "• /user_stats - Статистика пользователей\n"
            help_text += "• /check_mod [название] - Проверить наличие мода в базе данных\n\n"
        
        help_text += "🌐 <b>Ссылки:</b>\n"
        help_text += "• <a href=\"https://modrinth.com/\">Modrinth - Лучший поиск модов для Minecraft</a>"
        
        # Используем метод edit_text для редактирования текущего сообщения
        await callback.message.edit_text(
            text=help_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🏠 Выход в главное меню", callback_data="main_menu")]
            ])
        )
        await callback.answer()
        
    except Exception as e:
        logging.error(f"Ошибка в help_menu_callback: {e}")
        await callback.answer("Произошла ошибка при обработке запроса")

async def main_menu_callback(callback: types.CallbackQuery):
    """Обработчик кнопки выхода в главное меню"""
    try:
        # Регистрируем пользователя
        await register_user(
            user_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
            language_code=callback.from_user.language_code
        )
        
        welcome_text = (
            "👋 <b>Добро пожаловать в Modrinth Search Bot!</b>\n\n"
            "Я помогу найти моды для Minecraft на Modrinth.\n\n"
            "🔍 <b>Просто напиши название мода</b>, который хочешь найти, "
            "и я покажу всю доступную информацию о нем!\n\n"
            "✨ <b>Новая функция:</b> Подписка на обновления модов!\n"
            "Теперь вы можете подписаться на мод и получать уведомления о новых версиях.\n\n"
            "📋 <b>Используйте кнопки ниже для навигации</b>"
        )
        
        # Создаем клавиатуру с основными командами
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="📋 Мои подписки", callback_data="mysubs_menu")],
            [types.InlineKeyboardButton(text="📊 Статистика", callback_data="stats_menu")],
            [types.InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help_menu")]
        ])
        
        await callback.message.edit_text(welcome_text, parse_mode="HTML", reply_markup=keyboard)
        await callback.answer()
    
    except Exception as e:
        logging.error(f"Ошибка в main_menu_callback: {e}")
        await callback.answer("Произошла ошибка")

async def debug_callback(callback: types.CallbackQuery):
    """Обработчик для отладки необработанных callback-запросов"""
    logging.warning(f"Необработанный callback: {callback.data}")
    await callback.answer(f"Callback получен: {callback.data}", show_alert=True)