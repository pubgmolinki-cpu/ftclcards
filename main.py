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

def get_random_card(rarity=None):
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    if rarity:
        search_rarity = rarity.lower()
    else:
        rand = random.randint(1, 100)
        if rand <= 70: search_rarity = "bronze"
        elif rand <= 95: search_rarity = "gold"
        else: search_rarity = "brilliant"
    
    card = cursor.execute(
        "SELECT * FROM all_cards WHERE LOWER(TRIM(rarity_type)) = ? ORDER BY RANDOM() LIMIT 1", 
        (search_rarity,)
    ).fetchone()
    conn.close()
    return card

# --- АДМИН-ФУНКЦИИ ---

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
        await message.answer(f"✅ Игрок {name} ({rar}) добавлен!")
    except:
        await message.answer("Формат: <code>/add_player Имя, Рейтинг, Звезды, Клуб, file_id</code>")

# Хендлер для получения ID (реагирует только на твои сообщения)
@dp.message(F.photo)
async def get_photo_id(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        photo_id = message.photo[-1].file_id
        await message.reply(f"📸 <b>file_id для базы:</b>\n\n<code>{photo_id}</code>")

# --- ИГРОВАЯ ЛОГИКА ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    conn = sqlite3.connect("ftcl_cards.db")
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                 (message.from_user.id, message.from_user.username or "Player"))
    conn.commit()
    conn.close()
    await message.answer("⚽️ Добро пожаловать в FTCL!", reply_markup=main_menu())

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
    
    # Лимит 1 минута
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

    # Эффект интриги
    status = await message.answer("📦 Открываем ежедневный пак...")
    await asyncio.sleep(1.5)

    # Запись в базу
    cursor.execute("UPDATE users SET last_open=?, balance=balance+? WHERE user_id=?", 
                   (now.strftime('%Y-%m-%d %H:%M:%S'), card[3], message.from_user.id))
    cursor.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (message.from_user.id, card[0]))
    conn.commit()
    conn.close()
    
    text = (f"<b>🎊 Твоя карта!</b>\n\n👤 {html.escape(card[1])}\n📈 Рейтинг: {card[2]}\n"
            f"🛡 Клуб: {html.escape(card[4])}\n✨ Тип: {card[5].capitalize()}")
    
    try:
        await message.answer_photo(photo=card[6], caption=text)
        await status.delete() # Удаляем статус ТОЛЬКО после успешной отправки
    except Exception as e:
        await message.answer(f"{text}\n\n❌ Ошибка фото: {e}")
        await status.delete()

@dp.callback_query(F.data.startswith("buy_"))
async def buy_pack(cb: types.CallbackQuery):
    rarity = cb.data.split("_")[1]
    prices = {"Bronze": 500, "Gold": 1500, "Brilliant": 5000}
    
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (cb.from_user.id,)).fetchone()
    
    if not u or u[0] < prices[rarity]:
        await cb.answer("Недостаточно звезд!", show_alert=True)
        conn.close()
        return

    card = get_random_card(rarity)
    if not card:
        await cb.answer(f"Игроков {rarity} нет!", show_alert=True)
        conn.close()
        return

    conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (prices[rarity], cb.from_user.id))
    conn.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (cb.from_user.id, card[0]))
    conn.commit()
    conn.close()

    await cb.answer()
    status = await cb.message.answer(f"📦 Покупаем {rarity} пак...")
    await asyncio.sleep(1.5)

    text = (f"🌟 <b>Пак открыт!</b>\n\n👤 {html.escape(card[1])}\n📈 Рейтинг: {card[2]}\n"
            f"🛡 Клуб: {html.escape(card[4])}\n✨ Редкость: {card[5].capitalize()}")

    try:
        await cb.message.answer_photo(photo=card[6], caption=text)
        await status.delete()
    except Exception as e:
        await cb.message.answer(f"{text}\n\n❌ Ошибка фото: {e}")
        await status.delete()

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    c = conn.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=?", (message.from_user.id,)).fetchone()[0]
    conn.close()
    await message.answer(f"👤 <b>@{message.from_user.username}</b>\n💰 Баланс: {u[0]}🌟\n🗂 Коллекция: {c} шт.")

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
