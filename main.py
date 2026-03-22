import asyncio
import sqlite3
import os
import html
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("TOKEN") 
ADMIN_ID = 1866813859 # <--- ЗАМЕНИ НА СВОЙ ID!

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
    conn.commit()
    conn.close()

# --- АДМИН-ЧАСТЬ ---

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        # Берем самое качественное фото
        photo = max(message.photo, key=lambda p: p.file_size)
        temp_photo_buffer[message.from_user.id] = photo.file_id
        await message.reply("📸 <b>Фото запомнил!</b>\nТеперь введи данные игрока:\n<code>/add_player Имя, Рейтинг, Позиция, Клуб</code>")

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    photo_id = temp_photo_buffer.get(message.from_user.id)
    if not photo_id:
        return await message.reply("❌ Сначала отправь фото!")

    try:
        # Разделяем ввод
        parts = message.text.replace("/add_player ", "").split(", ")
        name = parts[0].strip()
        rating = int(parts[1].strip())
        pos = parts[2].strip()
        club = parts[3].strip()
        
        # Редкость
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
    except Exception as e:
        await message.answer("❌ Ошибка! Формат: <code>Имя, Рейтинг, Позиция, Клуб</code>")

# --- ИГРОВАЯ ЧАСТЬ ---

@dp.message((F.text == "Получить Карту 🏆") | (F.text.lower() == "фтклкарта"))
async def give_card(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    # Настройка, чтобы получать данные в виде словаря (по именам колонок)
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    
    card = cursor.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1").fetchone()
    conn.close()
    
    if not card: 
        return await message.answer("⚠️ База пуста.")

    # Теперь берем данные ПО ИМЕНАМ СТОЛБЦОВ, а не по цифрам!
    c_name = html.escape(str(card["name"]))
    c_rating = card["rating"]
    c_pos = html.escape(str(card["position"]))
    c_club = html.escape(str(card["club"]))
    c_rarity = card["rarity"]
    c_photo = str(card["photo_id"]).strip() # Убираем лишние пробелы

    text = (f"🎊 <b>Твоя карта!</b>\n\n"
            f"👤 {c_name}\n"
            f"📈 Рейтинг: {c_rating}\n"
            f"🏃 Позиция: {c_pos}\n"
            f"🛡 Клуб: {c_club}\n"
            f"✨ {c_rarity}")
    
    try:
        # Отправляем именно по c_photo
        await message.reply_photo(photo=c_photo, caption=text)
    except Exception as e:
        await message.reply(f"{text}\n\n❌ Ошибка Telegram: <code>{e}</code>")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    await message.answer("⚽️ Бот запущен!", reply_markup=builder.as_markup(resize_keyboard=True))

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
