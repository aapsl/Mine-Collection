import asyncio
import logging
import os
import sys

# Настройка путей
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

async def main():
    """Основная функция бота"""
    try:
        from bot.config import BOT_TOKEN
        from bot.database import init_database, close_database, get_pool
        from bot.cache import init_redis
        from bot.utils import load_mod_aliases, load_mod_names_cache
        from aiogram import Bot, Dispatcher
        from aiogram.filters import Command
        from aiogram.types import Message
        
        if not BOT_TOKEN:
            logging.error("❌ BOT_TOKEN не указан")
            return
        
        # 1. Сначала инициализируем базу данных
        logging.info("🔄 Инициализация базы данных...")
        await init_database()
        
        # 2. Проверяем, что пул инициализирован через функцию get_pool
        pool = get_pool()
        if pool is None:
            logging.error("❌ Пул соединений не инициализирован")
            return
        
        # 3. Инициализируем Redis
        logging.info("🔄 Инициализация кэша...")
        init_redis()
        
        # 4. Загружаем псевдонимы
        logging.info("🔄 Загрузка псевдонимов модов...")
        load_mod_aliases()
        
        # 5. Загружаем кэш названий модов (теперь пул должен быть доступен)
        logging.info("🔄 Загрузка кэша названий модов...")
        await load_mod_names_cache()
        
        # Инициализация бота
        bot = Bot(token=BOT_TOKEN)
        dp = Dispatcher()
        
        # Регистрация обработчиков
        logging.info("🔄 Регистрация обработчиков...")
        
        from bot.handlers.base import (
            cmd_start, cmd_help, handle_search_button, handle_my_subs_button, 
            handle_help_button, mysubs_menu_callback, help_menu_callback, 
            stats_menu_callback
        )
        from bot.handlers.search import search_mods
        from bot.handlers.subscriptions import cmd_my_subscriptions
        from bot.handlers.mods import (
            mods_page_callback, show_mod_callback, mc_version_callback, 
            back_to_list_callback, new_search_callback, ver_page_callback
        )
        from bot.handlers.subscriptions import (
            subscribe_callback, unsubscribe_callback, subs_show_callback,
            subs_unsubscribe_callback, subs_back_callback, subs_refresh_callback,
            subs_page_callback
        )
        
        from aiogram.filters import Command
        from aiogram import F
        
        # Базовые команды
        dp.message.register(cmd_start, Command("start"))
        dp.message.register(cmd_help, Command("help"))
        
        # Обработчики кнопок
        dp.message.register(handle_search_button, F.text == "🔍 Новый поиск")
        dp.message.register(handle_my_subs_button, F.text == "📋 Мои подписки")
        dp.message.register(handle_help_button, F.text == "ℹ️ Помощь")
        
        # Поиск модов
        dp.message.register(search_mods, F.text)
        
        # Подписки
        dp.message.register(cmd_my_subscriptions, Command("mysubs"))
        
        # Callback-обработчики для модов
        dp.callback_query.register(mods_page_callback, F.data.startswith("mods_page:"))
        dp.callback_query.register(show_mod_callback, F.data.startswith("show_mod:"))
        dp.callback_query.register(mc_version_callback, F.data.startswith("mc_version:"))
        dp.callback_query.register(back_to_list_callback, F.data.startswith("back_to_list:"))
        dp.callback_query.register(new_search_callback, F.data == "new_search")
        dp.callback_query.register(ver_page_callback, F.data.startswith("ver_page:"))
        
        # Callback-обработчики для подписок
        dp.callback_query.register(mysubs_menu_callback, F.data == "mysubs_menu")
        dp.callback_query.register(subscribe_callback, F.data.startswith("subscribe:"))
        dp.callback_query.register(unsubscribe_callback, F.data.startswith("unsubscribe:"))
        dp.callback_query.register(subs_show_callback, F.data.startswith("subs_show:"))
        dp.callback_query.register(subs_unsubscribe_callback, F.data.startswith("subs_unsubscribe:"))
        dp.callback_query.register(subs_back_callback, F.data.startswith("subs_back:"))
        dp.callback_query.register(subs_refresh_callback, F.data == "subs_refresh")
        dp.callback_query.register(subs_page_callback, F.data.startswith("subs_page:"))
        
        # Другие callback-обработчики
        dp.callback_query.register(help_menu_callback, F.data == "help_menu")
        dp.callback_query.register(stats_menu_callback, F.data == "stats_menu")
        
        logging.info("✅ Бот успешно инициализирован и готов к работе")
        
        # Запуск бота
        await dp.start_polling(bot)
        
    except Exception as e:
        logging.error(f"❌ Ошибка при запуске бота: {e}")
        import traceback
        logging.error(traceback.format_exc())
    finally:
        try:
            await close_database()
            logging.info("✅ Соединение с базой данных закрыто")
        except Exception as e:
            logging.error(f"❌ Ошибка при закрытии соединения с БД: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Бот остановлен пользователем")
    except Exception as e:
        logging.error(f"💥 Критическая ошибка: {e}")