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
ADMIN_ID = 1866813859 # <--- ОБЯЗАТЕЛЬНО ПОСТАВЬ СВОЙ ID

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("ftcl_cards.db")
    cursor = conn.cursor()
    # Создаем таблицы согласно твоей структуре
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 1000, last_open TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS all_cards 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, rating INTEGER, 
                       position TEXT, rarity TEXT, rarity_type TEXT, club TEXT, photo_id TEXT)''')
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
    
    card = cursor.execute(
        "SELECT * FROM all_cards WHERE LOWER(rarity_type) = ? ORDER BY RANDOM() LIMIT 1", 
        (search_rarity,)
    ).fetchone()
    conn.close()
    return card

# --- АДМИН-КОМАНДЫ ---

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        # Формат: /add_player Имя, Рейтинг, Позиция, Клуб, file_id
        data = message.text.replace("/add_player ", "").split(", ")
        name, rating, pos, club, f_id = data[0].strip(), int(data[1].strip()), data[2].strip(), data[3].strip(), data[4].strip()
        
        # Определяем редкость для колонок rarity и rarity_type
        if rating >= 90:
            r_type, r_label = "brilliant", "Brilliant 💎"
        elif rating >= 75:
            r_type, r_label = "gold", "Gold 🥇"
        else:
            r_type, r_label = "bronze", "Bronze 🥉"
            
        conn = sqlite3.connect("ftcl_cards.db")
        conn.execute("""INSERT INTO all_cards (name, rating, position, rarity, rarity_type, club, photo_id) 
                        VALUES (?, ?, ?, ?, ?, ?, ?)""", (name, rating, pos, r_label, r_type, club, f_id))
        conn.commit()
        conn.close()
        await message.answer(f"✅ Игрок <b>{name}</b> ({pos}) добавлен!")
    except Exception as e:
        await message.answer(f"❌ Ошибка! Используй формат:\n<code>Имя, Рейтинг, Позиция, Клуб, file_id</code>\n\n{e}")

@dp.message(F.photo)
async def get_photo_id(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        # Берем самый большой файл, чтобы получить длинный ID
        photo = max(message.photo, key=lambda p: p.file_size)
        await message.reply(f"📸 <b>file_id для базы:</b>\n\n<code>{photo.file_id}</code>")

# --- ИГРОВАЯ ЛОГИКА ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    await message.answer("⚽️ Бот FTCL готов! Напиши <b>ФтклКарта</b> или используй кнопки.", reply_markup=main_menu())

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    builder.button(text="Профиль 👤")
    builder.button(text="Магазин 🛒")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

@dp.message((F.text == "Получить Карту 🏆") | (F.text.lower() == "фтклкарта"))
async def give_card(message: types.Message):
    card = get_random_card()
    if not card: return await message.answer("⚠️ База пуста.")

    # Экранируем текст, чтобы не было ошибок в Railway
    text = (f"<b>🎊 Твоя карта!</b>\n\n👤 {html.escape(str(card[1]))}\n📈 Рейтинг: {card[2]}\n"
            f"🏃 Позиция: {html.escape(str(card[3]))}\n🛡 Клуб: {html.escape(str(card[6]))}\n✨ {card[4]}")
    
    try:
        await message.reply_photo(photo=card[7], caption=text)
    except Exception as e:
        await message.reply(f"{text}\n\n❌ Ошибка фото: <code>{e}</code>")

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = sqlite3.connect("ftcl_cards.db")
    u = conn.execute("SELECT balance FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
    c = conn.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=?", (message.from_user.id,)).fetchone()[0]
    conn.close()
    await message.reply(f"👤 <b>Профиль</b>\n💰 Баланс: {u[0] if u else 0}🌟\n🗂 Карт: {c}")

@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Bronze (500)", callback_data="buy_bronze")
    kb.button(text="Gold (1500)", callback_data="buy_gold")
    kb.button(text="Brilliant (5000)", callback_data="buy_brilliant")
    kb.adjust(1)
    await message.answer("🛒 Магазин паков:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy(cb: types.CallbackQuery):
    rarity = cb.data.split("_")[1]
    card = get_random_card(rarity)
    if not card: return await cb.answer("Нет таких карт!")
    
    await cb.answer()
    await cb.message.delete()
    try:
        await cb.message.answer_photo(photo=card[7], caption=f"🌟 Куплен пак: {card[1]}")
    except:
        await cb.message.answer(f"🌟 Куплен пак: {card[1]} (Ошибка фото)")

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
