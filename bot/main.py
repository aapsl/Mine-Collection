import asyncio
import logging
import os
import sys
from functools import partial

# Добавляем текущую директорию в путь для импорта
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import BOT_TOKEN, DB_PATH, LOG_LEVEL
from bot.database import init_database
from bot.cache import init_redis
from bot.utils import load_mod_aliases, load_mod_names_cache
from bot.handlers.base import cmd_start, cmd_help, debug_callback, handle_search_button, main_menu_callback, mysubs_menu_callback, help_menu_callback, stats_menu_callback, get_main_keyboard, handle_search_button, handle_my_subs_button, handle_help_button
from bot.handlers.admin import cmd_check_mod, cmd_stats, cmd_check_db, cmd_reload_cache, cmd_reload_aliases, cmd_reset_cache, cmd_broadcast, cmd_user_stats
from bot.handlers.search import search_mods
from bot.handlers.mods import mods_page_callback, show_mod_callback, mc_version_callback, back_to_list_callback, new_search_callback, ver_page_callback
from bot.handlers.subscriptions import (
    cmd_my_subscriptions, cmd_unsubscribe, cmd_debug_subs, 
    subscribe_callback, unsubscribe_callback, subs_show_callback, 
    subs_unsubscribe_callback, subs_back_callback, subs_refresh_callback, 
    subs_page_callback
)
from bot.tasks.updates import check_mod_updates

# Настройка логирования
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Создаем обертки для обработчиков, которым нужен объект bot
async def wrap_cmd_my_subs(message: Message):
    return await cmd_my_subscriptions(message.from_user.id, message.chat.id, bot)

async def wrap_cmd_debug_subs(message: Message):
    return await cmd_debug_subs(message.from_user.id, message.chat.id, bot)

async def wrap_mods_page(callback: types.CallbackQuery):
    return await mods_page_callback(callback, bot)

async def wrap_show_mod(callback: types.CallbackQuery):
    return await show_mod_callback(callback, bot)

async def wrap_mc_version(callback: types.CallbackQuery):
    return await mc_version_callback(callback, bot)

async def wrap_back_to_list(callback: types.CallbackQuery):
    return await back_to_list_callback(callback, bot)

async def wrap_subscribe(callback: types.CallbackQuery):
    return await subscribe_callback(callback, bot)

async def wrap_unsubscribe(callback: types.CallbackQuery):
    return await unsubscribe_callback(callback, bot)

async def wrap_subs_show(callback: types.CallbackQuery):
    return await subs_show_callback(callback, bot)

async def wrap_subs_unsubscribe(callback: types.CallbackQuery):
    return await subs_unsubscribe_callback(callback, bot)

async def wrap_subs_back(callback: types.CallbackQuery):
    return await subs_back_callback(callback)

async def wrap_subs_refresh(callback: types.CallbackQuery):
    return await subs_refresh_callback(callback)

async def wrap_subs_page(callback: types.CallbackQuery):
    return await subs_page_callback(callback, bot)

async def wrap_cmd_stats(message: Message):
    return await cmd_stats(message.from_user.id, message.chat.id, bot)

async def wrap_cmd_check_db(message: Message):
    return await cmd_check_db(message.from_user.id, message.chat.id, bot)

async def wrap_cmd_reload_cache(message: Message):
    return await cmd_reload_cache(message.from_user.id, message.chat.id, bot)

async def wrap_cmd_reload_aliases(message: Message):
    return await cmd_reload_aliases(message.from_user.id, message.chat.id, bot)

async def wrap_cmd_reset_cache(message: Message):
    return await cmd_reset_cache(message.from_user.id, message.chat.id, bot)

async def wrap_cmd_broadcast(message: Message):
    return await cmd_broadcast(message, bot)

async def wrap_cmd_user_stats(message: Message):
    return await cmd_user_stats(message.from_user.id, message.chat.id, bot)

async def wrap_cmd_check_mod(message: Message):
    return await cmd_check_mod(message, bot)

async def wrap_ver_page(callback: types.CallbackQuery):
    return await ver_page_callback(callback, bot)

# Обновляем регистрацию обработчиков
def register_handlers():
    """Регистрация всех обработчиков"""
    logging.info("Начинаем регистрацию обработчиков...")
    
    # Обработчики кнопок (должны быть зарегистрированы первыми)
    dp.message.register(handle_search_button, F.text == "🔍 Новый поиск")
    dp.message.register(handle_my_subs_button, F.text == "📋 Мои подписки")
    dp.message.register(handle_help_button, F.text == "ℹ️ Помощь")
    
    # Базовые команды
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_help, Command("help"))
    logging.info("Зарегистрированы базовые команды: /start, /help")
    
    # Админские команды
    dp.message.register(wrap_cmd_stats, Command("stats"))
    dp.message.register(wrap_cmd_check_db, Command("check_db"))
    dp.message.register(wrap_cmd_reload_cache, Command("reload_cache"))
    dp.message.register(wrap_cmd_reload_aliases, Command("reload_aliases"))
    dp.message.register(wrap_cmd_reset_cache, Command("reset_cache"))
    dp.message.register(wrap_cmd_broadcast, Command("broadcast"))
    dp.message.register(wrap_cmd_user_stats, Command("user_stats"))
    dp.message.register(wrap_cmd_check_mod, Command("check_mod"))
    dp.message.register(wrap_cmd_debug_subs, Command("debug_subs"))
    logging.info("Зарегистрированы административные команды")
    
    # Подписки
    dp.message.register(wrap_cmd_my_subs, Command("mysubs"))
    dp.message.register(cmd_unsubscribe, F.text.startswith("/unsubscribe_"))
    logging.info("Зарегистрированы команды подписок")
    
    # Поиск
    dp.message.register(search_mods, F.text)
    logging.info("Зарегистрирован обработчик поиска")
    
    # Callback-обработчики
    dp.callback_query.register(mysubs_menu_callback, F.data == "mysubs_menu")
    dp.callback_query.register(wrap_mods_page, F.data.startswith("mods_page:"))
    dp.callback_query.register(wrap_show_mod, F.data.startswith("show_mod:"))
    dp.callback_query.register(wrap_mc_version, F.data.startswith("mc_version:"))
    dp.callback_query.register(wrap_back_to_list, F.data.startswith("back_to_list:"))
    dp.callback_query.register(new_search_callback, F.data == "new_search")
    dp.callback_query.register(wrap_subscribe, F.data.startswith("subscribe:"))
    dp.callback_query.register(wrap_unsubscribe, F.data.startswith("unsubscribe:"))
    dp.callback_query.register(wrap_subs_show, F.data.startswith("subs_show:"))
    dp.callback_query.register(wrap_subs_unsubscribe, F.data.startswith("subs_unsubscribe:"))
    dp.callback_query.register(wrap_subs_back, F.data.startswith("subs_back:"))
    dp.callback_query.register(wrap_subs_refresh, F.data == "subs_refresh")
    dp.callback_query.register(wrap_subs_page, F.data.startswith("subs_page:"))
    dp.callback_query.register(help_menu_callback, F.data == "help_menu")
    dp.callback_query.register(stats_menu_callback, F.data == "stats_menu")
    dp.callback_query.register(wrap_ver_page, F.data.startswith("ver_page:"))
    logging.info("Зарегистрированы callback-обработчики")
    
    logging.info("Регистрация обработчиков завершена")

async def main():
    """Основная функция запуска бота"""
    logging.info("Запуск бота...")
    
    # Проверка наличия обязательных переменных
    if not BOT_TOKEN:
        logging.error("Не указан BOT_TOKEN в .env файле")
        exit(1)
    
    # Проверка существования базы данных
    if not os.path.exists(DB_PATH):
        logging.error(f"База данных {DB_PATH} не найдена")
        exit(1)
    
    # Инициализация компонентов
    init_database()
    init_redis()
    load_mod_aliases()
    load_mod_names_cache()
    
    # Очищаем кэш поиска при каждом запуске
    from bot.cache import clear_cache
    if clear_cache():
        logging.info("Кэш поиска очищен при запуске")
    else:
        logging.info("Не удалось очистить кэш поиска")
    
    # Получаем ID бота
    try:
        bot_info = await bot.get_me()
        BOT_ID = bot_info.id
        logging.info(f"ID бота: {BOT_ID}")
    except Exception as e:
        logging.error(f"Не удалось получить ID бота: {e}")
        BOT_ID = None
    
    # Регистрируем обработчики
    register_handlers()
    
    # Создаем фоновую задачу
    update_task = asyncio.create_task(check_mod_updates(bot))
    
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logging.info("Работа бота прервана")
    except Exception as e:
        logging.error(f"Ошибка в основном цикле бота: {e}")
    finally:
        # Останавливаем фоновую задачу
        if not update_task.done():
            update_task.cancel()
            try:
                await update_task
            except asyncio.CancelledError:
                logging.info("Фоновая задача проверки обновлений остановлена")
            except Exception as e:
                logging.error(f"Ошибка при остановке фоновой задачи: {e}")
        
        # Закрываем сессию бота
        try:
            await bot.session.close()
            logging.info("Сессия бота закрыта")
        except Exception as e:
            logging.error(f"Ошибка при закрытии сессии бота: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен пользователем")
    except Exception as e:
        logging.error(f"Неожиданная ошибка: {e}")
    finally:
        logging.info("Работа бота завершена")