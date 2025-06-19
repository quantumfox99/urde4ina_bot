import os
import asyncio
import random
from datetime import datetime

import pytz
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENWEATHER_TOKEN = os.getenv("OPENWEATHER_TOKEN")  # пока не используется, но оставим

USERS = [
    {"chat_id": 123456789, "name": "Витя", "city": "Warsaw", "timezone": "Europe/Warsaw", "role": "admin"},
    {"chat_id": 987654321, "name": "Женя", "city": "Warsaw", "timezone": "Europe/Warsaw", "role": "user"},
    {"chat_id": 111222333, "name": "Рома", "city": "Rivne", "timezone": "Europe/Kyiv", "role": "user"},
    {"chat_id": 444555666, "name": "Витек", "city": "Kelowna", "timezone": "America/Vancouver", "role": "user"},
    {"chat_id": 777888999, "name": "Никита", "city": "Warsaw", "timezone": "Europe/Warsaw", "role": "user"},
]

PREDICTIONS = [
    "Сегодня тебе улыбнётся удача!",
    "Будь осторожен в пути.",
    "Жди хорошие новости вечером.",
    "Идеальный день, чтобы начать что-то новое!"
]

def get_weather(city: str) -> str:
    # заглушка погоды
    return f"Погода в {city}: +20°C, облачно"

def admin_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🔍 Поиск запчасти"), KeyboardButton("🚗 Выбор модели")],
            [KeyboardButton("🛒 Корзина"), KeyboardButton("🔁 Сброс поиска")],
            [KeyboardButton("🔄 Синхронизировать"), KeyboardButton("📚 Логи запросов")],
            [KeyboardButton("👥 Список пользователей")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = next((u for u in USERS if u["chat_id"] == user_id), None)

    if user:
        text = f"Привет, {user['name']}!"
        reply_markup = admin_keyboard() if user["role"] == "admin" else None
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text("Вы не зарегистрированы.")

async def send_weather(app):
    now_utc = datetime.now(pytz.utc)
    for user in USERS:
        try:
            tz = pytz.timezone(user["timezone"])
            local_time = now_utc.astimezone(tz)
            if local_time.hour == 7 and local_time.minute <= 10:
                text = f"{get_weather(user['city'])}\nПредсказание: {random.choice(PREDICTIONS)}"
                await app.bot.send_message(chat_id=user["chat_id"], text=text)
        except Exception as e:
            print(f"Ошибка для {user['name']}: {e}")

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: asyncio.create_task(send_weather(app)), "interval", minutes=10)
    scheduler.start()

    print("Бот запущен.")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
