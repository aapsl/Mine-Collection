import asyncio
import logging
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

from dotenv import load_dotenv
load_dotenv()

# Простые импорты модулей целиком
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
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Новый поиск")],
            [KeyboardButton(text="📋 Мои подписки")],
            [KeyboardButton(text="ℹ️ Помощь")]
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
    
    # Базовое приветствие для всех
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
    
    # Добавляем админ-команды только для админов
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
    
    await message.answer(
        welcome_text,
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


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
    
    # Добавляем админ-команды только для админов
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
    """Полная справка по админ-командам (только для админов)"""
    user_id = message.from_user.id
    
    if user_id not in config.ADMIN_IDS:
        await message.answer("❌ У вас нет прав для выполнения этой команды")
        return
    
    await message.answer(
        "⚙️ <b>Полный список админ-команд</b>\n\n"
        "📊 <b>Статистика и мониторинг:</b>\n"
        "• /stats - Общая статистика БД\n"
        "• /check_db - Детальная проверка БД\n"
        "• /user_stats - Статистика пользователей и топ подписок\n"
        "• /check_mod [название] - Проверить наличие мода\n\n"
        
        "🔄 <b>Управление кэшем:</b>\n"
        "• /reload_cache - Перезагрузить кэш поиска\n"
        "• /reload_aliases - Перезагрузить псевдонимы\n"
        "• /reset_cache - Полный сброс кэша (Redis + локальный)\n\n"
        
        "📨 <b>Рассылка:</b>\n"
        "• /broadcast [текст] - Отправить сообщение всем пользователям\n"
        "• После ввода команды потребуется подтверждение\n\n"
        
        "❓ <b>Справка:</b>\n"
        "• /help_admin - Эта справка\n\n"
        
        "💡 <b>Советы:</b>\n"
        "• Все админ-команды логируются\n"
        "• Рассылку нельзя отменить после подтверждения\n"
        "• Кэш можно сбрасывать при проблемах с поиском",
        parse_mode="HTML"
    )

@dp.message(Command("mysubs"))
async def cmd_mysubs(message: Message):
    user_id = message.from_user.id
    logging.info(f"📋 /mysubs от {user_id}")
    
    subs = await db.get_user_subscriptions(user_id)
    
    if not subs:
        await message.answer("📋 У вас нет подписок")
        return
    
    keyboard = kb.subscriptions_keyboard(subs)
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
    # Очищаем локальный кэш
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

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("❌ Укажите текст для рассылки\n\nПример: `/broadcast Всем привет!`", parse_mode="HTML")
        return
    
    await message.answer(
        f"📨 Начинаю рассылку:\n\n<i>{text[:200]}</i>\n\n⚠️ Продолжить?",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="✅ Да", callback_data=f"broadcast_confirm:{text}"),
             types.InlineKeyboardButton(text="❌ Нет", callback_data="broadcast_cancel")]
        ])
    )

@dp.callback_query(F.data.startswith("broadcast_confirm:"))
async def broadcast_confirm_callback(call: types.CallbackQuery):
    if call.from_user.id not in config.ADMIN_IDS:
        await call.answer("❌ Нет прав")
        return
    
    text = call.data.split(":", 1)[1]
    await call.message.edit_text("📨 Идёт рассылка...")
    
    users = await db.get_all_users()
    total = len(users)
    
    if total == 0:
        await call.message.edit_text("❌ Нет пользователей")
        return
    
    success = 0
    for i, user_id in enumerate(users):
        try:
            await call.bot.send_message(user_id, text, parse_mode="HTML")
            success += 1
            if i % 30 == 0:
                await asyncio.sleep(1)
        except:
            pass
        
        if (i + 1) % 100 == 0:
            await call.message.edit_text(f"📨 {success}/{total}")
    
    await call.message.edit_text(f"✅ Рассылка завершена\n\nУспешно: {success}/{total}")
    await call.answer()

@dp.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel_callback(call: types.CallbackQuery):
    if call.from_user.id not in config.ADMIN_IDS:
        await call.answer("❌ Нет прав")
        return
    await call.message.edit_text("❌ Рассылка отменена")
    await call.answer()

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

@dp.message(Command("help_admin"))
async def cmd_help_admin(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    
    await message.answer(
        "⚙️ <b>Админ-команды</b>\n\n"
        "/stats - Статистика\n"
        "/check_db - Проверка БД\n"
        "/reload_cache - Перезагрузка кэша\n"
        "/reload_aliases - Перезагрузка псевдонимов\n"
        "/reset_cache - Сброс кэша\n"
        "/user_stats - Статистика пользователей\n"
        "/broadcast [текст] - Рассылка\n"
        "/check_mod [название] - Проверка мода\n"
        "/help_admin - Эта справка",
        parse_mode="HTML"
    )

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

@dp.message(F.text & ~F.text.startswith('/'))
async def search_mods(message: Message):
    query = message.text.strip()
    
    # Логируем запрос пользователя
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
        parts = call.data.split(":", 3)  # Максимум 4 части: mod, id, query, page
        
        if len(parts) < 4:
            logging.error(f"Неверный формат callback_data: {call.data}")
            await call.answer("❌ Ошибка формата данных", show_alert=True)
            return
        
        _, mod_id, query, page_str = parts
        
        # Безопасное преобразование page в число
        try:
            page = int(page_str)
        except ValueError:
            logging.error(f"Неверный формат page: '{page_str}' в {call.data}")
            # Пробуем извлечь число из строки
            import re
            numbers = re.findall(r'\d+', page_str)
            if numbers:
                page = int(numbers[0])
            else:
                page = 0
        
        pool = db.get_pool()
        if pool is None:
            await call.answer("❌ База данных не готова", show_alert=True)
            return
        
        # Получаем информацию о моде
        async with pool.acquire() as conn:
            mod = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
        
        if not mod:
            await call.answer("❌ Мод не найден", show_alert=True)
            return
        
        # Получаем версии
        versions = await db.get_mod_versions(mod_id)
        if not versions:
            await call.answer("❌ Нет версий для этого мода", show_alert=True)
            return
        
        # Получаем загрузчики
        loaders = await db.get_all_mod_loaders(mod_id)
        
        # Форматируем сообщение
        mod_dict = dict(mod)
        message_text = utils.format_mod_message(mod_dict, versions[0], loaders)
        message_text += f"\n\n📦 Всего версий: {len(versions)}"
        
        # Проверяем подписку
        subs = await db.get_user_subscriptions(call.from_user.id)
        is_subscribed = any(s['mod_id'] == mod_id for s in subs)
        
        # Создаём клавиатуру
        keyboard = kb.versions_keyboard(mod_id, versions, query, page, 0, is_subscribed)
        
        await call.message.edit_text(message_text, parse_mode="HTML", reply_markup=keyboard)
        await call.answer()
        
    except Exception as e:
        logging.error(f"Ошибка в mod_callback: {e}")
        logging.error(f"Callback data: {call.data}")
        await call.answer("❌ Произошла ошибка при открытии мода", show_alert=True)

@dp.callback_query(F.data.startswith("version:"))
async def version_callback(call: types.CallbackQuery):
    _, mod_id, ver_id, query, mod_page, ver_page = call.data.split(":", 6)
    mod_page = int(mod_page)
    ver_page = int(ver_page)
    
    pool = db.get_pool()
    if pool is None:
        await call.answer("БД не готова")
        return
    
    async with pool.acquire() as conn:
        mod = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
        ver = await conn.fetchrow("SELECT * FROM versions WHERE id = $1", ver_id)
    
    if not mod or not ver:
        await call.answer("Данные не найдены")
        return
    
    text = utils.format_mod_message(dict(mod), dict(ver))
    
    versions = await db.get_mod_versions(mod_id)
    subs = await db.get_user_subscriptions(call.from_user.id)
    is_subscribed = any(s['mod_id'] == mod_id for s in subs)
    
    keyboard = kb.versions_keyboard(mod_id, versions, query, mod_page, ver_page, is_subscribed)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await call.answer()

@dp.callback_query(F.data.startswith("ver_page:"))
async def ver_page_callback(call: types.CallbackQuery):
    _, mod_id, ver_page, query, mod_page = call.data.split(":", 4)
    ver_page = int(ver_page)
    mod_page = int(mod_page)
    
    pool = db.get_pool()
    if pool is None:
        await call.answer("БД не готова")
        return
    
    async with pool.acquire() as conn:
        mod = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
    
    if not mod:
        await call.answer("Мод не найден")
        return
    
    versions = await db.get_mod_versions(mod_id)
    loaders = await db.get_all_mod_loaders(mod_id)
    
    text = utils.format_mod_message(dict(mod), versions[0] if versions else None, loaders)
    
    subs = await db.get_user_subscriptions(call.from_user.id)
    is_subscribed = any(s['mod_id'] == mod_id for s in subs)
    
    keyboard = kb.versions_keyboard(mod_id, versions, query, mod_page, ver_page, is_subscribed)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await call.answer()

@dp.callback_query(F.data.startswith("sub:"))
async def subscribe_callback(call: types.CallbackQuery):
    _, mod_id, query, mod_page, ver_page = call.data.split(":", 4)
    mod_page = int(mod_page)
    ver_page = int(ver_page)
    user_id = call.from_user.id
    
    pool = db.get_pool()
    if pool is None:
        await call.answer("БД не готова")
        return
    
    async with pool.acquire() as conn:
        mod = await conn.fetchrow("SELECT title FROM mods WHERE id = $1", mod_id)
    
    if not mod:
        await call.answer("Мод не найден")
        return
    
    versions = await db.get_mod_versions(mod_id)
    last_ver = versions[0]['version_number'] if versions else None
    
    await db.add_subscription(user_id, mod_id, mod['title'], last_ver)
    
    versions = await db.get_mod_versions(mod_id)
    loaders = await db.get_all_mod_loaders(mod_id)
    async with pool.acquire() as conn:
        mod_full = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
    
    text = utils.format_mod_message(dict(mod_full), versions[0] if versions else None, loaders)
    text += "\n\n🔔 Вы подписаны на обновления!"
    
    keyboard = kb.versions_keyboard(mod_id, versions, query, mod_page, ver_page, True)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
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
        await call.answer("БД не готова")
        return
    
    versions = await db.get_mod_versions(mod_id)
    loaders = await db.get_all_mod_loaders(mod_id)
    async with pool.acquire() as conn:
        mod_full = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
    
    text = utils.format_mod_message(dict(mod_full), versions[0] if versions else None, loaders)
    text += "\n\n❌ Вы отписались от обновлений"
    
    keyboard = kb.versions_keyboard(mod_id, versions, query, mod_page, ver_page, False)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await call.answer("✅ Отписка выполнена")

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

@dp.callback_query(F.data.startswith("sub_show:"))
async def sub_show_callback(call: types.CallbackQuery):
    _, mod_id, page = call.data.split(":", 2)
    page = int(page)
    
    pool = db.get_pool()
    if pool is None:
        await call.answer("БД не готова")
        return
    
    async with pool.acquire() as conn:
        mod = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
    
    if not mod:
        await call.answer("Мод не найден")
        return
    
    versions = await db.get_mod_versions(mod_id)
    loaders = await db.get_all_mod_loaders(mod_id)
    
    text = utils.format_mod_message(dict(mod), versions[0] if versions else None, loaders)
    text += "\n\n📋 В ваших подписках"
    
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="❌ Отписаться", callback_data=f"sub_del:{mod_id}:{page}")],
        [types.InlineKeyboardButton(text="⬅️ Назад", callback_data=f"subs_back:{page}")]
    ])
    
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
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
    """Обновление списка подписок"""
    subs = await db.get_user_subscriptions(call.from_user.id)
    
    if not subs:
        await call.message.edit_text("📋 У вас нет подписок")
        await call.answer("✅ Обновлено")
        return
    
    keyboard = kb.subscriptions_keyboard(subs, 0)
    new_text = f"📋 <b>Ваши подписки</b> ({len(subs)}):"
    
    # Получаем текущее сообщение
    current_text = call.message.text or ""
    current_markup = call.message.reply_markup
    
    # Проверяем, изменилось ли содержимое
    text_changed = current_text != new_text
    markup_changed = str(current_markup) != str(keyboard) if current_markup else True
    
    try:
        if text_changed and markup_changed:
            # Изменилось и то, и другое
            await call.message.edit_text(new_text, parse_mode="HTML", reply_markup=keyboard)
        elif text_changed:
            # Изменился только текст
            await call.message.edit_text(new_text, parse_mode="HTML")
            await call.message.edit_reply_markup(reply_markup=keyboard)
        elif markup_changed:
            # Изменилась только клавиатура
            await call.message.edit_reply_markup(reply_markup=keyboard)
        else:
            # Ничего не изменилось, просто отвечаем
            await call.answer("✅ Список актуален")
            return
    except Exception as e:
        if "message is not modified" in str(e):
            await call.answer("✅ Список актуален")
        else:
            logging.error(f"Ошибка при обновлении подписок: {e}")
            await call.answer("❌ Ошибка при обновлении", show_alert=True)
    
    await call.answer("✅ Обновлено")

@dp.callback_query(F.data.startswith("subs_page:"))
async def subs_page_callback(call: types.CallbackQuery):
    """Переключение страниц подписок"""
    _, page = call.data.split(":", 1)
    page = int(page)
    
    subs = await db.get_user_subscriptions(call.from_user.id)
    keyboard = kb.subscriptions_keyboard(subs, page)
    
    try:
        # Пробуем обновить только клавиатуру
        await call.message.edit_reply_markup(reply_markup=keyboard)
    except Exception as e:
        if "message is not modified" in str(e):
            # Клавиатура не изменилась, ничего страшного
            pass
        else:
            logging.error(f"Ошибка при смене страницы: {e}")
    
    await call.answer()

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
    """Меню подписок из главного меню"""
    subs = await db.get_user_subscriptions(call.from_user.id)
    
    if not subs:
        await call.message.edit_text("📋 У вас нет подписок")
    else:
        keyboard = kb.subscriptions_keyboard(subs, 0)
        await call.message.edit_text(
            f"📋 <b>Ваши подписки</b> ({len(subs)}):",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    await call.answer()

@dp.callback_query(F.data == "help_menu")
async def help_menu_callback(call: types.CallbackQuery):
    await cmd_help(call.message)
    await call.answer()

@dp.callback_query(F.data == "noop")
async def noop_callback(call: types.CallbackQuery):
    """Заглушка для кнопок, которые ничего не делают"""
    await call.answer()
# ==================== ЗАПУСК ====================

async def main():
    global BOT_ID
    
    if not config.validate_config():
        return
    
    logging.info("🚀 ЗАПУСК БОТА")
    
    # СНАЧАЛА инициализируем БД
    await db.init_database()
    logging.info("✅ База данных инициализирована")
    
    # Потом получаем информацию о боте
    bot_info = await bot.get_me()
    BOT_ID = bot_info.id
    logging.info(f"✅ Бот: @{bot_info.username}")
    
    # Затем остальные компоненты
    cache.init_redis()
    utils.load_mod_aliases()
    await utils.load_mod_names_cache()
    
    # Фоновая задача
    update_task = asyncio.create_task(check_mod_updates(bot))
    
    try:
        await dp.start_polling(bot)
    finally:
        update_task.cancel()
        await db.close_database()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Бот остановлен")