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
ADMIN_ID = 1866813859 # Твой ID

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='Markdown'))
dp = Dispatcher()

# --- ФУНКЦИЯ КОНВЕРТАЦИИ ---
def get_rarity_by_rating(rating):
    if 50 <= rating <= 74:
        return "Bronze"
    elif 75 <= rating <= 89:
        return "Gold"
    elif rating >= 90:
        return "Brilliant"
    return "Bronze" # По умолчанию

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000, last_open TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS all_cards 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rating INTEGER, 
                       stars INTEGER, club TEXT, rarity_type TEXT, photo_id TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_cards (user_id INTEGER, card_id INTEGER)''')
    conn.commit()
    conn.close()

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    builder.button(text="Профиль 👤")
    builder.button(text="Магазин 🛒")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- ЛОГИКА ВЫБОРА КАРТЫ ПО ШАНСАМ ---
def get_random_card(rarity=None):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    
    if not rarity:
        rand = random.randint(1, 100)
        if rand <= 75: rarity = "Bronze"
        elif rand <= 95: rarity = "Gold"
        else: rarity = "Brilliant"
    
    card = cursor.execute("SELECT * FROM all_cards WHERE rarity_type = ? ORDER BY RANDOM() LIMIT 1", (rarity,)).fetchone()
    conn.close()
    return card

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    conn = sqlite3.connect("ftcl_cards.db")
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                 (message.from_user.id, message.from_user.username or "Player"))
    conn.commit()
    conn.close()
    await message.answer("⚽️ Система конвертации рейтинга активирована!", reply_markup=main_menu())

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
            await message.answer(f"⏳ Карта будет доступна через {rem.seconds // 3600}ч.")
            return

    card = get_random_card()
    if not card:
        await message.answer("⚠️ В базе нет игроков! Попроси админа добавить их.")
        return

    cursor.execute("UPDATE users SET last_open=?, balance=balance+? WHERE user_id=?", 
                   (now.strftime('%Y-%m-%d %H:%M:%S'), card[3], message.from_user.id))
    cursor.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (message.from_user.id, card[0]))
    conn.commit()
    conn.close()
    
    emoji = {"Bronze": "🥉", "Gold": "🥇", "Brilliant": "💎"}
    text = (f"🎊 **Новая карта!**\n\n"
            f"👤 Имя: {card[1]}\n"
            f"📈 Рейтинг: {card[2]}\n"
            f"🛡 Клуб: {card[4]}\n"
            f"✨ Тип: {card[5]} {emoji.get(card[5], '')}\n"
            f"💰 Бонус: +{card[3]} 🌟")
            
    if card[6] and card[6] != "None": await message.answer_photo(photo=card[6], caption=text)
    else: await message.answer(text)

@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Bronze Pack (500🌟) 🥉", callback_data="buy_Bronze")
    kb.button(text="Gold Pack (1500🌟) 🥇", callback_data="buy_Gold")
    kb.button(text="Brilliant Pack (5000🌟) 💎", callback_data="buy_Brilliant")
    kb.adjust(1)
    await message.answer("🛒 **Магазин FTCL**", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy_pack(cb: types.CallbackQuery):
    rarity = cb.data.split("_")[1]
    prices = {"Bronze": 500, "Gold": 1500, "Brilliant": 5000}
    
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (cb.from_user.id,)).fetchone()
    
    if u[0] < prices[rarity]:
        await cb.answer("Недостаточно звезд!", show_alert=True)
        return

    card = get_random_card(rarity)
    if not card:
        await cb.answer("В базе нет игроков такого типа!", show_alert=True)
        return

    conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (prices[rarity], cb.from_user.id))
    conn.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (cb.from_user.id, card[0]))
    conn.commit()
    conn.close()
    await cb.message.answer(f"📦 Ты выбил {rarity} карту: **{card[1]}**!")
    await cb.answer()

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    c = conn.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=?", (message.from_user.id,)).fetchone()[0]
    conn.close()
    await message.answer(f"👤 **@{message.from_user.username}**\n💰 Баланс: {u[0]}🌟\n🗂 Карт: {c}")

@dp.message(Command("add_player"))
async def add_player(msg: types.Message):
    if msg.from_user.id != ADMIN_ID: return
    try:
        # Формат: Имя, Рейтинг, Звезды, Клуб, file_id
        d = msg.text.replace("/add_player ", "").split(", ")
        name, rating, stars, club, f_id = d[0], int(d[1]), int(d[2]), d[3], d[4]
        
        # АВТО-КОНВЕРТАЦИЯ
        rarity = get_rarity_by_rating(rating)
        
        conn = sqlite3.connect("ftcl_cards.db")
        conn.execute("INSERT INTO all_cards (name, rating, stars, club, rarity_type, photo_id) VALUES (?, ?, ?, ?, ?, ?)", 
                     (name, rating, stars, club, rarity, f_id))
        conn.commit()
        conn.close()
        await msg.answer(f"✅ Добавлен {name}!\nТип: {rarity} (определено по рейту {rating})")
    except:
        await msg.answer("Ошибка! Формат:\n`Имя, Рейтинг, Звезды, Клуб, file_id`")

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
