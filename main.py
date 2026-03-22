import asyncio
import psycopg2
from psycopg2.extras import DictCursor
import os
import html
import random
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = 1866813859  # <--- ОБЯЗАТЕЛЬНО ПОСТАВЬ СВОЙ ID

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

temp_photo_buffer = {}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # BIGINT важен для Telegram ID
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id BIGINT PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS all_cards 
                      (id SERIAL PRIMARY KEY, name TEXT, rating INTEGER, 
                       position TEXT, rarity TEXT, rarity_type TEXT, club TEXT, photo_id TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_cards 
                      (user_id BIGINT, card_id INTEGER)''')
    conn.commit()
    cursor.close()
    conn.close()

def get_random_card_logic(rarity_type=None):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    try:
        if rarity_type:
            search = rarity_type.lower().strip()
        else:
            rand = random.randint(1, 100)
            if rand <= 70: search = "bronze"
            elif rand <= 95: search = "gold"
            else: search = "brilliant"
        
        # Поиск с защитой от регистра
        cursor.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = LOWER(%s) ORDER BY RANDOM() LIMIT 1", (search,))
        card = cursor.fetchone()
        
        # Если нужной редкости нет, берем ЛЮБУЮ карту, чтобы не писать "База пуста"
        if not card:
            cursor.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
            card = cursor.fetchone()
        return card
    finally:
        cursor.close()
        conn.close()

# --- ХЕНДЛЕРЫ АДМИНА ---

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        photo = max(message.photo, key=lambda p: p.file_size)
        temp_photo_buffer[message.from_user.id] = photo.file_id
        await message.reply("📸 <b>Фото принято!</b>\nТеперь введи данные игрока:\n<code>/add_player Имя, Рейтинг, Позиция, Клуб</code>")

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    p_id = temp_photo_buffer.get(message.from_user.id)
    if not p_id: return await message.reply("❌ Сначала отправь фото!")

    try:
        data = message.text.replace("/add_player ", "").split(", ")
        name, rating, pos, club = data[0].strip(), int(data[1].strip()), data[2].strip(), data[3].strip()
        
        if rating >= 90: r_type, r_label = "brilliant", "Brilliant 💎"
        elif rating >= 75: r_type, r_label = "gold", "Gold 🥇"
        else: r_type, r_label = "bronze", "Bronze 🥉"
            
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""INSERT INTO all_cards (name, rating, position, rarity, rarity_type, club, photo_id) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s)""", (name, rating, pos, r_label, r_type, club, p_id))
        conn.commit()
        cursor.close()
        conn.close()
        
        await message.answer(f"✅ Игрок <b>{name}</b> сохранен в PostgreSQL!")
        del temp_photo_buffer[message.from_user.id]
    except:
        await message.answer("❌ Ошибка! Формат: <code>Имя, Рейтинг, Позиция, Клуб</code>")

# --- ИГРОВЫЕ ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING", 
                 (message.from_user.id, message.from_user.username or "Player"))
    conn.commit()
    cursor.close()
    conn.close()
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆")
    kb.button(text="Профиль 👤")
    kb.adjust(2)
    await message.answer("⚽️ Бот FTCL на PostgreSQL запущен!", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "Получить Карту 🏆")
async def give_card(message: types.Message):
    card = get_random_card_logic()
    if not card: 
        return await message.answer("⚠️ База пуста. Добавь игроков через /add_player!")

    cap = (f"🎊 <b>Твоя карта!</b>\n\n👤 {html.escape(card['name'])}\n📈 Рейтинг: {card['rating']}\n"
           f"🏃 Позиция: {html.escape(card['position'])}\n🛡 Клуб: {html.escape(card['club'])}\n✨ {card['rarity']}")
    
    try:
        await message.reply_photo(photo=card['photo_id'], caption=cap)
    except Exception as e:
        await message.reply(f"{cap}\n\n❌ Ошибка фото: {e}")

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT balance FROM users WHERE user_id=%s", (message.from_user.id,))
    u = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=%s", (message.from_user.id,))
    c = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    
    balance = u['balance'] if u else 0
    await message.reply(f"👤 <b>Профиль @{message.from_user.username}</b>\n\n💰 Баланс: {balance} 🌟\n🗂 Коллекция: {c} шт.")

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
