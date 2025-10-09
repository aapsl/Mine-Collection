import asyncio
import logging
import sqlite3
from datetime import datetime

from bot.database import get_mod_versions, get_subscriptions_for_mod, update_subscription_version, remove_subscription
from bot.config import DB_PATH

async def check_mod_updates(bot):
    """Фоновая задача для проверки обновлений модов"""
    try:
        while True:
            try:
                logging.info("Начинаем проверку обновлений модов...")
            
                # Получаем все моды с подписками
                with sqlite3.connect(DB_PATH, timeout=30) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT DISTINCT mod_id FROM subscriptions")
                    mods_with_subs = [row[0] for row in cursor.fetchall()]
            
                logging.info(f"Проверяем обновления для {len(mods_with_subs)} модов с подписками")
            
                for mod_id in mods_with_subs:
                    try:
                        # Получаем информацию о моде
                        with sqlite3.connect(DB_PATH, timeout=30) as conn:
                            conn.row_factory = sqlite3.Row
                            cursor = conn.cursor()
                            cursor.execute("SELECT * FROM mods WHERE id = ?", (mod_id,))
                            mod_data = cursor.fetchone()
                    
                        if not mod_data:
                            continue
                    
                        versions = get_mod_versions(mod_id)
                        if not versions:
                            continue
                    
                        latest_version = versions[0]['version_number']
                    
                        # Получаем последнюю известную версию из подписки
                        with sqlite3.connect(DB_PATH, timeout=30) as conn:
                            cursor = conn.cursor()
                            cursor.execute("SELECT last_version FROM subscriptions WHERE mod_id = ? LIMIT 1", (mod_id,))
                            last_known_version_row = cursor.fetchone()
                            last_known_version = last_known_version_row[0] if last_known_version_row else None
                    
                        if latest_version and last_known_version is not None and latest_version != last_known_version:
                            logging.info(f"Обнаружено обновление для мода {mod_data['title']}: {last_known_version} -> {latest_version}")
                        
                            # Обновляем версию в подписках
                            update_subscription_version(mod_id, latest_version)
                            
                            # Получаем всех подписчиков
                            subscribers = get_subscriptions_for_mod(mod_id)
                        
                            for sub in subscribers:
                                try:
                                    user_id = sub['user_id']
                                    message_text = (
                                        f"🔄 <b>Обновление мода!</b>\n\n"
                                        f"Мод <b>{mod_data['title']}</b> обновлен:\n"
                                        f"• Было: {last_known_version or 'Неизвестно'}\n"
                                        f"• Стало: {latest_version}\n\n"
                                        f"<a href=\"https://modrinth.com/mod/{mod_data['slug']}\">Страница мода на Modrinth</a>"
                                    )
                                
                                    await bot.send_message(
                                        chat_id=user_id,
                                        text=message_text,
                                        parse_mode="HTML",
                                        disable_web_page_preview=True
                                    )
                                
                                    await asyncio.sleep(0.1)
                                
                                except Exception as e:
                                    logging.error(f"Ошибка при отправке уведомления пользователю {sub['user_id']}: {e}")
                                    if "bot was blocked" in str(e).lower():
                                        remove_subscription(sub['user_id'], mod_id)
                
                    except Exception as e:
                        logging.error(f"Ошибка при проверке обновлений для мода {mod_id}: {e}")
                        continue
            
                logging.info("Проверка обновлений завершена. Следующая проверка через 1 час.")
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                logging.info("Задача проверки обновлений остановлена по запросу")
                break
            except Exception as e:
                logging.error(f"Ошибка в фоновой задаче проверки обновлений: {e}")
                await asyncio.sleep(300)
    except asyncio.CancelledError:
        logging.info("Задача проверки обновлений полностью остановлена")
    except Exception as e:
        logging.error(f"Неожиданная ошибка в фоновой задаче: {e}")