import asyncio
import random
import datetime
import sqlite3
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties

# --- НАСТРОЙКИ ---
# Если запускаешь на Railway, добавь переменную TOKEN в разделе Variables!
TOKEN = os.getenv("TOKEN") 
# Твой ID (узнай в @userinfobot)
ADMIN_ID = 1866813859 

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='Markdown'))
dp = Dispatcher()

class GameStates(StatesGroup):
    waiting_for_opponent = State()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000, 
                       last_open TEXT, wins INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS all_cards 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rating INTEGER, 
                       stars INTEGER, club TEXT, division TEXT, position TEXT, photo_id TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_cards (user_id INTEGER, card_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS lineup 
                      (user_id INTEGER PRIMARY KEY, gk INTEGER, def1 INTEGER, def2 INTEGER, def3 INTEGER, def4 INTEGER,
                       mid1 INTEGER, mid2 INTEGER, mid3 INTEGER, atk1 INTEGER, atk2 INTEGER, atk3 INTEGER)''')
    conn.commit()
    conn.close()

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    builder.button(text="Стартовый Состав 🏟️")
    builder.button(text="Поиск соперника ⚔️")
    builder.button(text="Профиль 👤")
    builder.button(text="Мини-Игры 🎲")
    builder.button(text="Магазин 🛒")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- ОСНОВНАЯ ЛОГИКА ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    conn = sqlite3.connect("ftcl_cards.db")
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                 (message.from_user.id, message.from_user.username or "Player"))
    conn.execute("INSERT OR IGNORE INTO lineup (user_id) VALUES (?)", (message.from_user.id,))
    conn.commit()
    conn.close()
    await message.answer("✅ Бот настроен и готов! Собери свой состав и побеждай.", reply_markup=main_menu())

# ПОЛУЧЕНИЕ КАРТЫ (ЗАДЕРЖКА 24 ЧАСА)
@dp.message(F.text == "Получить Карту 🏆")
async def daily_card(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    user = cursor.execute("SELECT last_open FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    now = datetime.datetime.now()
    
    if user and user[0]:
        last = datetime.datetime.strptime(user[0], '%Y-%m-%d %H:%M:%S')
        if now < last + datetime.timedelta(hours=24):
            remaining = (last + datetime.timedelta(hours=24)) - now
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            await message.answer(f"⏳ Следующая карта будет доступна через {hours}ч. {minutes}мин.")
            conn.close()
            return

    card = cursor.execute("SELECT id, name, rating, stars, photo_id, position FROM all_cards ORDER BY RANDOM() LIMIT 1").fetchone()
    if not card:
        await message.answer("⚠️ В базе нет игроков! Попроси админа добавить их.")
        conn.close()
        return

    cursor.execute("UPDATE users SET last_open=?, balance=balance+? WHERE user_id=?", 
                   (now.strftime('%Y-%m-%d %H:%M:%S'), card[3], message.from_user.id))
    cursor.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (message.from_user.id, card[0]))
    conn.commit()
    conn.close()

    caption = f"🎊 Выпал игрок: {card[1]} [{card[2]}]\nПозиция: {card[5]}\nБонус: +{card[3]}🌟"
    if card[4] and card[4] != "None":
        await message.answer_photo(photo=card[4], caption=caption)
    else:
        await message.answer(caption)

# ПРОФИЛЬ (С ПОБЕДАМИ)
@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance, wins FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    c = conn.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=?", (message.from_user.id,)).fetchone()[0]
    conn.close()
    await message.answer(f"👤 **Профиль: @{message.from_user.username}**\n\n"
                         f"💰 Баланс: {u[0]}🌟\n"
                         f"🏆 Побед в матчах: {u[1]}\n"
                         f"🗂 Всего карт: {c}")

# МАГАЗИН И ИГРЫ (ЗАГЛУШКИ)
@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    await message.answer("🛒 Магазин в разработке. Скоро здесь можно будет покупать паки!")

@dp.message(F.text == "Мини-Игры 🎲")
async def games(message: types.Message):
    await message.answer("🎲 Игры (Казино/Кости) появятся в следующем обновлении!")

# --- СИСТЕМА СОСТАВА И МАТЧЕЙ ---
# (Код из предыдущего сообщения для Стартового состава остается таким же)
# Вставь сюда блоки show_lineup, pick_player и save_player из моего прошлого ответа.

async def main():
    init_db()
    print("Бот успешно запущен на Railway!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
