import asyncio
import sqlite3
import os
import html
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("TOKEN") 
ADMIN_ID = 1866813859 # <--- ТВОЙ ID

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Временный буфер для фото
temp_photo_buffer = {}

def init_db():
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000, last_open TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS all_cards 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rating INTEGER, 
                       position TEXT, rarity TEXT, rarity_type TEXT, club TEXT, photo_id TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_cards (user_id INTEGER, card_id INTEGER)''')
    conn.commit()
    conn.close()

def get_random_card(rarity_type=None):
    conn = sqlite3.connect("ftcl_cards.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if rarity_type:
        search = rarity_type.lower().strip()
    else:
        rand = random.randint(1, 100)
        if rand <= 70: search = "bronze"
        elif rand <= 95: search = "gold"
        else: search = "brilliant"
    
    card = cursor.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = ? ORDER BY RANDOM() LIMIT 1", (search,)).fetchone()
    conn.close()
    return card

# --- АДМИН-ЧАСТЬ ---

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        photo = max(message.photo, key=lambda p: p.file_size)
        temp_photo_buffer[message.from_user.id] = photo.file_id
        await message.reply("📸 <b>Фото запомнил!</b>\nТеперь введи данные игрока:\n<code>/add_player Имя, Рейтинг, Позиция, Клуб</code>")

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    photo_id = temp_photo_buffer.get(message.from_user.id)
    if not photo_id: return await message.reply("❌ Сначала отправь фото!")

    try:
        parts = message.text.replace("/add_player ", "").split(", ")
        name, rating, pos, club = parts[0].strip(), int(parts[1].strip()), parts[2].strip(), parts[3].strip()
        
        if rating >= 90: r_type, r_label = "brilliant", "Brilliant 💎"
        elif rating >= 75: r_type, r_label = "gold", "Gold 🥇"
        else: r_type, r_label = "bronze", "Bronze 🥉"
            
        conn = sqlite3.connect("ftcl_cards.db")
        conn.execute("""INSERT INTO all_cards (name, rating, position, rarity, rarity_type, club, photo_id) 
                        VALUES (?, ?, ?, ?, ?, ?, ?)""", (name, rating, pos, r_label, r_type, club, photo_id))
        conn.commit()
        conn.close()
        
        del temp_photo_buffer[message.from_user.id]
        await message.answer(f"✅ Игрок <b>{name}</b> добавлен!")
    except:
        await message.answer("❌ Ошибка! Формат: <code>Имя, Рейтинг, Позиция, Клуб</code>")

# --- ИГРОВАЯ ЧАСТЬ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    conn = sqlite3.connect("ftcl_cards.db")
    conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
                 (message.from_user.id, message.from_user.username or "Player"))
    conn.commit()
    conn.close()
    await message.answer("⚽️ Бот FTCL готов!", reply_markup=main_menu())

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    builder.button(text="Профиль 👤")
    builder.button(text="Магазин 🛒")
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)

@dp.message((F.text == "Получить Карту 🏆") | (F.text.lower() == "фтклкарта"))
async def give_card(message: types.Message):
    card = get_random_card()
    if not card: return await message.answer("⚠️ База пуста.")
    
    text = (f"🎊 <b>Твоя карта!</b>\n\n👤 {html.escape(str(card['name']))}\n📈 Рейтинг: {card['rating']}\n"
            f"🏃 Позиция: {html.escape(str(card['position']))}\n🛡 Клуб: {html.escape(str(card['club']))}\n✨ {card['rarity']}")
    
    try:
        await message.reply_photo(photo=str(card['photo_id']).strip(), caption=text)
    except Exception as e:
        await message.reply(f"{text}\n\n❌ Ошибка: {e}")

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    c = conn.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=?", (message.from_user.id,)).fetchone()[0]
    conn.close()
    
    await message.reply(f"👤 <b>Профиль @{message.from_user.username}</b>\n\n"
                        f"💰 Баланс: {u[0] if u else 0} 🌟\n"
                        f"🗂 В коллекции: {c} шт.")

@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Bronze Pack (500 🌟)", callback_data="buy_bronze")
    kb.button(text="Gold Pack (1500 🌟)", callback_data="buy_gold")
    kb.button(text="Brilliant Pack (5000 🌟)", callback_data="buy_brilliant")
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
        await cb.answer("В базе нет карт такой редкости!", show_alert=True)
        conn.close()
        return

    conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, cb.from_user.id))
    conn.execute("INSERT INTO user_cards (user_id, card_id) VALUES (?, ?)", (cb.from_user.id, card['id']))
    conn.commit()
    conn.close()

    await cb.answer(f"Покупка {rarity} пака завершена!")
    await cb.message.delete()

    text = (f"🌟 <b>Пак открыт!</b>\n\n👤 {html.escape(card['name'])}\n📈 Рейтинг: {card['rating']}\n"
            f"🛡 Клуб: {html.escape(card['club'])}\n✨ Редкость: {card['rarity']}")

    try:
        await cb.message.answer_photo(photo=card['photo_id'], caption=text)
    except Exception as e:
        await cb.message.answer(f"{text}\n\n❌ Ошибка фото: {e}")

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
