import asyncio
import random
import datetime
import sqlite3
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("TOKEN") 
ADMIN_ID = 1866813859  # Твой ID для команды /add_player

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='Markdown'))
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    # Таблица юзеров (убрал wins, чтобы не было ошибок)
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000, 
                       last_open TEXT)''')
    # Таблица всех доступных в игре карт
    cursor.execute('''CREATE TABLE IF NOT EXISTS all_cards 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rating INTEGER, 
                       stars INTEGER, position TEXT, photo_id TEXT)''')
    # Таблица карт, которые есть у игроков
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_cards (user_id INTEGER, card_id INTEGER)''')
    conn.commit()
    conn.close()

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    builder.button(text="Профиль 👤")
    builder.button(text="Магазин 🛒")
    builder.button(text="Мини-Игры 🎲")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    conn = sqlite3.connect("ftcl_cards.db")
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                 (message.from_user.id, message.from_user.username or "Player"))
    conn.commit()
    conn.close()
    await message.answer("⚽️ Добро пожаловать в FTCL Cards! Собирай редкие карты и побеждай.", reply_markup=main_menu())

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    c = conn.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=?", (message.from_user.id,)).fetchone()[0]
    conn.close()
    await message.answer(f"👤 **Твой Профиль**\n\n💰 Баланс: {u[0]}🌟\n🗂 Всего карт: {c}")

@dp.message(F.text == "Получить Карту 🏆")
async def daily_card(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    user = cursor.execute("SELECT last_open FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    now = datetime.datetime.now()
    
    if user and user[0]:
        last = datetime.datetime.strptime(user[0], '%Y-%m-%d %H:%M:%S')
        if now < last + datetime.timedelta(hours=24):
            rem = (last + datetime.timedelta(hours=24)) - now
            await message.answer(f"⏳ Карта будет доступна через {rem.seconds // 3600}ч. {(rem.seconds // 60) % 60}м.")
            return

    card = cursor.execute("SELECT id, name, rating, stars, photo_id FROM all_cards ORDER BY RANDOM() LIMIT 1").fetchone()
    if not card:
        await message.answer("⚠️ В базе еще нет игроков.")
        return

    cursor.execute("UPDATE users SET last_open=?, balance=balance+? WHERE user_id=?", 
                   (now.strftime('%Y-%m-%d %H:%M:%S'), card[3], message.from_user.id))
    cursor.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (message.from_user.id, card[0]))
    conn.commit()
    conn.close()
    
    cap = f"🎊 Выпала карта: **{card[1]}** [{card[2]}]\nБонус: +{card[3]}🌟"
    if card[4] and card[4] != "None": await message.answer_photo(photo=card[4], caption=cap)
    else: await message.answer(cap)

# --- МАГАЗИН (РАБОЧИЙ) ---
@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Купить пак (500🌟)", callback_data="buy_pack")
    await message.answer("🛒 В магазине доступен Пак Новичка.\nЦена: 500🌟", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "buy_pack")
async def buy_pack(callback: types.CallbackQuery):
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
    if u[0] < 500:
        await callback.answer("Недостаточно звезд! ❌", show_alert=True)
        return
    
    card = conn.execute("SELECT id, name FROM all_cards ORDER BY RANDOM() LIMIT 1").fetchone()
    if not card:
        await callback.answer("Магазин пуст!", show_alert=True)
        return

    conn.execute("UPDATE users SET balance = balance - 500 WHERE user_id=?", (callback.from_user.id,))
    conn.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (callback.from_user.id, card[0]))
    conn.commit()
    conn.close()
    await callback.message.answer(f"📦 Пак открыт! Твой новый игрок: **{card[1]}**")

# --- МИНИ-ИГРЫ ---
@dp.message(F.text == "Мини-Игры 🎲")
async def games(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Бросить кубик (Ставка 100)", callback_data="play_dice")
    await message.answer("🎲 Испытай удачу! Бросай кубик: если выпадет 4, 5 или 6 — ты удваиваешь ставку.", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "play_dice")
async def play_dice(callback: types.CallbackQuery):
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
    if u[0] < 100:
        await callback.answer("Нужно минимум 100 звезд!", show_alert=True)
        return

    dice = await callback.message.answer_dice("🎲")
    await asyncio.sleep(3) # Ждем анимацию
    
    if dice.dice.value >= 4:
        conn.execute("UPDATE users SET balance = balance + 100 WHERE user_id=?", (callback.from_user.id,))
        await callback.message.answer("🎉 Победа! Ты получил 100🌟")
    else:
        conn.execute("UPDATE users SET balance = balance - 100 WHERE user_id=?", (callback.from_user.id,))
        await callback.message.answer("😢 Проигрыш. Ты потерял 100🌟")
    
    conn.commit()
    conn.close()

# --- АДМИНКА ---
@dp.message(Command("add_player"))
async def add(msg: types.Message):
    if msg.from_user.id != ADMIN_ID: return
    try:
        # Формат: /add_player Имя, Рейтинг, Звезды, Позиция, file_id
        d = msg.text.replace("/add_player ", "").split(", ")
        conn = sqlite3.connect("ftcl_cards.db")
        conn.execute("INSERT INTO all_cards (name, rating, stars, position, photo_id) VALUES (?, ?, ?, ?, ?)", 
                     (d[0], int(d[1]), int(d[2]), d[3], d[4]))
        conn.commit()
        await msg.answer(f"✅ Игрок {d[0]} добавлен!")
    except: await msg.answer("Ошибка! Юзай: Имя, Рейтинг, Звезды, Позиция, file_id")

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
