import asyncio
import logging
from aiogram import types

from bot.database import get_pool, get_mod_versions, update_subscription_version

async def check_mod_updates(bot):
    """Фоновая проверка обновлений с кнопками"""
    # Ждём запуска бота
    await asyncio.sleep(30)
    
    while True:
        try:
            pool = get_pool()
            if pool is None:
                await asyncio.sleep(60)
                continue
            
            logging.info("🔍 Проверка обновлений...")
            
            async with pool.acquire() as conn:
                # Получаем все моды с подписками
                mods = await conn.fetch("SELECT DISTINCT mod_id FROM subscriptions")
            
            for row in mods:
                mod_id = row['mod_id']
                
                try:
                    # Получаем информацию о моде
                    async with pool.acquire() as conn:
                        mod = await conn.fetchrow(
                            "SELECT id, title, slug, downloads FROM mods WHERE id = $1", 
                            mod_id
                        )
                    
                    if not mod:
                        continue
                    
                    # Получаем последнюю версию
                    versions = await get_mod_versions(mod_id)
                    if not versions:
                        continue
                    
                    latest_version = versions[0]['version_number']
                    
                    # Получаем сохранённую версию из подписки
                    async with pool.acquire() as conn:
                        old_version = await conn.fetchval(
                            "SELECT last_version FROM subscriptions WHERE mod_id = $1 LIMIT 1",
                            mod_id
                        )
                    
                    # Если есть обновление
                    if old_version and old_version != latest_version:
                        logging.info(f"🔄 Обновление {mod['title']}: {old_version} → {latest_version}")
                        
                        # Обновляем версию в подписках
                        await update_subscription_version(mod_id, latest_version)
                        
                        # Получаем всех подписчиков
                        async with pool.acquire() as conn:
                            subscribers = await conn.fetch(
                                "SELECT user_id FROM subscriptions WHERE mod_id = $1",
                                mod_id
                            )
                        
                        # Создаём клавиатуру с кнопками
                        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
                            [
                                types.InlineKeyboardButton(
                                    text="📦 Открыть в боте",
                                    callback_data=f"mod:{mod['id']}:update:{mod['title']}"
                                ),
                                types.InlineKeyboardButton(
                                    text="🌐 На Modrinth",
                                    url=f"https://modrinth.com/mod/{mod['slug']}"
                                )
                            ]
                        ])
                        
                        # Формируем сообщение
                        message_text = (
                            f"🔄 <b>Обновление мода!</b>\n\n"
                            f"<b>{mod['title']}</b>\n"
                            f"📥 Загрузок: {mod['downloads']:,}\n\n"
                            f"<b>Новая версия:</b> {latest_version}\n"
                            f"<b>Было:</b> {old_version}\n\n"
                            f"⬇️ Нажми на кнопку, чтобы посмотреть мод"
                        )
                        
                        # Отправляем уведомления всем подписчикам
                        for sub in subscribers:
                            try:
                                await bot.send_message(
                                    chat_id=sub['user_id'],
                                    text=message_text,
                                    parse_mode="HTML",
                                    reply_markup=keyboard,
                                    disable_web_page_preview=True
                                )
                                await asyncio.sleep(0.1)  # Защита от флуда
                            except Exception as e:
                                logging.error(f"Не удалось отправить пользователю {sub['user_id']}: {e}")
                
                except Exception as e:
                    logging.error(f"Ошибка при проверке мода {mod_id}: {e}")
                    continue
            
            # Ждём час до следующей проверки
            await asyncio.sleep(3600)
            
        except asyncio.CancelledError:
            logging.info("⏹️ Задача проверки обновлений остановлена")
            break
        except Exception as e:
            logging.error(f"❌ Ошибка в фоновой задаче: {e}")
            await asyncio.sleep(300)