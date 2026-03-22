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

# --- НАСТРОЙКИ (ВСТАВЬ СВОЁ ТУТ) ---
TOKEN = os.getenv("TOKEN")  # Токен из переменных Railway
ADMIN_ID = 1866813859        # Твой Telegram ID для админки

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='Markdown'))
dp = Dispatcher()

class GameState(StatesGroup):
    waiting_for_bet = State()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000, last_open TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS all_cards 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rating INTEGER, 
                       stars INTEGER, club TEXT, division TEXT, position TEXT, rarity TEXT, 
                       rarity_type TEXT, photo_id TEXT)''')
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
    builder.button(text="Профиль 👤")
    builder.button(text="Мини-Игры 🎲")
    builder.button(text="Магазин 🛒")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                   (message.from_user.id, message.from_user.username or "Player"))
    cursor.execute("INSERT OR IGNORE INTO lineup (user_id) VALUES (?)", (message.from_user.id,))
    conn.commit()
    conn.close()
    await message.answer("Футбольная империя FTCL запущена! ⚽️", reply_markup=main_menu())

# ЛОГИКА СОСТАВА
@dp.message(F.text == "Стартовый Состав 🏟️")
async def show_lineup(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    row = cursor.execute("SELECT * FROM lineup WHERE user_id = ?", (message.from_user.id,)).fetchone()
    if not row:
        cursor.execute("INSERT INTO lineup (user_id) VALUES (?)", (message.from_user.id,))
        conn.commit()
        row = [message.from_user.id] + [None]*11

    status = lambda val: "✅" if val else "❌"
    text = (f"🏟 **Твой состав 4-3-3**\n\n"
            f"🧤 Вратарь: {status(row[1])}\n"
            f"🛡 Защита: {status(row[2])}{status(row[3])}{status(row[4])}{status(row[5])}\n"
            f"⚙️ Полузащита: {status(row[6])}{status(row[7])}{status(row[8])}\n"
            f"🔥 Атака: {status(row[9])}{status(row[10])}{status(row[11])}")

    kb = InlineKeyboardBuilder()
    for pos in ["Вратарь", "Защитник", "Полузащитник", "Нападающий"]:
        kb.button(text=f"Выбрать: {pos}", callback_data=f"pick_{pos}")
    kb.adjust(2)
    await message.answer(text, reply_markup=kb.as_markup())
    conn.close()

@dp.callback_query(F.data.startswith("pick_"))
async def list_players(callback: types.CallbackQuery):
    pos = callback.data.split("_")[1]
    conn = sqlite3.connect("ftcl_cards.db")
    cards = conn.execute("""SELECT all_cards.id, name, rating FROM user_cards 
                             JOIN all_cards ON user_cards.card_id = all_cards.id 
                             WHERE user_id = ? AND position LIKE ?""", 
                          (callback.from_user.id, f"%{pos}%")).fetchall()
    if not cards:
        await callback.answer(f"Нет игроков на позицию {pos}!", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    for c in cards:
        kb.button(text=f"{c[1]} ({c[2]})", callback_data=f"set_{pos}_{c[0]}")
    kb.adjust(1)
    await callback.message.edit_text(f"Выбери игрока ({pos}):", reply_markup=kb.as_markup())
    conn.close()

@dp.callback_query(F.data.startswith("set_"))
async def save_player(callback: types.CallbackQuery):
    _, pos, c_id = callback.data.split("_")
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    if pos == "Вратарь": cursor.execute("UPDATE lineup SET gk=? WHERE user_id=?", (c_id, callback.from_user.id))
    elif pos == "Защитник":
        l = cursor.execute("SELECT def1,def2,def3,def4 FROM lineup WHERE user_id=?", (callback.from_user.id,)).fetchone()
        slot = "def1" if not l[0] else "def2" if not l[1] else "def3" if not l[2] else "def4"
        cursor.execute(f"UPDATE lineup SET {slot}=? WHERE user_id=?", (c_id, callback.from_user.id))
    elif pos == "Полузащитник":
        l = cursor.execute("SELECT mid1,mid2,mid3 FROM lineup WHERE user_id=?", (callback.from_user.id,)).fetchone()
        slot = "mid1" if not l[0] else "mid2" if not l[1] else "mid3"
        cursor.execute(f"UPDATE lineup SET {slot}=? WHERE user_id=?", (c_id, callback.from_user.id))
    elif pos == "Нападающий":
        l = cursor.execute("SELECT atk1,atk2,atk3 FROM lineup WHERE user_id=?", (callback.from_user.id,)).fetchone()
        slot = "atk1" if not l[0] else "atk2" if not l[1] else "atk3"
        cursor.execute(f"UPDATE lineup SET {slot}=? WHERE user_id=?", (c_id, callback.from_user.id))
    conn.commit()
    conn.close()
    await callback.answer("Игрок в составе!")
    await show_lineup(callback.message)

# ПОЛУЧЕНИЕ КАРТЫ (РАЗ В 2 МИНУТЫ)
@dp.message(F.text == "Получить Карту 🏆")
async def daily_card(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    user = cursor.execute("SELECT last_open FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    now = datetime.datetime.now()
    if user and user[0]:
        last = datetime.datetime.strptime(user[0], '%Y-%m-%d %H:%M:%S')
        if now < last + datetime.timedelta(minutes=2):
            wait = (last + datetime.timedelta(minutes=2)) - now
            await message.answer(f"⏳ Жди {wait.seconds} сек.")
            conn.close()
            return
    card = cursor.execute("SELECT id, name, rating, stars, photo_id, position FROM all_cards ORDER BY RANDOM() LIMIT 1").fetchone()
    if not card:
        await message.answer("База пуста! Используй /add_player")
        conn.close()
        return
    cursor.execute("UPDATE users SET last_open=?, balance=balance+? WHERE user_id=?", (now.strftime('%Y-%m-%d %H:%M:%S'), card[3], message.from_user.id))
    cursor.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (message.from_user.id, card[0]))
    conn.commit()
    conn.close()
    caption = f"🎊 Выпал: {card[1]} [{card[2]}]\nПозиция: {card[5]}\nНаграда: +{card[3]}🌟"
    if card[4] and card[4] != "None": await message.answer_photo(photo=card[4], caption=caption)
    else: await message.answer(caption)

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        d = message.text.replace("/add_player ", "").split(", ")
        conn = sqlite3.connect("ftcl_cards.db")
        conn.execute("INSERT INTO all_cards (name, rating, stars, club, division, position, photo_id) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                     (d[0], int(d[1]), int(d[2]), d[3], d[4], d[5], d[6]))
        conn.commit()
        await message.answer(f"✅ {d[0]} добавлен!")
    except: await message.answer("Формат: Имя, Рейтинг, Звезды, Клуб, Дивизион, Позиция, file_id")

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    c = conn.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=?", (message.from_user.id,)).fetchone()[0]
    await message.answer(f"👤 Профиль: @{message.from_user.username}\n💰 Баланс: {u[0]}🌟\n🗂 Карт: {c}")

async def main():
    init_db()
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
