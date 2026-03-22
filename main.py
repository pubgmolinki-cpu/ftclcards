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
ADMIN_ID = 1866813859 # <--- ТВОЙ ID (ОБЯЗАТЕЛЬНО!)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Временная память для фото
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

# --- АДМИН-ФУНКЦИИ ---

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        photo = max(message.photo, key=lambda p: p.file_size)
        temp_photo_buffer[message.from_user.id] = photo.file_id
        await message.reply("📸 <b>Фото сохранено!</b>\nВведи команду:\n<code>/add_player Имя, Рейтинг, Позиция, Клуб</code>")

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    photo_id = temp_photo_buffer.get(message.from_user.id)
    if not photo_id:
        return await message.reply("❌ Сначала скинь фото!")

    try:
        # Парсим: Имя, Рейтинг, Позиция, Клуб
        data = message.text.replace("/add_player ", "").split(", ")
        name, rating, pos, club = data[0].strip(), int(data[1].strip()), data[2].strip(), data[3].strip()
        
        # Определяем редкость
        if rating >= 90: r_type, r_label = "brilliant", "Brilliant 💎"
        elif rating >= 75: r_type, r_label = "gold", "Gold 🥇"
        else: r_type, r_label = "bronze", "Bronze 🥉"
            
        conn = sqlite3.connect("ftcl_cards.db")
        conn.execute("""INSERT INTO all_cards (name, rating, position, rarity, rarity_type, club, photo_id) 
                        VALUES (?, ?, ?, ?, ?, ?, ?)""", (name, rating, pos, r_label, r_type, club, photo_id))
        conn.commit()
        conn.close()
        
        del temp_photo_buffer[message.from_user.id]
        await message.answer(f"✅ Игрок <b>{name}</b> успешно добавлен!")
    except Exception as e:
        await message.answer("❌ Ошибка! Формат: <code>Имя, Рейтинг, Позиция, Клуб</code>")

# --- ИГРОВАЯ ЛОГИКА ---

@dp.message((F.text == "Получить Карту 🏆") | (F.text.lower() == "фтклкарта"))
async def give_card(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    # Берем случайную карту
    card = conn.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1").fetchone()
    conn.close()
    
    if not card: 
        return await message.answer("⚠️ База пуста.")

    # СТРОГОЕ СООТВЕТСТВИЕ ИНДЕКСАМ ТВОЕЙ БАЗЫ:
    # 1:name, 2:rating, 3:position, 4:rarity, 6:club, 7:photo_id
    text = (f"🎊 <b>Твоя карта!</b>\n\n"
            f"👤 {html.escape(str(card[1]))}\n"
            f"📈 Рейтинг: {card[2]}\n"
            f"🏃 Позиция: {html.escape(str(card[3]))}\n"
            f"🛡 Клуб: {html.escape(str(card[6]))}\n"
            f"✨ {card[4]}")
    
    try:
        # Отправляем фото из колонки №7
        await message.reply_photo(photo=card[7], caption=text)
    except Exception as e:
        await message.reply(f"{text}\n\n❌ Ошибка фото: <code>{e}</code>")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    builder.adjust(1)
    await message.answer("⚽️ Бот FTCL запущен!", reply_markup=builder.as_markup(resize_keyboard=True))

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
