import asyncio
import random
import datetime
import sqlite3
import os
import html
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("TOKEN") 
ADMIN_ID = 1866813859 # <--- Твой ID (обязательно!)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

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

def get_random_card(rarity=None):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    
    if rarity:
        search_rarity = rarity.lower().strip()
    else:
        rand = random.randint(1, 100)
        if rand <= 70: search_rarity = "bronze"
        elif rand <= 95: search_rarity = "gold"
        else: search_rarity = "brilliant"
    
    # Используем LOWER для надежности поиска
    card = cursor.execute(
        "SELECT * FROM all_cards WHERE LOWER(rarity_type) = ? ORDER BY RANDOM() LIMIT 1", 
        (search_rarity,)
    ).fetchone()
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
    await message.answer("⚽️ Система FTCL исправлена. Магазин и выдача работают!", reply_markup=main_menu())

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    builder.button(text="Профиль 👤")
    builder.button(text="Магазин 🛒")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

@dp.message(F.text == "Получить Карту 🏆")
async def daily_card(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    user = cursor.execute("SELECT last_open FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    now = datetime.datetime.now()
    
    if user and user[0]:
        last = datetime.datetime.strptime(user[0], '%Y-%m-%d %H:%M:%S')
        if now < last + datetime.timedelta(minutes=1):
            rem = (last + datetime.timedelta(minutes=1)) - now
            await message.answer(f"⏳ Подожди {rem.seconds} сек.")
            conn.close()
            return

    card = get_random_card()
    if not card:
        await message.answer("⚠️ Игроков нет в базе!")
        conn.close()
        return

    # Сначала запись в БД
    cursor.execute("UPDATE users SET last_open=?, balance=balance+? WHERE user_id=?", 
                   (now.strftime('%Y-%m-%d %H:%M:%S'), card[3], message.from_user.id))
    cursor.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (message.from_user.id, card[0]))
    conn.commit()
    conn.close()

    text = (f"<b>🎊 Твоя карта!</b>\n\n👤 {html.escape(card[1])}\n📈 Рейтинг: {card[2]}\n"
            f"🛡 Клуб: {html.escape(card[4])}\n✨ Тип: {card[5].capitalize()}")

    try:
        await message.answer_photo(photo=card[6], caption=text)
    except Exception as e:
        await message.answer(f"{text}\n\n❌ Ошибка фото: {e}")

@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Bronze Pack (500🌟)", callback_data="buy_bronze")
    kb.button(text="Gold Pack (1500🌟)", callback_data="buy_gold")
    kb.button(text="Brilliant Pack (5000🌟)", callback_data="buy_brilliant")
    kb.adjust(1)
    await message.answer("🛒 <b>Магазин FTCL</b>\nВыбери пак для покупки:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy_pack(cb: types.CallbackQuery):
    rarity = cb.data.split("_")[1]
    prices = {"bronze": 500, "gold": 1500, "brilliant": 5000}
    price = prices.get(rarity)
    
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (cb.from_user.id,)).fetchone()
    
    if not u or u[0] < price:
        await cb.answer("Недостаточно звезд! ❌", show_alert=True)
        conn.close()
        return

    card = get_random_card(rarity)
    if not card:
        await cb.answer(f"В базе нет карт редкости {rarity}!", show_alert=True)
        conn.close()
        return

    # Списываем баланс и добавляем карту
    conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, cb.from_user.id))
    conn.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (cb.from_user.id, card[0]))
    conn.commit()
    conn.close()

    # Отвечаем на callback сразу, чтобы убрать "часики"
    await cb.answer(f"Покупка {rarity} пака завершена!")
    
    # Удаляем меню магазина, чтобы не нажимали дважды
    await cb.message.delete()

    text = (f"🌟 <b>Пак открыт!</b>\n\n👤 {html.escape(card[1])}\n📈 Рейтинг: {card[2]}\n"
            f"🛡 Клуб: {html.escape(card[4])}\n✨ Редкость: {card[5].capitalize()}")

    try:
        await cb.message.answer_photo(photo=card[6], caption=text)
    except Exception as e:
        await cb.message.answer(f"{text}\n\n❌ Ошибка фото: {e}")

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    c = conn.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=?", (message.from_user.id,)).fetchone()[0]
    conn.close()
    await message.answer(f"👤 <b>@{message.from_user.username}</b>\n💰 Баланс: {u[0] if u else 0}🌟\n🗂 Коллекция: {c} шт.")

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        data = message.text.replace("/add_player ", "").split(", ")
        name, rating, stars, club, f_id = data[0], int(data[1]), int(data[2]), data[3], data[4]
        
        if rating >= 90: rar = "brilliant"
        elif rating >= 75: rar = "gold"
        else: rar = "bronze"
        
        conn = sqlite3.connect("ftcl_cards.db")
        conn.execute("INSERT INTO all_cards (name, rating, stars, club, rarity_type, photo_id) VALUES (?, ?, ?, ?, ?, ?)", 
                     (name, rating, stars, club, rar, f_id))
        conn.commit()
        conn.close()
        await message.answer(f"✅ Добавлен {name} ({rar})")
    except:
        await message.answer("Формат: <code>Имя, Рейтинг, Звезды, Клуб, file_id</code>")

@dp.message(F.photo)
async def get_photo_id(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        photo_id = message.photo[-1].file_id
        await message.reply(f"📸 <b>file_id:</b>\n<code>{photo_id}</code>")

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
