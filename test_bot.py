import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "8350627631:AAGaR58sLoPIYI5O8CHhYjxagrXPQpg9KuM"  # Вставьте ваш токен

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    logging.info("🔥 КОМАНДА /start ВЫЗВАНА!")
    await message.answer("✅ /start работает!")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    logging.info("🔥 КОМАНДА /stats ВЫЗВАНА!")
    await message.answer("✅ /stats работает!")

@dp.message()
async def echo(message: Message):
    logging.info(f"Сообщение: {message.text}")
    await message.answer(f"Вы написали: {message.text}")

async def main():
    logging.info("🚀 Тестовый бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())