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
TOKEN = os.getenv("TOKEN") 
ADMIN_ID = 1866813859 # <--- ЗАМЕНИ НА СВОЙ ID

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

# --- ОБРАБОТЧИКИ МЕНЮ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    conn = sqlite3.connect("ftcl_cards.db")
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                 (message.from_user.id, message.from_user.username or "Player"))
    conn.execute("INSERT OR IGNORE INTO lineup (user_id) VALUES (?)", (message.from_user.id,))
    conn.commit()
    conn.close()
    await message.answer("✅ Бот запущен! Собери состав и вызывай друзей на матч.", reply_markup=main_menu())

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
            await message.answer(f"⏳ Жди еще {rem.seconds // 3600}ч. {(rem.seconds // 60) % 60}мин.")
            return

    card = cursor.execute("SELECT id, name, rating, stars, photo_id, position FROM all_cards ORDER BY RANDOM() LIMIT 1").fetchone()
    if not card:
        await message.answer("⚠️ В базе пусто! Админ должен добавить игроков.")
        return

    cursor.execute("UPDATE users SET last_open=?, balance=balance+? WHERE user_id=?", 
                   (now.strftime('%Y-%m-%d %H:%M:%S'), card[3], message.from_user.id))
    cursor.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (message.from_user.id, card[0]))
    conn.commit()
    conn.close()
    
    cap = f"🎊 Выпал: {card[1]} [{card[2]}]\nПозиция: {card[5]}\nБонус: +{card[3]}🌟"
    if card[4] and card[4] != "None": await message.answer_photo(photo=card[4], caption=cap)
    else: await message.answer(cap)

# --- СИСТЕМА СОСТАВА 4-3-3 ---

@dp.message(F.text == "Стартовый Состав 🏟️")
async def show_lineup(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    row = conn.execute("SELECT * FROM lineup WHERE user_id = ?", (message.from_user.id,)).fetchone()
    if not row:
        conn.execute("INSERT INTO lineup (user_id) VALUES (?)", (message.from_user.id,))
        conn.commit()
        row = [message.from_user.id] + [None]*11

    s = lambda x: "✅" if x else "❌"
    text = (f"🏟 **Твой состав 4-3-3**\n\n"
            f"🧤 ВРТ: {s(row[1])}\n"
            f"🛡 ЗЩ: {s(row[2])}{s(row[3])}{s(row[4])}{s(row[5])}\n"
            f"⚙️ ПЗ: {s(row[6])}{s(row[7])}{s(row[8])}\n"
            f"🔥 НП: {s(row[9])}{s(row[10])}{s(row[11])}")

    kb = InlineKeyboardBuilder()
    for p in ["Вратарь", "Защитник", "Полузащитник", "Нападающий"]:
        kb.button(text=f"Выбрать: {p}", callback_data=f"pick_{p}")
    kb.adjust(2)
    await message.answer(text, reply_markup=kb.as_markup())
    conn.close()

@dp.callback_query(F.data.startswith("pick_"))
async def list_p(cb: types.CallbackQuery):
    pos = cb.data.split("_")[1]
    conn = sqlite3.connect("ftcl_cards.db")
    cards = conn.execute("""SELECT all_cards.id, name, rating FROM user_cards 
                             JOIN all_cards ON user_cards.card_id = all_cards.id 
                             WHERE user_id = ? AND position LIKE ?""", 
                          (cb.from_user.id, f"%{pos}%")).fetchall()
    if not cards:
        await cb.answer(f"Нет игроков на позицию {pos}!", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    for c in cards: kb.button(text=f"{c[1]} ({c[2]})", callback_data=f"set_{pos}_{c[0]}")
    kb.adjust(1)
    await cb.message.edit_text(f"Выбери ({pos}):", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("set_"))
async def save_p(cb: types.CallbackQuery):
    _, pos, c_id = cb.data.split("_")
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    if pos == "Вратарь": cursor.execute("UPDATE lineup SET gk=? WHERE user_id=?", (c_id, cb.from_user.id))
    elif pos == "Защитник":
        l = cursor.execute("SELECT def1,def2,def3,def4 FROM lineup WHERE user_id=?", (cb.from_user.id,)).fetchone()
        slot = "def1" if not l[0] else "def2" if not l[1] else "def3" if not l[2] else "def4"
        cursor.execute(f"UPDATE lineup SET {slot}=? WHERE user_id=?", (c_id, cb.from_user.id))
    elif pos == "Полузащитник":
        l = cursor.execute("SELECT mid1,mid2,mid3 FROM lineup WHERE user_id=?", (cb.from_user.id,)).fetchone()
        slot = "mid1" if not l[0] else "mid2" if not l[1] else "mid3"
        cursor.execute(f"UPDATE lineup SET {slot}=? WHERE user_id=?", (c_id, cb.from_user.id))
    elif pos == "Нападающий":
        l = cursor.execute("SELECT atk1,atk2,atk3 FROM lineup WHERE user_id=?", (cb.from_user.id,)).fetchone()
        slot = "atk1" if not l[0] else "atk2" if not l[1] else "atk3"
        cursor.execute(f"UPDATE lineup SET {slot}=? WHERE user_id=?", (c_id, cb.from_user.id))
    conn.commit()
    conn.close()
    await cb.answer("Добавлено!")
    await show_lineup(cb.message)

# --- ПОИСК СОПЕРНИКА И ПРОФИЛЬ ---

@dp.message(F.text == "Поиск соперника ⚔️")
async def find_op(msg: types.Message, state: FSMContext):
    await msg.answer("Введи @username соперника:")
    await state.set_state(GameStates.waiting_for_opponent)

@dp.message(GameStates.waiting_for_opponent)
async def invite(msg: types.Message, state: FSMContext):
    target = msg.text.replace("@", "")
    conn = sqlite3.connect("ftcl_cards.db")
    op = conn.execute("SELECT user_id FROM users WHERE username = ?", (target,)).fetchone()
    if not op:
        await msg.answer("Юзер не найден.")
    else:
        kb = InlineKeyboardBuilder()
        kb.button(text="Принять ✅", callback_data=f"match_{msg.from_user.id}")
        await bot.send_message(op[0], f"⚡️ Вызов от @{msg.from_user.username}!", reply_markup=kb.as_markup())
        await msg.answer("Вызов отправлен!")
    await state.clear()
    conn.close()

@dp.message(F.text == "Профиль 👤")
async def prof(msg: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance, wins FROM users WHERE user_id=?", (msg.from_user.id,)).fetchone()
    c = conn.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=?", (msg.from_user.id,)).fetchone()[0]
    await msg.answer(f"👤 @{msg.from_user.username}\n💰 Баланс: {u[0]}🌟\n🏆 Побед: {u[1]}\n🗂 Карт: {c}")

@dp.message(F.text == "Магазин 🛒")
async def shop(msg: types.Message): await msg.answer("🛒 Магазин: Паки появятся скоро!")

@dp.message(F.text == "Мини-Игры 🎲")
async def games(msg: types.Message): await msg.answer("🎲 Игры в разработке!")

@dp.message(Command("add_player"))
async def add(msg: types.Message):
    if msg.from_user.id != ADMIN_ID: return
    try:
        d = msg.text.split(", ")
        conn = sqlite3.connect("ftcl_cards.db")
        conn.execute("INSERT INTO all_cards (name, rating, stars, position, photo_id) VALUES (?, ?, ?, ?, ?)", 
                     (d[1], int(d[2]), int(d[3]), d[4], d[5]))
        conn.commit()
        await msg.answer("✅ Добавлен!")
    except: await msg.answer("Формат: /add_player, Имя, Рейтинг, Звезды, Позиция, photo_id")

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
