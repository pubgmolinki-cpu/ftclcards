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

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("TOKEN")
# Берем URL базы из переменных Railway
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = 1866813859  # <--- ЗАМЕНИ НА СВОЙ ID!

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

temp_photo_buffer = {}

def get_db_connection():
    # Подключение к PostgreSQL
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # В Postgres синтаксис немного отличается (SERIAL вместо AUTOINCREMENT)
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id BIGINT PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000, last_open TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS all_cards 
                      (id SERIAL PRIMARY KEY, name TEXT, rating INTEGER, 
                       position TEXT, rarity TEXT, rarity_type TEXT, club TEXT, photo_id TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_cards (user_id BIGINT, card_id INTEGER)''')
    conn.commit()
    cursor.close()
    conn.close()

def get_random_card_logic(rarity_type=None):
    conn = get_db_connection()
    # DictCursor заменяет sqlite3.Row для доступа по именам
    cursor = conn.cursor(cursor_factory=DictCursor)
    
    if rarity_type:
        search = rarity_type.lower().strip()
    else:
        rand = random.randint(1, 100)
        if rand <= 70: search = "bronze"
        elif rand <= 95: search = "gold"
        else: search = "brilliant"
    
    cursor.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = %s ORDER BY RANDOM() LIMIT 1", (search,))
    card = cursor.fetchone()
    cursor.close()
    conn.close()
    return card

# --- АДМИН-ЧАСТЬ ---

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        photo = max(message.photo, key=lambda p: p.file_size)
        temp_photo_buffer[message.from_user.id] = photo.file_id
        await message.reply("📸 <b>Фото сохранено!</b>\nИспользуй: <code>/add_player Имя, Рейтинг, Позиция, Клуб</code>")

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
            
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""INSERT INTO all_cards (name, rating, position, rarity, rarity_type, club, photo_id) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s)""", (name, rating, pos, r_label, r_type, club, photo_id))
        conn.commit()
        cursor.close()
        conn.close()
        
        del temp_photo_buffer[message.from_user.id]
        await message.answer(f"✅ Игрок <b>{name}</b> добавлен в PostgreSQL!")
    except:
        await message.answer("❌ Ошибка формата!")

# --- ИГРОВАЯ ЧАСТЬ ---

@dp.message(F.text == "Получить Карту 🏆")
async def give_card_handler(message: types.Message):
    card = get_random_card_logic()
    if not card: return await message.answer("⚠️ База пуста.")
    
    text = (f"🎊 <b>Твоя карта!</b>\n\n👤 {html.escape(card['name'])}\n📈 Рейтинг: {card['rating']}\n"
            f"🏃 Позиция: {html.escape(card['position'])}\n🛡 Клуб: {html.escape(card['club'])}\n✨ {card['rarity']}")
    
    try:
        await message.reply_photo(photo=card['photo_id'].strip(), caption=text)
    except Exception as e:
        await message.reply(f"{text}\n\n❌ Ошибка: {e}")

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
    
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    builder.button(text="Профиль 👤")
    builder.adjust(1)
    await message.answer("⚽️ Бот на PostgreSQL запущен успешно!", reply_markup=builder.as_markup(resize_keyboard=True))

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
