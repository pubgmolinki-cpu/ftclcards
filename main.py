import asyncio
import psycopg2
from psycopg2.extras import DictCursor
import os
import html
import random
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = 1866813859  # <--- ПОСТАВЬ СВОЙ ID

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

temp_photo_buffer = {}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # BIGINT для ID, чтобы не было ошибок
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

def get_stars_by_rating(rating):
    """Логика начисления звезд по твоему списку"""
    if rating >= 90: return 2500
    if rating >= 85: return 2000
    if rating >= 80: return 1750
    if rating >= 75: return 1500
    if rating >= 70: return 1250
    if rating >= 60: return 1000
    if rating >= 55: return 500
    return 250  # Для рейтинга 50 и ниже

def get_random_card_logic():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    try:
        rand = random.randint(1, 100)
        if rand <= 70: search = "bronze"
        elif rand <= 95: search = "gold"
        else: search = "brilliant"
        
        cursor.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = LOWER(%s) ORDER BY RANDOM() LIMIT 1", (search,))
        card = cursor.fetchone()
        
        if not card: # Если нужной редкости нет, берем любого
            cursor.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
            card = cursor.fetchone()
        return card
    finally:
        cursor.close()
        conn.close()

# --- АДМИН-ФУНКЦИИ ---

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        photo = max(message.photo, key=lambda p: p.file_size)
        temp_photo_buffer[message.from_user.id] = photo.file_id
        await message.reply("📸 <b>Фото сохранено!</b>\nВведи: <code>/add_player Имя, Рейтинг, Позиция, Клуб</code>")

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
        
        await message.answer(f"✅ Игрок <b>{name}</b> ({rating}) добавлен!")
        del temp_photo_buffer[message.from_user.id]
    except:
        await message.answer("❌ Ошибка! Формат: <code>Имя, Рейтинг, Позиция, Клуб</code>")

# --- ИГРОВЫЕ ФУНКЦИИ ---

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
    await message.answer("⚽️ Добро пожаловать в FTCL Cards!", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "Получить Карту 🏆")
async def give_card(message: types.Message):
    card = get_random_card_logic()
    if not card: 
        return await message.answer("⚠️ В базе пока нет игроков.")

    # Вычисляем награду
    reward = get_stars_by_rating(card['rating'])
    
    # Сохраняем в базу: начисление звезд + запись в коллекцию
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1. Обновляем баланс
        cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, message.from_user.id))
        # 2. Добавляем карту в коллекцию
        cursor.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (message.from_user.id, card['id']))
        conn.commit()
    except Exception as e:
        print(f"Ошибка сохранения: {e}")
    finally:
        cursor.close()
        conn.close()

    cap = (f"🎊 <b>Твоя карта!</b>\n\n👤 {html.escape(card['name'])}\n📈 Рейтинг: {card['rating']}\n"
           f"🛡 Клуб: {html.escape(card['club'])}\n✨ {card['rarity']}\n\n"
           f"💰 Награда: <b>+{reward}</b> ⭐")
    
    try:
        await message.reply_photo(photo=card['photo_id'], caption=cap)
    except:
        await message.reply(f"{cap}\n\n❌ Ошибка загрузки фото")

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    
    # Получаем данные пользователя
    cursor.execute("SELECT balance FROM users WHERE user_id=%s", (message.from_user.id,))
    u = cursor.fetchone()
    
    # Считаем количество карт в коллекции
    cursor.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=%s", (message.from_user.id,))
    c_count = cursor.fetchone()[0]
    
    cursor.close()
    conn.close()
    
    balance = u['balance'] if u else 0
    await message.reply(f"👤 <b>Профиль @{message.from_user.username}</b>\n\n"
                        f"💰 Баланс: <b>{balance}</b> ⭐\n"
                        f"🗂 В коллекции: <b>{c_count}</b> шт.")

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
