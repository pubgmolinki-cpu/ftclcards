import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Импортируем твои функции (создадим их в других файлах)
# from database import session, Match, User
# from ai_logic import calculate_odds

# Настройки
API_TOKEN = 'ТВОЙ_ТОКЕН_БОТА'
ADMIN_ID = 12345678  # Твой ID, чтобы только ты мог добавлять матчи
WEB_APP_URL = 'https://твой-сайт-с-дизайном.com' 

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- ЛОГИКА ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ---

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    # Создаем кнопку Web App
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="Играть ⚽️", 
        web_app=WebAppInfo(url=WEB_APP_URL)
    ))

    await message.answer(
        f"<b>TonBoxBet</b>\n\n"
        f"Приветствуем тебя в нашем боте, где ты можешь ставить ставки на матчи ФТКЛ "
        f"и выигрывать TonBox Coins.",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )

# --- ЛОГИКА ДЛЯ АДМИНА (ЗАПОЛНЕНИЕ МАТЧЕЙ) ---

@dp.message(F.text.startswith("Добавить матч"), F.from_user.id == ADMIN_ID)
async def add_match_ai(message: types.Message):
    # Пример формата: "Добавить матч: Команда1 (Рейтинги) vs Команда2 (Рейтинги)"
    await message.answer("Отправляю составы ИИ-помощнику для расчета коэффициентов...⏳")
    
    try:
        # 1. Вызываем функцию из ai_logic.py
        # data = calculate_odds(составы_из_текста)
        
        # 2. Сохраняем в БД (database.py)
        # new_match = Match(team1=..., k_p1=data['k1'], ...)
        # session.add(new_match)
        # session.commit()
        
        await message.answer("✅ Матч успешно добавлен в Web App!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# Запуск бота
if __name__ == "__main__":
    dp.run_polling(bot)
