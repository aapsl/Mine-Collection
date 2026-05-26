import asyncio
import logging
import sys
import os
import time
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import bot.config as config
import bot.database as db
import bot.cache as cache
import bot.utils as utils
import bot.keyboards as kb
from bot.tasks.updates import check_mod_updates

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s'
)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
BOT_ID = None


# ==================== КЛАВИАТУРЫ ====================

def main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Новый поиск")],
            [KeyboardButton(text="📋 Мои подписки")],
            [KeyboardButton(text="ℹ️ Помощь")]
        ],
        resize_keyboard=True
    )


def admin_keyboard() -> ReplyKeyboardMarkup:
    """Админ-клавиатура"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Новый поиск")],
            [KeyboardButton(text="📋 Мои подписки")],
            [KeyboardButton(text="ℹ️ Помощь")],
            [KeyboardButton(text="⚙️ Админ-панель")]
        ],
        resize_keyboard=True
    )


# ==================== КОМАНДЫ ====================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    is_admin = user_id in config.ADMIN_IDS
    
    logging.info(f"✅ /start от {user_id} (админ: {is_admin})")
    
    await db.register_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        language_code=message.from_user.language_code
    )
    
    welcome_text = (
        "👋 <b>Добро пожаловать в Modrinth Search Bot!</b>\n\n"
        "🔍 <b>Как искать моды:</b>\n"
        "• Просто напишите название мода\n"
        "• Используйте английские названия\n"
        "• Можно использовать псевдонимы (jei, sodium, create)\n\n"
        "📋 <b>Основные команды:</b>\n"
        "• /help - Помощь\n"
        "• /mysubs - Мои подписки\n"
    )
    
    if is_admin:
        welcome_text += (
            "\n⚙️ <b>Админ-команды:</b>\n"
            "• /stats - Статистика БД\n"
            "• /check_db - Проверка БД\n"
            "• /reload_cache - Перезагрузить кэш\n"
            "• /reload_aliases - Перезагрузить псевдонимы\n"
            "• /reset_cache - Сбросить кэш\n"
            "• /user_stats - Статистика пользователей\n"
            "• /broadcast - Рассылка\n"
            "• /check_mod - Проверить мод\n"
            "• /help_admin - Все админ-команды\n"
        )
    
    keyboard = admin_keyboard() if is_admin else main_keyboard()
    
    await message.answer(welcome_text, parse_mode="HTML", reply_markup=keyboard)


@dp.message(Command("help"))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    is_admin = user_id in config.ADMIN_IDS
    
    help_text = (
        "🤖 <b>Modrinth Search Bot - Помощь</b>\n\n"
        "🔍 <b>Поиск модов:</b>\n"
        "• Просто введите название мода\n"
        "• Используйте английские названия\n"
        "• Поддерживаются псевдонимы (jei, sodium, create)\n"
        "• Работает со спецсимволами (:, -, пробелы)\n\n"
        "📋 <b>Команды:</b>\n"
        "• /start - Начать работу\n"
        "• /help - Эта справка\n"
        "• /mysubs - Мои подписки\n\n"
        "🔔 <b>Подписки:</b>\n"
        "• Нажмите '🔔 Подписаться' на странице мода\n"
        "• Уведомления о новых версиях приходят автоматически\n"
        "• /mysubs - Управление подписками\n"
    )
    
    if is_admin:
        help_text += (
            "\n⚙️ <b>Админ-команды:</b>\n"
            "• /stats - Статистика базы данных\n"
            "• /check_db - Проверка подключения к БД\n"
            "• /reload_cache - Перезагрузка кэша поиска\n"
            "• /reload_aliases - Перезагрузка псевдонимов\n"
            "• /reset_cache - Полный сброс кэша\n"
            "• /user_stats - Статистика пользователей\n"
            "• /broadcast [текст] - Рассылка сообщения\n"
            "• /check_mod [название] - Проверка наличия мода\n"
            "• /help_admin - Полный список админ-команд\n"
        )
    
    await message.answer(help_text, parse_mode="HTML")


@dp.message(Command("help_admin"))
async def cmd_help_admin(message: Message):
    """Полная справка по админ-командам"""
    user_id = message.from_user.id
    
    if user_id not in config.ADMIN_IDS:
        await message.answer("❌ У вас нет прав")
        return
    
    await message.answer(
        "⚙️ <b>Полный список админ-команд</b>\n\n"
        "📊 <b>Статистика и мониторинг:</b>\n"
        "• /stats - Общая статистика БД\n"
        "• /check_db - Детальная проверка БД\n"
        "• /user_stats - Статистика пользователей\n"
        "• /check_mod [название] - Проверить мод\n\n"
        
        "🔄 <b>Управление кэшем:</b>\n"
        "• /reload_cache - Перезагрузить кэш поиска\n"
        "• /reload_aliases - Перезагрузить псевдонимы\n"
        "• /reset_cache - Полный сброс кэша\n\n"
        
        "📨 <b>Рассылка:</b>\n"
        "• /broadcast [текст] - Запустить рассылку\n"
        "• /broadcast_status - Статус текущей рассылки\n"
        "• /broadcast_cancel - Остановить рассылку\n\n"
        
        "❓ <b>Справка:</b>\n"
        "• /help_admin - Эта справка",
        parse_mode="HTML"
    )


@dp.message(Command("mysubs"))
async def cmd_mysubs(message: Message):
    user_id = message.from_user.id
    logging.info(f"📋 /mysubs от {user_id}")
    
    subs = await db.get_user_subscriptions(user_id)
    
    if not subs:
        await message.answer(
            "📋 У вас пока нет подписок.\n\n"
            "Чтобы подписаться, найдите мод и нажмите '🔔 Подписаться'"
        )
        return
    
    keyboard = kb.subscriptions_keyboard(subs, 0)
    await message.answer(f"📋 <b>Ваши подписки</b> ({len(subs)}):", parse_mode="HTML", reply_markup=keyboard)


# ==================== АДМИН-КОМАНДЫ ====================

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    
    stats = await db.get_mod_stats()
    users = await db.get_users_count()
    
    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"📦 Модов: {stats.get('mods_count', 0)}\n"
        f"📄 Версий: {stats.get('versions_count', 0)}\n"
        f"👥 Пользователей: {users}",
        parse_mode="HTML"
    )


@dp.message(Command("check_db"))
async def cmd_check_db(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    
    pool = db.get_pool()
    if pool is None:
        await message.answer("❌ База данных не подключена")
        return
    
    async with pool.acquire() as conn:
        mods = await conn.fetchval("SELECT COUNT(*) FROM mods")
        vers = await conn.fetchval("SELECT COUNT(*) FROM versions")
        users = await conn.fetchval("SELECT COUNT(*) FROM users")
        subs = await conn.fetchval("SELECT COUNT(*) FROM subscriptions")
    
    await message.answer(
        f"✅ <b>База данных OK</b>\n\n"
        f"Моды: {mods}\n"
        f"Версии: {vers}\n"
        f"Пользователи: {users}\n"
        f"Подписки: {subs}",
        parse_mode="HTML"
    )


@dp.message(Command("reload_cache"))
async def cmd_reload_cache(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    
    await utils.load_mod_names_cache()
    await message.answer("✅ Кэш поиска перезагружен")


@dp.message(Command("reload_aliases"))
async def cmd_reload_aliases(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    
    utils.load_mod_aliases()
    await message.answer(f"✅ Псевдонимы перезагружены. Загружено {len(utils.COMMON_MOD_ALIASES)} записей")


@dp.message(Command("reset_cache"))
async def cmd_reset_cache(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    
    cache.clear_cache()
    utils.mod_names_cache.clear()
    await utils.load_mod_names_cache()
    await message.answer("✅ Весь кэш сброшен и перезагружен")


@dp.message(Command("user_stats"))
async def cmd_user_stats(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    
    users = await db.get_users_count()
    
    pool = db.get_pool()
    top_subs = []
    if pool:
        async with pool.acquire() as conn:
            top_subs = await conn.fetch("""
                SELECT m.title, COUNT(s.user_id) as subs_count
                FROM subscriptions s
                JOIN mods m ON s.mod_id = m.id
                GROUP BY m.id, m.title
                ORDER BY subs_count DESC
                LIMIT 5
            """)
    
    text = f"👥 <b>Статистика пользователей</b>\n\nВсего пользователей: {users}\n\n"
    if top_subs:
        text += "<b>Топ-5 подписок:</b>\n"
        for i, row in enumerate(top_subs, 1):
            text += f"{i}. {row['title']} — {row['subs_count']} подписчиков\n"
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("check_mod"))
async def cmd_check_mod(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Укажите название мода\n\nПример: `/check_mod Create`", parse_mode="HTML")
        return
    
    mod_name = parts[1].strip()
    pool = db.get_pool()
    
    if pool is None:
        await message.answer("❌ База данных не подключена")
        return
    
    async with pool.acquire() as conn:
        exact = await conn.fetchrow("SELECT id, title, downloads FROM mods WHERE title ILIKE $1", mod_name)
        
        if exact:
            await message.answer(
                f"✅ <b>Мод найден</b>\n\nID: {exact['id']}\nНазвание: {exact['title']}\nЗагрузок: {exact['downloads']:,}",
                parse_mode="HTML"
            )
            return
        
        similar = await conn.fetch("SELECT id, title, downloads FROM mods WHERE title ILIKE $1 ORDER BY downloads DESC LIMIT 5", f'%{mod_name}%')
        
        if similar:
            text = f"❌ Точное совпадение не найдено.\n\n<b>Похожие моды:</b>\n"
            for i, row in enumerate(similar, 1):
                text += f"{i}. {row['title']} ({row['downloads']:,})\n"
            await message.answer(text, parse_mode="HTML")
        else:
            await message.answer(f"❌ Мод \"{mod_name}\" не найден")

# ==================== РАССЫЛКА (ФОНОВАЯ) ====================

# Словарь для отслеживания активных рассылок
active_broadcasts = {}

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    """Команда для запуска рассылки"""
    user_id = message.from_user.id
    
    if user_id not in config.ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return
    
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer(
            "❌ Укажите текст для рассылки\n\n"
            "Пример: `/broadcast Всем привет!`\n\n"
            "💡 Текст может содержать HTML-разметку:\n"
            "<b>жирный</b>, <i>курсив</i>, <a href='https://example.com'>ссылки</a>",
            parse_mode="HTML"
        )
        return
    
    if user_id in active_broadcasts:
        await message.answer(
            f"⚠️ У вас уже есть активная рассылка!\n"
            f"Прогресс: {active_broadcasts[user_id]['sent']}/{active_broadcasts[user_id]['total']}\n"
            f"Дождитесь её завершения или используйте /broadcast_cancel"
        )
        return
    
    users = await db.get_all_users()
    total = len(users)
    
    if total == 0:
        await message.answer("❌ Нет пользователей для рассылки")
        return
    
    preview = text[:300] + "..." if len(text) > 300 else text
    
    # Сохраняем текст прямо в callback_data (кодируем для безопасности)
    import urllib.parse
    encoded_text = urllib.parse.quote(text)
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(
                text="✅ Начать рассылку", 
                callback_data=f"broadcast_start:{user_id}:{encoded_text[:100]}"
            ),
            types.InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")
        ]
    ])
    
    await message.answer(
        f"📨 <b>Подтверждение рассылки</b>\n\n"
        f"📊 Получателей: {total}\n"
        f"📝 Текст сообщения:\n"
        f"<code>{preview}</code>\n\n"
        f"⚠️ <b>Внимание!</b> Отменить рассылку будет невозможно.\n"
        f"Сообщение будет отправлено <b>всем пользователям бота</b>.\n\n"
        f"Нажмите «Начать рассылку» для подтверждения.",
        parse_mode="HTML",
        reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("broadcast_start:"))
async def broadcast_start_callback(call: types.CallbackQuery):
    """Запуск рассылки в фоне"""
    try:
        parts = call.data.split(":", 2)
        if len(parts) < 2:
            await call.answer("❌ Ошибка формата данных", show_alert=True)
            return
        
        admin_id = int(parts[1])
        
        if call.from_user.id != admin_id:
            await call.answer("❌ Эта кнопка не для вас", show_alert=True)
            return
        
        if call.from_user.id not in config.ADMIN_IDS:
            await call.answer("❌ Нет прав", show_alert=True)
            return
        
        # Извлекаем текст из callback_data
        import urllib.parse
        if len(parts) >= 3:
            broadcast_text = urllib.parse.unquote(parts[2])
        else:
            # Если текста нет в callback, пробуем извлечь из сообщения
            broadcast_text = None
        
        # Если не получилось, пробуем из сообщения
        if not broadcast_text:
            import re
            match = re.search(r'<code>(.*?)</code>', call.message.text or "", re.DOTALL)
            if match:
                broadcast_text = match.group(1).strip()
        
        if not broadcast_text:
            await call.answer("❌ Не удалось извлечь текст сообщения", show_alert=True)
            return
        
        users = await db.get_all_users()
        total = len(users)
        
        if total == 0:
            await call.message.edit_text("❌ Нет пользователей для рассылки")
            return
        
        active_broadcasts[admin_id] = {
            'sent': 0,
            'failed': 0,
            'total': total,
            'text': broadcast_text,
            'running': True
        }
        
        await call.message.edit_text(
            f"📨 <b>Рассылка запущена!</b>\n\n"
            f"📊 Всего: {total}\n"
            f"📤 Отправлено: 0\n"
            f"❌ Ошибок: 0\n\n"
            f"🔄 Рассылка выполняется в фоновом режиме...",
            parse_mode="HTML"
        )
        await call.answer("✅ Рассылка запущена")
        
        asyncio.create_task(run_broadcast_task(bot, admin_id, call.message.chat.id, broadcast_text, users))
        
    except Exception as e:
        logging.error(f"Ошибка при запуске рассылки: {e}")
        await call.answer("❌ Ошибка при запуске рассылки", show_alert=True)


async def run_broadcast_task(bot_instance, admin_id: int, chat_id: int, text: str, users: list):
    """Фоновая задача для рассылки сообщений"""
    total = len(users)
    sent = 0
    failed = 0
    
    for i, user_id in enumerate(users):
        if admin_id in active_broadcasts and not active_broadcasts[admin_id].get('running', True):
            await bot_instance.send_message(
                chat_id,
                f"⏹️ <b>Рассылка остановлена</b>\n\n"
                f"📊 Отправлено: {sent}\n"
                f"❌ Ошибок: {failed}",
                parse_mode="HTML"
            )
            return
        
        try:
            await bot_instance.send_message(user_id, text, parse_mode="HTML", disable_web_page_preview=True)
            sent += 1
            if admin_id in active_broadcasts:
                active_broadcasts[admin_id]['sent'] = sent
                active_broadcasts[admin_id]['failed'] = failed
            
            if (i + 1) % 50 == 0:
                try:
                    await bot_instance.send_message(
                        chat_id,
                        f"📨 <b>Прогресс рассылки</b>\n\n"
                        f"📊 Отправлено: {sent}/{total}\n"
                        f"❌ Ошибок: {failed}",
                        parse_mode="HTML"
                    )
                except:
                    pass
            
            await asyncio.sleep(0.2)
            
        except Exception as e:
            failed += 1
            if admin_id in active_broadcasts:
                active_broadcasts[admin_id]['failed'] = failed
            logging.warning(f"Не удалось отправить {user_id}: {e}")
    
    if admin_id in active_broadcasts:
        del active_broadcasts[admin_id]
    
    await bot_instance.send_message(
        chat_id,
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📊 Отправлено: {sent}/{total}\n"
        f"❌ Ошибок: {failed}",
        parse_mode="HTML"
    )


@dp.message(Command("broadcast_status"))
async def cmd_broadcast_status(message: Message):
    """Статус активной рассылки"""
    user_id = message.from_user.id
    
    if user_id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    
    if user_id not in active_broadcasts:
        await message.answer("ℹ️ Нет активных рассылок")
        return
    
    b = active_broadcasts[user_id]
    progress = int((b['sent'] + b['failed']) / b['total'] * 100) if b['total'] > 0 else 0
    
    await message.answer(
        f"📨 <b>Статус рассылки</b>\n\n"
        f"📊 Всего: {b['total']}\n"
        f"📤 Отправлено: {b['sent']}\n"
        f"❌ Ошибок: {b['failed']}\n"
        f"📊 Прогресс: {progress}%\n"
        f"⏳ Осталось: {b['total'] - b['sent'] - b['failed']}",
        parse_mode="HTML"
    )


@dp.message(Command("broadcast_cancel"))
async def cmd_broadcast_cancel(message: Message):
    """Остановка активной рассылки"""
    user_id = message.from_user.id
    
    if user_id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    
    if user_id not in active_broadcasts:
        await message.answer("ℹ️ Нет активных рассылок для остановки")
        return
    
    active_broadcasts[user_id]['running'] = False
    b = active_broadcasts[user_id]
    
    await message.answer(
        f"⏹️ <b>Остановка рассылки...</b>\n\n"
        f"📤 Отправлено: {b['sent']}\n"
        f"❌ Ошибок: {b['failed']}",
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel_callback(call: types.CallbackQuery):
    """Отмена рассылки на этапе подтверждения"""
    if call.from_user.id not in config.ADMIN_IDS:
        await call.answer("❌ Нет прав")
        return
    
    await call.message.edit_text("❌ Рассылка отменена")
    await call.answer("✅ Отменено")

# ==================== ПОИСК ====================

@dp.message(F.text == "🔍 Новый поиск")
async def new_search_button(message: Message):
    await message.answer("🔍 Введите название мода:")


@dp.message(F.text == "📋 Мои подписки")
async def my_subs_button(message: Message):
    await cmd_mysubs(message)


@dp.message(F.text == "ℹ️ Помощь")
async def help_button(message: Message):
    await cmd_help(message)


@dp.message(F.text == "⚙️ Админ-панель")
async def admin_panel_button(message: Message):
    user_id = message.from_user.id
    
    if user_id not in config.ADMIN_IDS:
        await message.answer("❌ У вас нет прав доступа к админ-панели")
        return
    
    await message.answer(
        "⚙️ <b>Админ-панель</b>\n\n"
        "Выберите действие:\n\n"
        "📊 /stats - Статистика\n"
        "🔍 /check_db - Проверка БД\n"
        "🔄 /reload_cache - Обновить кэш\n"
        "📝 /reload_aliases - Обновить псевдонимы\n"
        "🗑️ /reset_cache - Сбросить кэш\n"
        "👥 /user_stats - Статистика пользователей\n"
        "📨 /broadcast - Рассылка\n"
        "🔎 /check_mod - Проверить мод\n"
        "❓ /help_admin - Все команды",
        parse_mode="HTML"
    )


@dp.message(F.text & ~F.text.startswith('/'))
async def search_mods(message: Message):
    query = message.text.strip()
    
    user_id = message.from_user.id
    username = message.from_user.username or "без юзернейма"
    
    logging.info(f"🔍 ПОИСК: '{query}' от {username} (ID: {user_id})")
    
    if len(query) < 2:
        await message.answer("❌ Минимум 2 символа")
        return
    
    await message.chat.do("typing")
    
    start_time = time.time()
    results = await utils.search_mods_cached(query, 50)
    elapsed = (time.time() - start_time) * 1000
    
    logging.info(f"⏱️ Поиск '{query}' занял {elapsed:.0f} мс, найдено {len(results)} результатов")
    
    if not results:
        await message.answer(f"🔍 По запросу \"{query}\" ничего не найдено")
        return
    
    keyboard = kb.mods_keyboard(results, 0, query)
    await message.answer(
        f"🔍 <b>Результаты</b> \"{query}\" ({len(results)}):",
        parse_mode="HTML",
        reply_markup=keyboard
    )


# ==================== CALLBACK-ОБРАБОТЧИКИ ====================

@dp.callback_query(F.data.startswith("page:"))
async def page_callback(call: types.CallbackQuery):
    _, page, query = call.data.split(":", 2)
    page = int(page)
    
    results = await utils.search_mods_cached(query, 50)
    if not results:
        await call.answer("Ничего не найдено")
        return
    
    keyboard = kb.mods_keyboard(results, page, query)
    await call.message.edit_reply_markup(reply_markup=keyboard)
    await call.answer()


@dp.callback_query(F.data.startswith("mod:"))
async def mod_callback(call: types.CallbackQuery):
    """Обработчик выбора мода из списка"""
    try:
        _, mod_id, query, page = call.data.split(":", 3)
        page = int(page)
        
        pool = db.get_pool()
        if pool is None:
            await call.answer("❌ База данных не готова", show_alert=True)
            return
        
        async with pool.acquire() as conn:
            mod = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
        
        if not mod:
            await call.answer("❌ Мод не найден", show_alert=True)
            return
        
        versions = await db.get_mod_versions(mod_id)
        total_versions = len(versions)
        loaders = await db.get_all_mod_loaders(mod_id)
        
        # Проверяем подписку
        subs = await db.get_user_subscriptions(call.from_user.id)
        is_subscribed = any(s['mod_id'] == mod_id for s in subs)
        
        # Форматируем сообщение (краткая версия)
        mod_dict = dict(mod)
        message_text = utils.format_mod_message(mod_dict, versions[0] if versions else None, loaders, total_versions)
        
        # Клавиатура карточки мода
        keyboard = kb.mod_details_keyboard(mod_id, query, page, is_subscribed, total_versions)
        
        await call.message.edit_text(message_text, parse_mode="HTML", reply_markup=keyboard)
        await call.answer()
        
    except Exception as e:
        logging.error(f"Ошибка в mod_callback: {e}")
        await call.answer("❌ Ошибка при открытии мода", show_alert=True)


@dp.callback_query(F.data.startswith("show_versions:"))
async def show_versions_callback(call: types.CallbackQuery):
    """Показывает список версий мода"""
    try:
        _, mod_id, query, mod_page = call.data.split(":", 3)
        mod_page = int(mod_page)
        
        versions = await db.get_mod_versions(mod_id)
        
        if not versions:
            await call.answer("❌ Нет доступных версий", show_alert=True)
            return
        
        # Исправлено: правильный вызов функции
        keyboard = kb.versions_list_keyboard(
            mod_id=mod_id,
            versions=versions,
            query=query,
            mod_page=mod_page,
            ver_page=0
        )
        
        await call.message.edit_text(
            f"📦 <b>Выберите версию</b>\n\nВсего версий: {len(versions)}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await call.answer()
        
    except Exception as e:
        logging.error(f"Ошибка в show_versions_callback: {e}")
        await call.answer("❌ Ошибка при загрузке версий", show_alert=True)


@dp.callback_query(F.data.startswith("versions_page:"))
async def versions_page_callback(call: types.CallbackQuery):
    """Пагинация списка версий"""
    try:
        _, mod_id, ver_page, query, mod_page = call.data.split(":", 4)
        ver_page = int(ver_page)
        mod_page = int(mod_page)
        
        versions = await db.get_mod_versions(mod_id)
        keyboard = kb.versions_list_keyboard(mod_id, versions, query, mod_page, ver_page)
        
        await call.message.edit_reply_markup(reply_markup=keyboard)
        await call.answer()
        
    except Exception as e:
        logging.error(f"Ошибка в versions_page_callback: {e}")
        await call.answer("❌ Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("select_version:"))
async def select_version_callback(call: types.CallbackQuery):
    """Показывает информацию о выбранной версии"""
    try:
        _, mod_id, version_id, query, mod_page, ver_page = call.data.split(":", 6)
        mod_page = int(mod_page)
        ver_page = int(ver_page)
        
        pool = db.get_pool()
        if pool is None:
            await call.answer("❌ База данных не готова", show_alert=True)
            return
        
        async with pool.acquire() as conn:
            version = await conn.fetchrow("SELECT * FROM versions WHERE id = $1", version_id)
            mod = await conn.fetchrow("SELECT title, slug FROM mods WHERE id = $1", mod_id)
        
        if not version or not mod:
            await call.answer("❌ Данные не найдены", show_alert=True)
            return
        
        version_number = version.get('version_number', '?')
        version_type = version.get('version_type', 'release')
        loaders = version.get('loaders', [])
        game_versions = version.get('game_versions', [])
        published_at = version.get('published_at')
        file_size = version.get('file_size', 0)
        download_url = version.get('download_url', '')
        
        # Тип версии с пояснением
        type_emoji = "🟢"
        type_name = "Релиз"
        if version_type == 'beta':
            type_emoji = "🔵"
            type_name = "Бета"
        elif version_type == 'alpha':
            type_emoji = "🟣"
            type_name = "Альфа"
        
        # Загрузчики
        loaders_str = ", ".join(loaders) if loaders else "Не указано"
        
        # Версии Minecraft
        mc_str = ", ".join(game_versions[:3]) if game_versions else "Не указано"
        if len(game_versions) > 3:
            mc_str += f" +{len(game_versions) - 3}"
        
        # Размер файла
        size_str = ""
        if file_size:
            if file_size < 1024 * 1024:
                size_str = f"\n📦 Размер: {file_size / 1024:.1f} КБ"
            else:
                size_str = f"\n📦 Размер: {file_size / (1024 * 1024):.1f} МБ"
        
        # Дата
        date_str = f"\n📅 Дата: {published_at.strftime('%Y-%m-%d')}" if published_at else ""
        
        message_text = (
            f"🎮 <b>{mod['title']}</b> — версия {version_number}\n\n"
            f"🏷️ Тип: {type_emoji} {type_name}\n"
            f"🔧 Загрузчики: {loaders_str}\n"
            f"🎮 Minecraft: {mc_str}"
            f"{size_str}"
            f"{date_str}\n\n"
            f"📥 <b>Нажмите кнопку ниже для скачивания</b>\n\n"
            f"💡 <i>Типы версий:</i> 🟢 релиз, 🔵 бета, 🟣 альфа"
        )
        
        keyboard = kb.version_detail_keyboard(mod_id, version_id, version_number, download_url, query, mod_page, ver_page)
        
        await call.message.edit_text(message_text, parse_mode="HTML", reply_markup=keyboard)
        await call.answer()
        
    except Exception as e:
        logging.error(f"Ошибка в select_version_callback: {e}")
        await call.answer("❌ Ошибка при загрузке версии", show_alert=True)


@dp.callback_query(F.data.startswith("download_latest:"))
async def download_latest_callback(call: types.CallbackQuery):
    """Скачивание последней версии мода"""
    try:
        _, mod_id = call.data.split(":", 1)
        
        versions = await db.get_mod_versions(mod_id)
        if not versions:
            await call.answer("❌ Нет версий для скачивания", show_alert=True)
            return
        
        latest_version = versions[0]
        download_url = latest_version.get('download_url')
        filename = latest_version.get('filename', f'{mod_id}.jar')
        
        if not download_url:
            await call.answer("❌ Ссылка для скачивания не найдена", show_alert=True)
            return
        
        await call.answer("⏳ Скачиваю файл...")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url) as resp:
                if resp.status != 200:
                    await call.answer("❌ Ошибка при скачивании", show_alert=True)
                    return
                
                file_data = await resp.read()
                
                await call.message.answer_document(
                    document=BufferedInputFile(file_data, filename=filename),
                    caption=f"📥 {filename}"
                )
        
        await call.answer("✅ Файл отправлен!")
        
    except Exception as e:
        logging.error(f"Ошибка при скачивании: {e}")
        await call.answer("❌ Ошибка при скачивании", show_alert=True)


@dp.callback_query(F.data.startswith("download_version:"))
async def download_version_callback(call: types.CallbackQuery):
    """Скачивание конкретной версии мода"""
    try:
        _, version_id = call.data.split(":", 1)
        
        pool = db.get_pool()
        if pool is None:
            await call.answer("❌ База данных не готова", show_alert=True)
            return
        
        async with pool.acquire() as conn:
            version = await conn.fetchrow("SELECT download_url, filename FROM versions WHERE id = $1", version_id)
        
        if not version or not version['download_url']:
            await call.answer("❌ Ссылка для скачивания не найдена", show_alert=True)
            return
        
        download_url = version['download_url']
        filename = version['filename'] or f'{version_id}.jar'
        
        await call.answer("⏳ Скачиваю файл...")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url) as resp:
                if resp.status != 200:
                    await call.answer("❌ Ошибка при скачивании", show_alert=True)
                    return
                
                file_data = await resp.read()
                
                await call.message.answer_document(
                    document=BufferedInputFile(file_data, filename=filename),
                    caption=f"📥 {filename}"
                )
        
        await call.answer("✅ Файл отправлен!")
        
    except Exception as e:
        logging.error(f"Ошибка при скачивании: {e}")
        await call.answer("❌ Ошибка при скачивании", show_alert=True)


@dp.callback_query(F.data.startswith("back_to_mod:"))
async def back_to_mod_callback(call: types.CallbackQuery):
    """Возврат к карточке мода из списка версий"""
    try:
        _, mod_id, query, mod_page = call.data.split(":", 3)
        mod_page = int(mod_page)
        
        pool = db.get_pool()
        if pool is None:
            await call.answer("❌ База данных не готова", show_alert=True)
            return
        
        async with pool.acquire() as conn:
            mod = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
        
        if not mod:
            await call.answer("❌ Мод не найден", show_alert=True)
            return
        
        versions = await db.get_mod_versions(mod_id)
        total_versions = len(versions)
        loaders = await db.get_all_mod_loaders(mod_id)
        
        subs = await db.get_user_subscriptions(call.from_user.id)
        is_subscribed = any(s['mod_id'] == mod_id for s in subs)
        
        mod_dict = dict(mod)
        message_text = utils.format_mod_message(mod_dict, versions[0] if versions else None, loaders, total_versions)
        
        keyboard = kb.mod_details_keyboard(mod_id, query, mod_page, is_subscribed, total_versions)
        
        await call.message.edit_text(message_text, parse_mode="HTML", reply_markup=keyboard)
        await call.answer()
        
    except Exception as e:
        logging.error(f"Ошибка в back_to_mod_callback: {e}")
        await call.answer("❌ Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("back_to_versions:"))
async def back_to_versions_callback(call: types.CallbackQuery):
    """Возврат к списку версий из деталей версии"""
    try:
        _, mod_id, query, mod_page, ver_page = call.data.split(":", 4)
        mod_page = int(mod_page)
        ver_page = int(ver_page)
        
        versions = await db.get_mod_versions(mod_id)
        
        keyboard = kb.versions_list_keyboard(mod_id, versions, query, mod_page, ver_page)
        
        await call.message.edit_text(
            f"📦 <b>Выберите версию</b>\n\nВсего версий: {len(versions)}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await call.answer()
        
    except Exception as e:
        logging.error(f"Ошибка в back_to_versions_callback: {e}")
        await call.answer("❌ Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("back:"))
async def back_callback(call: types.CallbackQuery):
    _, query, page = call.data.split(":", 2)
    page = int(page)
    
    results = await utils.search_mods_cached(query, 50)
    if not results:
        await call.answer("Ничего не найдено")
        return
    
    keyboard = kb.mods_keyboard(results, page, query)
    await call.message.edit_text(
        f"🔍 <b>Результаты</b> \"{query}\" ({len(results)}):",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await call.answer()


@dp.callback_query(F.data == "new_search")
async def new_search_callback(call: types.CallbackQuery):
    await call.message.edit_text("🔍 Введите название мода для поиска:")
    await call.answer()


# ==================== ПОДПИСКИ ====================

@dp.callback_query(F.data.startswith("sub:"))
async def subscribe_callback(call: types.CallbackQuery):
    _, mod_id, query, mod_page, ver_page = call.data.split(":", 4)
    mod_page = int(mod_page)
    ver_page = int(ver_page)
    user_id = call.from_user.id
    
    pool = db.get_pool()
    if pool is None:
        await call.answer("❌ БД не готова")
        return
    
    async with pool.acquire() as conn:
        mod = await conn.fetchrow("SELECT title FROM mods WHERE id = $1", mod_id)
    
    if not mod:
        await call.answer("❌ Мод не найден")
        return
    
    versions = await db.get_mod_versions(mod_id)
    last_ver = versions[0]['version_number'] if versions else None
    
    await db.add_subscription(user_id, mod_id, mod['title'], last_ver)
    
    # Обновляем карточку
    async with pool.acquire() as conn:
        mod_full = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
    
    total_versions = len(versions)
    loaders = await db.get_all_mod_loaders(mod_id)
    
    mod_dict = dict(mod_full)
    message_text = utils.format_mod_message(mod_dict, versions[0] if versions else None, loaders, total_versions)
    message_text += "\n\n🔔 Вы подписаны на обновления!"
    
    keyboard = kb.mod_details_keyboard(mod_id, query, mod_page, True, total_versions)
    
    await call.message.edit_text(message_text, parse_mode="HTML", reply_markup=keyboard)
    await call.answer("✅ Подписка оформлена")


@dp.callback_query(F.data.startswith("unsub:"))
async def unsubscribe_callback(call: types.CallbackQuery):
    _, mod_id, query, mod_page, ver_page = call.data.split(":", 4)
    mod_page = int(mod_page)
    ver_page = int(ver_page)
    user_id = call.from_user.id
    
    await db.remove_subscription(user_id, mod_id)
    
    pool = db.get_pool()
    if pool is None:
        await call.answer("❌ БД не готова")
        return
    
    versions = await db.get_mod_versions(mod_id)
    total_versions = len(versions)
    loaders = await db.get_all_mod_loaders(mod_id)
    
    async with pool.acquire() as conn:
        mod_full = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
    
    mod_dict = dict(mod_full)
    message_text = utils.format_mod_message(mod_dict, versions[0] if versions else None, loaders, total_versions)
    message_text += "\n\n❌ Вы отписались от обновлений"
    
    keyboard = kb.mod_details_keyboard(mod_id, query, mod_page, False, total_versions)
    
    await call.message.edit_text(message_text, parse_mode="HTML", reply_markup=keyboard)
    await call.answer("✅ Отписка выполнена")


# ==================== ПОДПИСКИ (СПИСОК) ====================

@dp.callback_query(F.data.startswith("sub_show:"))
async def sub_show_callback(call: types.CallbackQuery):
    _, mod_id, page = call.data.split(":", 2)
    page = int(page)
    
    pool = db.get_pool()
    if pool is None:
        await call.answer("❌ БД не готова")
        return
    
    async with pool.acquire() as conn:
        mod = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
    
    if not mod:
        await call.answer("❌ Мод не найден")
        return
    
    versions = await db.get_mod_versions(mod_id)
    total_versions = len(versions)
    loaders = await db.get_all_mod_loaders(mod_id)
    
    mod_dict = dict(mod)
    message_text = utils.format_mod_message(mod_dict, versions[0] if versions else None, loaders, total_versions)
    message_text += "\n\n📋 В ваших подписках"
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="❌ Отписаться", callback_data=f"sub_del:{mod_id}:{page}")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"subs_back:{page}")]
    ])
    
    await call.message.edit_text(message_text, parse_mode="HTML", reply_markup=keyboard)
    await call.answer()


@dp.callback_query(F.data.startswith("sub_del:"))
async def sub_delete_callback(call: types.CallbackQuery):
    _, mod_id, page = call.data.split(":", 2)
    page = int(page)
    
    await db.remove_subscription(call.from_user.id, mod_id)
    
    subs = await db.get_user_subscriptions(call.from_user.id)
    
    if not subs:
        await call.message.edit_text("📋 У вас больше нет подписок")
    else:
        keyboard = kb.subscriptions_keyboard(subs, page)
        await call.message.edit_text(f"📋 <b>Ваши подписки</b> ({len(subs)}):", parse_mode="HTML", reply_markup=keyboard)
    
    await call.answer("✅ Отписано")


@dp.callback_query(F.data.startswith("subs_back:"))
async def subs_back_callback(call: types.CallbackQuery):
    _, page = call.data.split(":", 1)
    page = int(page)
    
    subs = await db.get_user_subscriptions(call.from_user.id)
    keyboard = kb.subscriptions_keyboard(subs, page)
    
    await call.message.edit_text(f"📋 <b>Ваши подписки</b> ({len(subs)}):", parse_mode="HTML", reply_markup=keyboard)
    await call.answer()


@dp.callback_query(F.data == "subs_refresh")
async def subs_refresh_callback(call: types.CallbackQuery):
    subs = await db.get_user_subscriptions(call.from_user.id)
    
    if not subs:
        await call.message.edit_text("📋 У вас нет подписок")
        await call.answer("✅ Обновлено")
        return
    
    keyboard = kb.subscriptions_keyboard(subs, 0)
    new_text = f"📋 <b>Ваши подписки</b> ({len(subs)}):"
    
    try:
        await call.message.edit_text(new_text, parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        if "message is not modified" in str(e):
            await call.message.edit_reply_markup(reply_markup=keyboard)
        else:
            raise e
    
    await call.answer("✅ Обновлено")


@dp.callback_query(F.data.startswith("subs_page:"))
async def subs_page_callback(call: types.CallbackQuery):
    _, page = call.data.split(":", 1)
    page = int(page)
    
    subs = await db.get_user_subscriptions(call.from_user.id)
    keyboard = kb.subscriptions_keyboard(subs, page)
    
    try:
        await call.message.edit_reply_markup(reply_markup=keyboard)
    except Exception as e:
        if "message is not modified" in str(e):
            pass
        else:
            raise e
    
    await call.answer()


# ==================== ГЛАВНОЕ МЕНЮ ====================

@dp.callback_query(F.data == "main_menu")
async def main_menu_callback(call: types.CallbackQuery):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📋 Мои подписки", callback_data="mysubs_menu")],
        [types.InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help_menu")]
    ])
    
    await call.message.edit_text(
        "👋 <b>Главное меню</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    await call.answer()


@dp.callback_query(F.data == "mysubs_menu")
async def mysubs_menu_callback(call: types.CallbackQuery):
    subs = await db.get_user_subscriptions(call.from_user.id)
    
    if not subs:
        await call.message.edit_text("📋 У вас нет подписок")
    else:
        keyboard = kb.subscriptions_keyboard(subs, 0)
        await call.message.edit_text(f"📋 <b>Ваши подписки</b> ({len(subs)}):", parse_mode="HTML", reply_markup=keyboard)
    await call.answer()


@dp.callback_query(F.data == "help_menu")
async def help_menu_callback(call: types.CallbackQuery):
    await cmd_help(call.message)
    await call.answer()


@dp.callback_query(F.data == "noop")
async def noop_callback(call: types.CallbackQuery):
    await call.answer()


# ==================== ЗАПУСК ====================

async def main():
    global BOT_ID
    
    if not config.validate_config():
        return
    
    logging.info("🚀 ЗАПУСК БОТА")
    
    # Проверяем, нет ли уже запущенного бота
    try:
        bot_info = await bot.get_me()
        BOT_ID = bot_info.id
        logging.info(f"✅ Бот: @{bot_info.username} (ID: {BOT_ID})")
    except Exception as e:
        logging.error(f"❌ Не удалось получить информацию о боте: {e}")
        return
    
    # Инициализация БД
    await db.init_database()
    cache.init_redis()
    utils.load_mod_aliases()
    await utils.load_mod_names_cache()
    
    # Запускаем поллинг с увеличенным таймаутом
    try:
        # Устанавливаем меньший таймаут для избежания конфликтов
        await dp.start_polling(bot, polling_timeout=30)
    except Exception as e:
        logging.error(f"❌ Ошибка при запуске поллинга: {e}")
    finally:
        await db.close_database()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Бот остановлен")