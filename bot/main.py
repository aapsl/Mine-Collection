import asyncio
import logging
import sys
import os
import time
import urllib.parse
from datetime import datetime

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile

# Добавляем путь к проекту
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
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Новый поиск")],
            [KeyboardButton(text="📋 Мои подписки")],
            [KeyboardButton(text="ℹ️ Помощь")]
        ],
        resize_keyboard=True
    )


def admin_keyboard() -> ReplyKeyboardMarkup:
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


@dp.message(Command("mysubs"))
async def cmd_mysubs(message: Message):
    user_id = message.from_user.id
    subs = await db.get_user_subscriptions(user_id)
    if not subs:
        await message.answer(
            "📋 У вас пока нет подписок.\n\n"
            "Чтобы подписаться, найдите мод и нажмите '🔔 Подписаться'"
        )
        return
    keyboard = kb.subscriptions_keyboard(subs, 0)
    await message.answer(f"📋 <b>Ваши подписки</b> ({len(subs)}):", parse_mode="HTML", reply_markup=keyboard)



# ==================== ОБРАБОТЧИКИ КНОПОК ГЛАВНОГО МЕНЮ ====================

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
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ У вас нет прав")
        return
    await message.answer(
        "⚙️ <b>Админ-панель</b>\n\n"
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


# ==================== ПОИСК ====================

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
    logging.info(f"⏱️ Поиск '{query}' занял {elapsed:.0f} мс, найдено {len(results)}")
    if not results:
        await message.answer(f"🔍 По запросу \"{query}\" ничего не найдено")
        return
    keyboard = kb.mods_keyboard(results, 0, query)
    await message.answer(
        f"🔍 <b>Результаты</b> \"{query}\" ({len(results)}):",
        parse_mode="HTML",
        reply_markup=keyboard
    )



# ==================== CALLBACK-ОБРАБОТЧИКИ ПОИСКА ====================

@dp.callback_query(F.data.startswith("page:"))
async def page_callback(call: types.CallbackQuery):
    _, page, query = call.data.split(":", 2)
    page = int(page)
    query = urllib.parse.unquote(query)
    results = await utils.search_mods_cached(query, 50)
    if not results:
        await call.answer("Ничего не найдено")
        return
    keyboard = kb.mods_keyboard(results, page, query)
    await call.message.edit_reply_markup(reply_markup=keyboard)
    await call.answer()


@dp.callback_query(F.data.startswith("mod:"))
async def mod_callback(call: types.CallbackQuery):
    try:
        _, mod_id, encoded_query, page = call.data.split(":", 3)
        page = int(page)
        query = urllib.parse.unquote(encoded_query)
        logging.info(f"MOD_CALLBACK: запрос '{query}' (закодирован {encoded_query})")
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
        subs = await db.get_user_subscriptions(call.from_user.id)
        is_subscribed = any(s['mod_id'] == mod_id for s in subs)
        text = utils.format_mod_message(dict(mod), versions[0] if versions else None, loaders, total_versions)
        keyboard = kb.mod_details_keyboard(mod_id, query, page, is_subscribed, total_versions, source="search")
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await call.answer()
        asyncio.create_task(_update_versions_background(mod_id))
    except Exception as e:
        logging.error(f"mod_callback: {e}")
        await call.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("show_versions:"))
async def show_versions_callback(call: types.CallbackQuery):
    try:
        _, mod_id, query, mod_page = call.data.split(":", 3)
        mod_page = int(mod_page)
        query = urllib.parse.unquote(query)
        logging.info(f"show_versions_callback: получен query = '{query}'")
        # показать загрузку
        loading = await call.message.edit_text(
            "📦 <b>Загрузка списка версий...</b>\n\n🔄 Пожалуйста, подождите",
            parse_mode="HTML"
        )
        versions = await db.get_mod_versions(mod_id)
        if not versions:
            await loading.edit_text("❌ Нет доступных версий")
            await call.answer()
            return
        keyboard = kb.versions_list_keyboard(mod_id, versions, query, mod_page, 0)
        await loading.edit_text(
            f"📦 <b>Выберите версию</b>\n\nВсего версий: {len(versions)}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await call.answer()
    except Exception as e:
        logging.error(f"show_versions_callback: {e}")
        await call.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("versions_page:"))
async def versions_page_callback(call: types.CallbackQuery):
    try:
        _, mod_id, ver_page, query, mod_page = call.data.split(":", 4)
        ver_page = int(ver_page)
        mod_page = int(mod_page)
        query = urllib.parse.unquote(query)
        versions = await db.get_mod_versions(mod_id)
        keyboard = kb.versions_list_keyboard(mod_id, versions, query, mod_page, ver_page)
        await call.message.edit_reply_markup(reply_markup=keyboard)
        await call.answer()
    except Exception as e:
        logging.error(f"versions_page_callback: {e}")
        await call.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("select_version:"))
async def select_version_callback(call: types.CallbackQuery):
    try:
        _, mod_id, version_id, query, mod_page, ver_page = call.data.split(":", 6)
        mod_page = int(mod_page)
        ver_page = int(ver_page)
        query = urllib.parse.unquote(query)
        logging.info(f"select_version_callback: получен query = '{query}'")
        pool = db.get_pool()
        if pool is None:
            await call.answer("❌ БД не готова")
            return
        async with pool.acquire() as conn:
            version = await conn.fetchrow("SELECT * FROM versions WHERE id = $1", version_id)
            mod = await conn.fetchrow("SELECT title, slug FROM mods WHERE id = $1", mod_id)
        if not version or not mod:
            await call.answer("Данные не найдены")
            return
        vn = version['version_number']
        vtype = version['version_type']
        loaders = version['loaders']
        game_vers = version['game_versions']
        pub = version['published_at']
        fsize = version['file_size']
        dl_url = version['download_url']
        type_emoji = "🟢" if vtype == 'release' else ("🔵" if vtype == 'beta' else "🟣")
        type_name = "Релиз" if vtype == 'release' else ("Бета" if vtype == 'beta' else "Альфа")
        loaders_str = ", ".join(loaders) if loaders else "Не указано"
        mc_str = ", ".join(game_vers[:3]) if game_vers else "Не указано"
        if len(game_vers) > 3:
            mc_str += f" +{len(game_vers)-3}"
        size_str = ""
        if fsize:
            if fsize < 1024*1024:
                size_str = f"\n📦 Размер: {fsize/1024:.1f} КБ"
            else:
                size_str = f"\n📦 Размер: {fsize/(1024*1024):.1f} МБ"
        date_str = f"\n📅 Дата: {pub.strftime('%Y-%m-%d')}" if pub else ""
        text = (
            f"🎮 <b>{mod['title']}</b> — версия {vn}\n\n"
            f"🏷️ Тип: {type_emoji} {type_name}\n"
            f"🔧 Загрузчики: {loaders_str}\n"
            f"🎮 Minecraft: {mc_str}{size_str}{date_str}\n\n"
            f"📥 Нажмите кнопку ниже для скачивания\n\n"
            f"💡 Типы версий: 🟢 релиз, 🔵 бета, 🟣 альфа"
        )
        keyboard = kb.version_detail_keyboard(mod_id, version_id, vn, dl_url, query, mod_page, ver_page, fsize)
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await call.answer()
    except Exception as e:
        logging.error(f"select_version_callback: {e}")
        await call.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("back_to_versions:"))
async def back_to_versions_callback(call: types.CallbackQuery):
    try:
        _, mod_id, query, mod_page, ver_page = call.data.split(":", 4)
        mod_page = int(mod_page)
        ver_page = int(ver_page)
        query = urllib.parse.unquote(query)
        logging.info(f"back_to_versions_callback: получен query = '{query}'")
        versions = await db.get_mod_versions(mod_id)
        keyboard = kb.versions_list_keyboard(mod_id, versions, query, mod_page, ver_page)
        await call.message.edit_text(
            f"📦 <b>Выберите версию</b>\n\nВсего версий: {len(versions)}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await call.answer()
    except Exception as e:
        logging.error(f"back_to_versions_callback: {e}")
        await call.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("back:"))
async def back_callback(call: types.CallbackQuery):
    try:
        _, encoded_query, page = call.data.split(":", 2)
        page = int(page)
        query = urllib.parse.unquote(encoded_query)
        logging.info(f"BACK: получен запрос '{query}' (закодирован {encoded_query})")
        
        if not query or query == '':
            # показать главное меню
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="📋 Мои подписки", callback_data="mysubs_menu")],
                [types.InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help_menu")]
            ])
            await call.message.edit_text("👋 Главное меню", reply_markup=keyboard)
            await call.answer()
            return
        
        results = await utils.search_mods_cached(query, 50)
        if not results:
            await call.answer("Ничего не найдено")
            return
        
        total_pages = (len(results) + 9) // 10
        if page >= total_pages and total_pages > 0:
            page = total_pages - 1
        
        keyboard = kb.mods_keyboard(results, page, query)
        await call.message.edit_text(f"🔍 Результаты \"{query}\" ({len(results)}):", parse_mode="HTML", reply_markup=keyboard)
        await call.answer()
    except Exception as e:
        logging.error(f"back_callback: {e}")
        await call.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("back_to_mod:"))
async def back_to_mod_callback(call: types.CallbackQuery):
    """Возврат к карточке мода из списка версий (для поиска)"""
    try:
        _, mod_id, query, page = call.data.split(":", 3)
        page = int(page)
        query = urllib.parse.unquote(query)
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
        subs = await db.get_user_subscriptions(call.from_user.id)
        is_subscribed = any(s['mod_id'] == mod_id for s in subs)
        text = utils.format_mod_message(dict(mod), versions[0] if versions else None, loaders, total_versions)
        keyboard = kb.mod_details_keyboard(mod_id, query, page, is_subscribed, total_versions, source="search")
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await call.answer()
    except Exception as e:
        logging.error(f"back_to_mod_callback: {e}")
        await call.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data == "new_search")
async def new_search_callback(call: types.CallbackQuery):
    """Обработчик кнопки 'Новый поиск' в результатах"""
    await call.message.edit_text("🔍 Введите название мода для поиска:")
    await call.answer()

# ==================== ПОДПИСКИ (ИЗ КАРТОЧКИ) ====================

@dp.callback_query(F.data.startswith("subscribe:"))
async def subscribe_callback(call: types.CallbackQuery):
    try:
        parts = call.data.split(":", 4)
        if len(parts) == 5:
            _, mod_id, query, mod_page, ver_page = parts
            mod_page = int(mod_page)
            is_from_subs = False
            query = urllib.parse.unquote(query)
        elif len(parts) == 4 and parts[2] == "from_subs":
            _, mod_id, _, mod_page = parts
            mod_page = int(mod_page)
            is_from_subs = True
            query = ""
        else:
            await call.answer("Неверный формат", show_alert=True)
            return
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
        success = await db.add_subscription(user_id, mod_id, mod['title'], last_ver)
        if not success:
            await call.answer("Не удалось подписаться")
            return
        if is_from_subs:
            # обновить список подписок
            subs = await db.get_user_subscriptions(user_id)
            total_pages = (len(subs) + 9) // 10
            new_page = min(mod_page, total_pages - 1) if total_pages else 0
            keyboard = kb.subscriptions_keyboard(subs, new_page)
            await call.message.edit_text(
                f"📋 <b>Ваши подписки</b> ({len(subs)}):",
                parse_mode="HTML",
                reply_markup=keyboard
            )
        else:
            # обновить карточку мода
            total_versions = len(versions)
            loaders = await db.get_all_mod_loaders(mod_id)
            async with pool.acquire() as conn:
                mod_full = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
            text = utils.format_mod_message(dict(mod_full), versions[0] if versions else None, loaders, total_versions)
            text += "\n\n🔔 Вы подписаны на обновления!"
            keyboard = kb.mod_details_keyboard(mod_id, query, mod_page, True, total_versions, source="search")
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await call.answer(f"✅ Подписались на {mod['title']}")
    except Exception as e:
        logging.error(f"subscribe_callback: {e}")
        await call.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("unsubscribe:"))
async def unsubscribe_callback(call: types.CallbackQuery):
    try:
        parts = call.data.split(":", 4)
        if len(parts) == 5:
            _, mod_id, query, mod_page, ver_page = parts
            mod_page = int(mod_page)
            is_from_subs = False
            query = urllib.parse.unquote(query)
        elif len(parts) == 4 and parts[2] == "from_subs":
            _, mod_id, _, mod_page = parts
            mod_page = int(mod_page)
            is_from_subs = True
            query = ""
        else:
            await call.answer("Неверный формат", show_alert=True)
            return
        user_id = call.from_user.id
        success = await db.remove_subscription(user_id, mod_id)
        if not success:
            await call.answer("Не удалось отписаться")
            return
        if is_from_subs:
            subs = await db.get_user_subscriptions(user_id)
            if not subs:
                await call.message.edit_text("📋 У вас больше нет подписок")
            else:
                total_pages = (len(subs) + 9) // 10
                new_page = min(mod_page, total_pages - 1) if total_pages else 0
                keyboard = kb.subscriptions_keyboard(subs, new_page)
                await call.message.edit_text(
                    f"📋 <b>Ваши подписки</b> ({len(subs)}):",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
        else:
            versions = await db.get_mod_versions(mod_id)
            total_versions = len(versions)
            loaders = await db.get_all_mod_loaders(mod_id)
            pool = db.get_pool()
            async with pool.acquire() as conn:
                mod_full = await conn.fetchrow("SELECT * FROM mods WHERE id = $1", mod_id)
            text = utils.format_mod_message(dict(mod_full), versions[0] if versions else None, loaders, total_versions)
            text += "\n\n❌ Вы отписались от обновлений"
            keyboard = kb.mod_details_keyboard(mod_id, query, mod_page, False, total_versions, source="search")
            await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await call.answer("✅ Отписано")
    except Exception as e:
        logging.error(f"unsubscribe_callback: {e}")
        await call.answer("Ошибка", show_alert=True)


# ==================== ПОДПИСКИ (СПИСОК) ====================

@dp.callback_query(F.data.startswith("sub_show:"))
async def sub_show_callback(call: types.CallbackQuery):
    try:
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
        total_versions = len(versions)
        loaders = await db.get_all_mod_loaders(mod_id)
        text = utils.format_mod_message(dict(mod), versions[0] if versions else None, loaders, total_versions)
        text += "\n\n📋 <b>Этот мод есть в ваших подписках</b>"
        subs = await db.get_user_subscriptions(call.from_user.id)
        is_subscribed = any(s['mod_id'] == mod_id for s in subs)
        # Специальная клавиатура для подписок
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])
        action_row = []
        action_row.append(types.InlineKeyboardButton(text="📥 Скачать", callback_data=f"download_latest:{mod_id}"))
        if total_versions:
            action_row.append(types.InlineKeyboardButton(text=f"📦 Версии ({total_versions})", callback_data=f"show_versions_subs:{mod_id}:{page}"))
        keyboard.inline_keyboard.append(action_row)
        if is_subscribed:
            keyboard.inline_keyboard.append([types.InlineKeyboardButton(text="❌ Отписаться", callback_data=f"unsubscribe:{mod_id}:from_subs:{page}")])
        else:
            keyboard.inline_keyboard.append([types.InlineKeyboardButton(text="🔔 Подписаться", callback_data=f"subscribe:{mod_id}:from_subs:{page}")])
        keyboard.inline_keyboard.append([
            types.InlineKeyboardButton(text="⬅️ Назад к подпискам", callback_data=f"back_to_subs:{page}"),
            types.InlineKeyboardButton(text="🌐 Modrinth", url=f"https://modrinth.com/mod/{mod_id}")
        ])
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await call.answer()
    except Exception as e:
        logging.error(f"sub_show_callback: {e}")
        await call.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("sub_del:"))
async def sub_del_callback(call: types.CallbackQuery):
    try:
        _, mod_id, page = call.data.split(":", 2)
        page = int(page)
        await db.remove_subscription(call.from_user.id, mod_id)
        subs = await db.get_user_subscriptions(call.from_user.id)
        if not subs:
            await call.message.edit_text("📋 У вас больше нет подписок")
        else:
            total_pages = (len(subs) + 9) // 10
            new_page = min(page, total_pages - 1) if total_pages else 0
            keyboard = kb.subscriptions_keyboard(subs, new_page)
            await call.message.edit_text(
                f"📋 <b>Ваши подписки</b> ({len(subs)}):",
                parse_mode="HTML",
                reply_markup=keyboard
            )
        await call.answer("✅ Отписано")
    except Exception as e:
        logging.error(f"sub_del_callback: {e}")
        await call.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("subs_back:"))
async def subs_back_callback(call: types.CallbackQuery):
    try:
        _, page = call.data.split(":", 1)
        page = int(page)
        subs = await db.get_user_subscriptions(call.from_user.id)
        total_pages = (len(subs) + 9) // 10
        new_page = min(page, total_pages - 1) if total_pages else 0
        keyboard = kb.subscriptions_keyboard(subs, new_page)
        await call.message.edit_text(
            f"📋 <b>Ваши подписки</b> ({len(subs)}):",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await call.answer()
    except Exception as e:
        logging.error(f"subs_back_callback: {e}")
        await call.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data == "subs_refresh")
async def subs_refresh_callback(call: types.CallbackQuery):
    subs = await db.get_user_subscriptions(call.from_user.id)
    if not subs:
        await call.message.edit_text("📋 У вас нет подписок")
        await call.answer()
        return
    keyboard = kb.subscriptions_keyboard(subs, 0)
    await call.message.edit_text(f"📋 <b>Ваши подписки</b> ({len(subs)}):", parse_mode="HTML", reply_markup=keyboard)
    await call.answer("✅ Обновлено")


@dp.callback_query(F.data.startswith("subs_page:"))
async def subs_page_callback(call: types.CallbackQuery):
    try:
        _, page = call.data.split(":", 1)
        page = int(page)
        subs = await db.get_user_subscriptions(call.from_user.id)
        keyboard = kb.subscriptions_keyboard(subs, page)
        await call.message.edit_reply_markup(reply_markup=keyboard)
        await call.answer()
    except Exception as e:
        logging.error(f"subs_page_callback: {e}")
        await call.answer("Ошибка", show_alert=True)


@dp.callback_query(F.data.startswith("back_to_subs:"))
async def back_to_subs_callback(call: types.CallbackQuery):
    try:
        _, page = call.data.split(":", 1)
        page = int(page)
        subs = await db.get_user_subscriptions(call.from_user.id)
        if not subs:
            await call.message.edit_text("📋 У вас нет подписок")
            await call.answer()
            return
        total_pages = (len(subs) + 9) // 10
        new_page = min(page, total_pages - 1) if total_pages > 0 else 0
        keyboard = kb.subscriptions_keyboard(subs, new_page)
        await call.message.edit_text(
            f"📋 <b>Ваши подписки</b> ({len(subs)}):",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await call.answer()
    except Exception as e:
        logging.error(f"back_to_subs_callback: {e}")
        await call.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("show_versions_subs:"))
async def show_versions_subs_callback(call: types.CallbackQuery):
    """Список версий из подписок (без query)"""
    try:
        _, mod_id, page = call.data.split(":", 2)
        page = int(page)
        loading = await call.message.edit_text("📦 Загрузка списка версий...", parse_mode="HTML")
        versions = await db.get_mod_versions(mod_id)
        if not versions:
            await loading.edit_text("❌ Нет версий")
            return
        # Используем ту же клавиатуру, но с пустым query
        keyboard = kb.versions_list_keyboard(mod_id, versions, "", page, 0)
        await loading.edit_text(
            f"📦 <b>Выберите версию</b>\n\nВсего версий: {len(versions)}",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        await call.answer()
    except Exception as e:
        logging.error(f"show_versions_subs_callback: {e}")
        await call.answer("Ошибка", show_alert=True)

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ВЕРСИЙ ====================

async def _update_versions_background(mod_id: str):
    """Фоновое обновление версий (не чаще раза в сутки)"""
    try:
        pool = db.get_pool()
        if pool is None:
            return
        async with pool.acquire() as conn:
            updated = await conn.fetchval("SELECT versions_updated_at FROM mods WHERE id = $1", mod_id)
        need = False
        if not updated:
            need = True
        else:
            if hasattr(updated, 'tzinfo') and updated.tzinfo is not None:
                updated = updated.replace(tzinfo=None)
            if (datetime.now() - updated).total_seconds() > 86400:
                need = True
        if not need:
            return
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"https://api.modrinth.com/v2/project/{mod_id}/version") as resp:
                if resp.status != 200:
                    return
                api_versions = await resp.json()
        async with pool.acquire() as conn:
            existing = await conn.fetch("SELECT id FROM versions WHERE mod_id = $1", mod_id)
            existing_ids = {r['id'] for r in existing}
            new_cnt = 0
            for v in api_versions[:50]:
                if v['id'] in existing_ids:
                    continue
                primary = None
                for f in v.get('files', []):
                    if f.get('primary'):
                        primary = f
                        break
                if not primary and v.get('files'):
                    primary = v['files'][0]
                if not primary:
                    continue
                pub = None
                if v.get('date_published'):
                    dt = v['date_published'].replace('Z', '+00:00')
                    try:
                        pub = datetime.fromisoformat(dt).replace(tzinfo=None)
                    except:
                        pass
                await conn.execute("""
                    INSERT INTO versions (id, mod_id, version_number, loaders, game_versions, download_url, filename, published_at, file_size, sha512_hash, changelog, version_type)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    ON CONFLICT (id) DO NOTHING
                """, v['id'], mod_id, v['version_number'], v.get('loaders', []), v.get('game_versions', []),
                    primary.get('url',''), primary.get('filename',''), pub, primary.get('size',0),
                    primary.get('hashes',{}).get('sha512',''), v.get('changelog',''), v.get('version_type','release'))
                new_cnt += 1
            if new_cnt:
                await conn.execute("UPDATE mods SET versions_updated_at = CURRENT_TIMESTAMP WHERE id = $1", mod_id)
                logging.info(f"Фоновое обновление {mod_id}: +{new_cnt} версий")
    except Exception as e:
        logging.error(f"_update_versions_background {mod_id}: {e}")


# ==================== АДМИН-КОМАНДЫ (кратко) ====================

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    stats = await db.get_mod_stats()
    users = await db.get_users_count()
    await message.answer(
        f"📊 <b>Статистика</b>\n\nМодов: {stats.get('mods_count',0)}\nВерсий: {stats.get('versions_count',0)}\nПользователей: {users}",
        parse_mode="HTML"
    )


@dp.message(Command("check_db"))
async def cmd_check_db(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    pool = db.get_pool()
    if pool is None:
        await message.answer("❌ БД не подключена")
        return
    async with pool.acquire() as conn:
        mods = await conn.fetchval("SELECT COUNT(*) FROM mods")
        vers = await conn.fetchval("SELECT COUNT(*) FROM versions")
        users = await conn.fetchval("SELECT COUNT(*) FROM users")
        subs = await conn.fetchval("SELECT COUNT(*) FROM subscriptions")
    await message.answer(
        f"✅ БД OK\nМоды: {mods}\nВерсии: {vers}\nПользователи: {users}\nПодписки: {subs}",
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
    await message.answer(f"✅ Псевдонимы перезагружены ({len(utils.COMMON_MOD_ALIASES)})")


@dp.message(Command("reset_cache"))
async def cmd_reset_cache(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    cache.clear_cache()
    utils.mod_names_cache.clear()
    await utils.load_mod_names_cache()
    await message.answer("✅ Кэш сброшен")


@dp.message(Command("user_stats"))
async def cmd_user_stats(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    users = await db.get_users_count()
    pool = db.get_pool()
    top = []
    if pool:
        async with pool.acquire() as conn:
            top = await conn.fetch("SELECT m.title, COUNT(s.user_id) as cnt FROM subscriptions s JOIN mods m ON s.mod_id=m.id GROUP BY m.id ORDER BY cnt DESC LIMIT 5")
    text = f"👥 Пользователей: {users}\n\n"
    if top:
        text += "🏆 Топ подписок:\n"
        for i, r in enumerate(top,1):
            text += f"{i}. {r['title']} — {r['cnt']}\n"
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("❌ Укажите текст для рассылки")
        return
    users = await db.get_all_users()
    if not users:
        await message.answer("❌ Нет пользователей")
        return
    await message.answer(f"📨 Начинаю рассылку {len(users)} пользователям...")
    ok = 0
    for uid in users:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            ok += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"✅ Отправлено {ok}/{len(users)}")


@dp.message(Command("check_mod"))
async def cmd_check_mod(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Укажите название мода")
        return
    mod_name = parts[1].strip()
    pool = db.get_pool()
    if not pool:
        await message.answer("❌ БД не готова")
        return
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, title, downloads FROM mods WHERE title ILIKE $1", mod_name)
        if row:
            await message.answer(f"✅ Найден: {row['title']} ({row['id']}), загрузок {row['downloads']}")
        else:
            similar = await conn.fetch("SELECT title, downloads FROM mods WHERE title ILIKE $1 ORDER BY downloads DESC LIMIT 5", f'%{mod_name}%')
            if similar:
                resp = "❌ Точного совпадения нет. Похожие:\n" + "\n".join(f"• {r['title']} ({r['downloads']})" for r in similar)
                await message.answer(resp)
            else:
                await message.answer("❌ Мод не найден")


@dp.message(Command("help_admin"))
async def cmd_help_admin(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("❌ Нет прав")
        return
    await message.answer(
        "⚙️ <b>Админ-команды</b>\n/stats\n/check_db\n/reload_cache\n/reload_aliases\n/reset_cache\n/user_stats\n/broadcast\n/check_mod\n/help_admin",
        parse_mode="HTML"
    )


# ==================== ЗАГЛУШКИ ====================

@dp.callback_query(F.data == "noop")
async def noop_callback(call: types.CallbackQuery):
    await call.answer()


@dp.callback_query(F.data == "main_menu")
async def main_menu_callback(call: types.CallbackQuery):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📋 Мои подписки", callback_data="mysubs_menu")],
        [types.InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help_menu")]
    ])
    await call.message.edit_text("👋 <b>Главное меню</b>\n\nВыберите действие:", parse_mode="HTML", reply_markup=keyboard)
    await call.answer()


@dp.callback_query(F.data == "mysubs_menu")
async def mysubs_menu_callback(call: types.CallbackQuery):
    subs = await db.get_user_subscriptions(call.from_user.id)
    if not subs:
        await call.message.edit_text("📋 У вас нет подписок")
        return
    keyboard = kb.subscriptions_keyboard(subs, 0)
    await call.message.edit_text(f"📋 <b>Ваши подписки</b> ({len(subs)}):", parse_mode="HTML", reply_markup=keyboard)
    await call.answer()


@dp.callback_query(F.data == "help_menu")
async def help_menu_callback(call: types.CallbackQuery):
    await cmd_help(call.message)
    await call.answer()


# ==================== СКАЧИВАНИЕ ====================

@dp.callback_query(F.data.startswith("download_latest:"))
async def download_latest_callback(call: types.CallbackQuery):
    try:
        await call.answer("⏳ Начинаю скачивание...", show_alert=False)
        _, mod_id = call.data.split(":", 1)
        versions = await db.get_mod_versions(mod_id)
        if not versions:
            await call.message.answer("❌ Нет версий")
            return
        v = versions[0]
        url = v['download_url']
        fname = v['filename'] or f"{mod_id}.jar"
        fsize = v.get('file_size', 0)
        if fsize > 50 * 1024 * 1024:
            async with db.get_pool().acquire() as conn:
                slug = await conn.fetchval("SELECT slug FROM mods WHERE id = $1", mod_id)
            kb_m = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🌐 Скачать с Modrinth", url=f"https://modrinth.com/mod/{slug}/version/{v['id']}")]
            ])
            await call.message.answer(
                f"⚠️ Файл превышает 50 МБ. Скачайте напрямую с Modrinth:",
                reply_markup=kb_m
            )
            return
        msg = await call.message.answer(f"📥 Скачиваю {fname}...")
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url) as resp:
                if resp.status != 200:
                    await msg.edit_text("❌ Ошибка скачивания")
                    return
                data = await resp.read()
        await msg.delete()
        await call.message.answer_document(BufferedInputFile(data, filename=fname), caption=f"✅ {fname}")
    except Exception as e:
        logging.error(f"download_latest: {e}")
        await call.message.answer("❌ Ошибка")


@dp.callback_query(F.data.startswith("download_version:"))
async def download_version_callback(call: types.CallbackQuery):
    try:
        await call.answer("⏳ Начинаю скачивание...", show_alert=False)
        _, ver_id = call.data.split(":", 1)
        pool = db.get_pool()
        async with pool.acquire() as conn:
            v = await conn.fetchrow("SELECT download_url, filename, file_size, mod_id FROM versions WHERE id = $1", ver_id)
            if not v:
                await call.message.answer("❌ Версия не найдена")
                return
            mod_id = v['mod_id']
            slug = await conn.fetchval("SELECT slug FROM mods WHERE id = $1", mod_id)
        url = v['download_url']
        fname = v['filename'] or f"{ver_id}.jar"
        fsize = v['file_size'] or 0
        if fsize > 50 * 1024 * 1024:
            kb_m = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🌐 Скачать с Modrinth", url=f"https://modrinth.com/mod/{slug}/version/{ver_id}")]
            ])
            await call.message.answer(
                f"⚠️ Файл превышает 50 МБ. Скачайте напрямую с Modrinth:",
                reply_markup=kb_m
            )
            return
        msg = await call.message.answer(f"📥 Скачиваю {fname}...")
        async with aiohttp.ClientSession() as sess:
            async with sess.get(url) as resp:
                if resp.status != 200:
                    await msg.edit_text("❌ Ошибка скачивания")
                    return
                data = await resp.read()
        await msg.delete()
        await call.message.answer_document(BufferedInputFile(data, filename=fname), caption=f"✅ {fname}")
    except Exception as e:
        logging.error(f"download_version: {e}")
        await call.message.answer("❌ Ошибка")

@dp.callback_query()
async def debug_unhandled_callback(call: types.CallbackQuery):
    logging.warning(f"⚠️ НЕОБРАБОТАННЫЙ CALLBACK: {call.data}")
    await call.answer("Кнопка временно недоступна", show_alert=True)

# ==================== ЗАПУСК ====================

async def main():
    global BOT_ID
    if not config.validate_config():
        return
    logging.info("🚀 ЗАПУСК БОТА")
    bot_info = await bot.get_me()
    BOT_ID = bot_info.id
    logging.info(f"✅ Бот: @{bot_info.username}")
    await db.init_database()
    cache.init_redis()
    utils.load_mod_aliases()
    await utils.load_mod_names_cache()
    # Фоновая задача проверки обновлений (если есть)
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