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
ADMIN_ID = 1866813859  # <--- ЗАМЕНИ НА СВОЙ ID

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

temp_photo_buffer = {}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
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
    if rating >= 90: return 2500
    if rating >= 85: return 2000
    if rating >= 80: return 1750
    if rating >= 75: return 1500
    if rating >= 70: return 1250
    if rating >= 60: return 1000
    if rating >= 55: return 500
    return 250

def get_card(rarity_filter=None):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    if rarity_filter:
        cursor.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = LOWER(%s) ORDER BY RANDOM() LIMIT 1", (rarity_filter,))
    else:
        rand = random.randint(1, 100)
        search = "bronze" if rand <= 70 else "gold" if rand <= 95 else "brilliant"
        cursor.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = LOWER(%s) ORDER BY RANDOM() LIMIT 1", (search,))
    
    card = cursor.fetchone()
    if not card: 
        cursor.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
        card = cursor.fetchone()
    cursor.close()
    conn.close()
    return card

async def process_card_drop(message, card, is_buy=False, cost=0):
    reward = get_stars_by_rating(card['rating'])
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Обновляем имя пользователя в базе при каждом действии (на случай смены ника)
    cursor.execute("UPDATE users SET username = %s WHERE user_id = %s", (message.from_user.username or "Игрок", message.from_user.id))
    
    if is_buy:
        cursor.execute("UPDATE users SET balance = balance - %s + %s WHERE user_id = %s", (cost, reward, message.from_user.id))
    else:
        cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, message.from_user.id))
    
    cursor.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (message.from_user.id, card['id']))
    conn.commit()
    cursor.close()
    conn.close()

    cap = (f"🎊 <b>{'Покупка' if is_buy else 'Выпала карта'}!</b>\n\n👤 {html.escape(card['name'])}\n📈 Рейтинг: {card['rating']}\n"
           f"🛡 Клуб: {html.escape(card['club'])}\n✨ {card['rarity']}\n\n"
           f"💰 Награда: <b>+{reward}</b> ⭐")
    try:
        await message.reply_photo(photo=card['photo_id'], caption=cap)
    except:
        await message.reply(f"{cap}\n\n❌ Ошибка фото")

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", 
                 (message.from_user.id, message.from_user.username or "Игрок"))
    conn.commit()
    cursor.close()
    conn.close()
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆")
    kb.button(text="Магазин 🛒")
    kb.button(text="Профиль 👤")
    kb.button(text="ТОП-10 📊")
    kb.adjust(2, 2)
    await message.answer("⚽️ FTCL Cards готов к игре!", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message((F.text == "Получить Карту 🏆") | (F.text.casefold() == "фтклкарта"))
async def give_card_free(message: types.Message):
    card = get_card()
    if not card: return await message.answer("⚠️ Игроков в базе нет.")
    await process_card_drop(message, card)

@dp.message(F.text == "Магазин 🛒")
async def open_shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Bronze Pack (500⭐)", callback_data="buy_bronze")
    kb.button(text="📦 Gold Pack (2500⭐)", callback_data="buy_gold")
    kb.button(text="📦 Brilliant Pack (5000⭐)", callback_data="buy_brilliant")
    kb.adjust(1)
    await message.answer("🛒 <b>Магазин паков</b>\nВыберите пак:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy_pack(callback: types.CallbackQuery):
    pack_type = callback.data.split("_")[1]
    costs = {"bronze": 500, "gold": 2500, "brilliant": 5000}
    cost = costs[pack_type]

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT balance FROM users WHERE user_id = %s", (callback.from_user.id,))
    res = cursor.fetchone()
    
    if not res or res['balance'] < cost:
        await callback.answer("❌ Недостаточно звезд!", show_alert=True)
        return

    card = get_card(pack_type)
    await process_card_drop(callback.message, card, is_buy=True, cost=cost)
    await callback.answer(f"Куплен {pack_type} пак!")

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT balance FROM users WHERE user_id=%s", (message.from_user.id,))
    u = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=%s", (message.from_user.id,))
    c_count = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    
    bal = u['balance'] if u else 0
    await message.reply(f"👤 <b>Профиль @{message.from_user.username}</b>\n\n💰 Баланс: <b>{bal}</b> ⭐\n🗂 В коллекции: <b>{c_count}</b> шт.")

@dp.message(F.text == "ТОП-10 📊")
async def show_top(message: types.Message):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    # Выбираем ТОП-10 игроков по балансу
    cursor.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    top_users = cursor.fetchall()
    cursor.close()
    conn.close()

    if not top_users:
        return await message.answer("📊 Список лидеров пока пуст.")

    text = "📊 <b>ТОП-10 Игроков по звёздам:</b>\n\n"
    for i, user in enumerate(top_users, 1):
        username = html.escape(user['username']) if user['username'] else "Игрок"
        # Эмодзи для первых трех мест
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} <b>{username}</b> — {user['balance']} ⭐\n"

    await message.answer(text)

# --- АДМИН ПАНЕЛЬ ---
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        photo = max(message.photo, key=lambda p: p.file_size)
        temp_photo_buffer[message.from_user.id] = photo.file_id
        await message.reply("📸 Фото принято. Жду /add_player")

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    p_id = temp_photo_buffer.get(message.from_user.id)
    if not p_id: return await message.reply("❌ Отправь фото!")
    try:
        data = message.text.replace("/add_player ", "").split(", ")
        name, rating, pos, club = data[0].strip(), int(data[1].strip()), data[2].strip(), data[3].strip()
        r_type = "brilliant" if rating >= 90 else "gold" if rating >= 75 else "bronze"
        r_label = "Brilliant 💎" if r_type == "brilliant" else "Gold 🥇" if r_type == "gold" else "Bronze 🥉"
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO all_cards (name, rating, position, rarity, rarity_type, club, photo_id) VALUES (%s,%s,%s,%s,%s,%s,%s)", (name, rating, pos, r_label, r_type, club, p_id))
        conn.commit(); cur.close(); conn.close()
        await message.answer(f"✅ Добавлен: {name}")
        del temp_photo_buffer[message.from_user.id]
    except: await message.answer("❌ Ошибка формата")

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
