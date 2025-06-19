import os
import logging
import asyncio
import random
import requests
from datetime import datetime, time, timedelta, timezone

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Включаем логирование для отладки (опционально)
logging.basicConfig(level=logging.INFO)

# Получаем токены и ID администратора из переменных окружения
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
OPENWEATHER_TOKEN = os.environ.get('OPENWEATHER_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_ID')  # Телеграм ID администратора (число, в строковом виде)

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Проверяем, является ли пользователь администратором (сравниваем с ADMIN_ID)
    is_admin = False
    if ADMIN_ID:
        try:
            admin_id_int = int(ADMIN_ID)
        except:
            admin_id_int = None
        if admin_id_int and user_id == admin_id_int:
            is_admin = True

    if is_admin:
        # Для администратора – отправляем приветствие с клавиатурой
        keyboard = [
            [KeyboardButton("Обновить прогноз")],
            [KeyboardButton("Статистика")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "Здравствуйте, администратор! Выберите опцию на клавиатуре.",
            reply_markup=reply_markup
        )
        # *Примечание:* Кнопки "Обновить прогноз" и "Статистика" – пример функционала для администратора.
        # Их обработку (например, обновление прогноза для всех или показ статистики) нужно реализовать отдельно.
    else:
        # Для обычного пользователя – приветствие и запрос города (если ещё не задан)
        if context.user_data.get("city"):
            city = context.user_data["city"]
            await update.message.reply_text(
                f"Вы уже подписаны на ежедневный прогноз для города *{city}* в 7:00 утра.",
                parse_mode="Markdown"
            )
        else:
            context.user_data["awaiting_city"] = True
            await update.message.reply_text(
                "Здравствуйте! 👋\nДля получения прогноза погоды отправьте название вашего города."
            )

# Обработчик текстовых сообщений (ожидание ввода города)
async def handle_city_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем, ждём ли от этого пользователя название города
    if context.user_data.get("awaiting_city"):
        city_name = update.message.text.strip()
        # Вызываем OpenWeather API для проверки города и получения текущей погоды (и смещения часового пояса)
        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                requests.get,
                f"https://api.openweathermap.org/data/2.5/weather?q={city_name}&units=metric&lang=ru&appid={OPENWEATHER_TOKEN}"
            )
            data = response.json()
        except Exception as e:
            logging.error(f"Error fetching weather: {e}")
            await update.message.reply_text(
                "Произошла ошибка при запросе погоды. Пожалуйста, попробуйте ещё раз позже."
            )
            return

        # Проверяем ответ API: код 200 означает успех (город найден)
        if data.get("cod") != 200:
            await update.message.reply_text(
                "Не удалось найти погоду для этого города. Проверьте правильность названия и отправьте ещё раз."
            )
            return  # остаёмся в режиме ожидания ввода города

        # Город найден – сохраняем название города и снимаем флаг ожидания
        city_name_ru = data.get("name", city_name)
        context.user_data["city"] = city_name_ru
        context.user_data["awaiting_city"] = False

        # Определяем часовой пояс города по смещению (timezone offset в секундах)
        tz_offset = data.get("timezone", 0)
        user_tz = timezone(timedelta(seconds=tz_offset))

        # Планируем ежедневную задачу на 7:00 по локальному времени пользователя
        job_name = f"daily_weather_{update.effective_user.id}"
        # Удаляем предыдущую задачу для этого пользователя, если была, чтобы не дублировать
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for job in current_jobs:
            job.schedule_removal()
        # Регистрируем новую ежедневную задачу
        context.job_queue.run_daily(
            send_daily_weather,                   # функция обратного вызова
            time=time(7, 0, tzinfo=user_tz),      # время 7:00 в часовом поясе user_tz
            days=(0, 1, 2, 3, 4, 5, 6),           # каждый день недели
            name=job_name,
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id
        )

        # Подтверждаем пользователю успешную подписку
        await update.message.reply_text(
            f"Отлично, *{city_name_ru}* сохранён! 🌆\n"
            f"Теперь я буду отправлять вам прогноз погоды и предсказание каждый день в 7:00 утра.",
            parse_mode="Markdown"
        )
    else:
        # На любой неожиданный текст (когда город не запрашивается) бот отвечает по умолчанию
        await update.message.reply_text(
            "Извините, я не понял сообщение. Воспользуйтесь командой /start для начала работы."
        )

# Функция отправки ежедневного сообщения (исполняется планировщиком в 7:00)
async def send_daily_weather(context: ContextTypes.DEFAULT_TYPE):
    # Получаем необходимые данные из контекста задачи
    chat_id = context.job.chat_id            # ID чата для отправки
    user_city = context.user_data.get("city")  # город пользователя, сохранённый ранее
    if not user_city:
        return  # если город не задан, ничего не делаем

    # Запрашиваем текущую погоду по городу через OpenWeather API
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            requests.get,
            f"https://api.openweathermap.org/data/2.5/weather?q={user_city}&units=metric&lang=ru&appid={OPENWEATHER_TOKEN}"
        )
        weather = response.json()
    except Exception as e:
        logging.error(f"Ошибка при получении погоды для {user_city}: {e}")
        return

    if weather.get("cod") != 200:
        logging.error(f"OpenWeather API вернул ошибку для города {user_city}: {weather.get('message')}")
        return

    # Разбираем нужные данные о погоде
    description = ""
    if weather.get("weather"):
        # Например: "пасмурно", "ясно" и т.д. Делаем с заглавной буквы.
        description = weather["weather"][0]["description"].capitalize()
    temp = weather["main"]["temp"]
    feels_like = weather["main"]["feels_like"]

    # Формируем текст прогноза погоды
    weather_text = (
        f"Погода в городе *{user_city}* сейчас: {description}\n"
        f"Температура: {temp:.1f}°C, ощущается как {feels_like:.1f}°C."
    )
    # Выбираем случайное предсказание из списка
    predictions = [
        "Сегодня удачный день для новых начинаний.",
        "Звёзды обещают спокойный день.",
        "Обратите внимание на мелочи – в них кроется что-то важное.",
        "Улыбайтесь — и удача улыбнётся вам в ответ!",
        "Хороший день, чтобы узнать что-то новое."
    ]
    prediction_text = random.choice(predictions)
    full_message = f"{weather_text}\n\n🔮 *Предсказание дня:* {prediction_text}"

    # Отправляем сообщение пользователю
    try:
        await context.bot.send_message(chat_id=chat_id, text=full_message, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")

def main():
    # Инициализируем приложение Telegram Bot Application
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Регистрируем обработчики команд и сообщений
    application.add_handler(CommandHandler("start", start))
    # (При необходимости можно добавить другие команды, например, /help)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_city_input))

    # Запускаем бота (долгий опрос Telegram API)
    application.run_polling()

if __name__ == "__main__":
    main()
