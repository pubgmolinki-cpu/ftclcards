import asyncio
import random
import datetime
import sqlite3
import os
import html # Используем стандартный модуль для безопасности текста
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("TOKEN") 
ADMIN_ID = 1866813859 # <--- ЗАМЕНИ НА СВОЙ ID

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
    
    card = cursor.execute(
        "SELECT * FROM all_cards WHERE LOWER(rarity_type) = ? ORDER BY RANDOM() LIMIT 1", 
        (search_rarity,)
    ).fetchone()
    conn.close()
    return card

# --- ИСПРАВЛЕННЫЙ ХЕНДЛЕР ВЫДАЧИ ID ---
@dp.message(F.photo)
async def get_photo_id(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        # Сортируем фото по размеру файла, чтобы точно взять оригинал (самый длинный ID)
        biggest_photo = max(message.photo, key=lambda p: p.file_size)
        photo_id = biggest_photo.file_id
        
        await message.reply(
            f"✅ <b>Оригинальный file_id получен!</b>\n\n"
            f"<code>{photo_id}</code>\n\n"
            f"<i>Этот ID намного длиннее предыдущего и должен работать без ошибок.</i>"
        )

# --- ИГРОВАЯ ЛОГИКА ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    init_db()
    await message.answer("⚽️ Бот активен! Используй кнопки или пиши <b>ФтклКарта</b>.", reply_markup=main_menu())

def main_menu():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Получить Карту 🏆")
    builder.button(text="Профиль 👤")
    builder.button(text="Магазин 🛒")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

@dp.message((F.text == "Получить Карту 🏆") | (F.text.lower() == "фтклкарта"))
async def handle_card_request(message: types.Message):
    card = get_random_card()
    if not card:
        return await message.reply("⚠️ База пуста.")

    # Экранируем текст для защиты от ошибок парсинга
    name = html.escape(str(card[1]))
    rating = card[2]
    club = html.escape(str(card[4]))
    rarity = card[5].capitalize()

    text = (f"🎊 <b>Твоя карта!</b>\n\n"
            f"👤 {name}\n📈 Рейтинг: {rating}\n"
            f"🛡 Клуб: {club}\n✨ Редкость: {rarity}")

    try:
        await message.reply_photo(photo=card[6], caption=text)
    except Exception as e:
        await message.reply(f"{text}\n\n❌ <b>Ошибка фото:</b> <code>{e}</code>")

@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Bronze Pack", callback_data="buy_bronze")
    kb.button(text="Gold Pack", callback_data="buy_gold")
    kb.button(text="Brilliant Pack", callback_data="buy_brilliant")
    kb.adjust(1)
    await message.answer("🛒 Магазин", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy_pack(cb: types.CallbackQuery):
    rarity = cb.data.split("_")[1]
    card = get_random_card(rarity)
    if not card:
        return await cb.answer("Нет таких карт!")

    await cb.answer()
    text = f"🌟 Куплен пак: {html.escape(card[1])}"
    try:
        await cb.message.answer_photo(photo=card[6], caption=text)
    except Exception as e:
        await cb.message.answer(f"{text}\n\n Ошибка: {e}")

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
