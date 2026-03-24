import asyncio, psycopg2, os, html, random, time
from psycopg2.extras import DictCursor
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = 1866813859  # <--- ЗАМЕНИ НА СВОЙ ID

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()
cooldowns = {} # Временное хранилище КД (сбросится при перезагрузке сервера)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# --- ЛОГИКА НАГРАД ---
def get_stars_by_rating(rating):
    rates = {90: 2500, 85: 2000, 80: 1750, 75: 1500, 70: 1250, 60: 1000, 55: 500}
    for r, val in rates.items():
        if rating >= r: return val
    return 250

def get_card(rarity_filter=None):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    if rarity_filter:
        cur.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = %s ORDER BY RANDOM() LIMIT 1", (rarity_filter.lower(),))
    else:
        r = random.randint(1, 100)
        rtype = "bronze" if r <= 70 else "gold" if r <= 95 else "brilliant"
        cur.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = %s ORDER BY RANDOM() LIMIT 1", (rtype,))
    card = cur.fetchone()
    if not card:
        cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
        card = cur.fetchone()
    cur.close(); conn.close()
    return card

# --- ОСНОВНЫЕ ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    referrer_id = command.args
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    is_new = cur.fetchone() is None
    
    # Регистрация
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", 
                 (user_id, message.from_user.username or "Игрок"))
    
    # Начисление за реферала
    if is_new and referrer_id and referrer_id.isdigit() and int(referrer_id) != user_id:
        ref_id = int(referrer_id)
        cur.execute("UPDATE users SET balance = balance + 5000 WHERE user_id = %s", (ref_id,))
        try:
            await bot.send_message(ref_id, f"🎁 У вас новый реферал! Зачислено <b>5000 ⭐</b>")
        except: pass

    conn.commit(); cur.close(); conn.close()
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆")
    kb.button(text="Магазин 🛒")
    kb.button(text="Профиль 👤")
    kb.button(text="Реферальная Система 👥")
    kb.button(text="ТОП-10 📊")
    kb.adjust(2, 2, 1)
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>\nСобирай карточки, открывай паки и стань лучшим в ТОПе!", 
                         reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "Реферальная Система 👥")
async def ref_system(message: types.Message):
    user_id = message.from_user.id
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
    
    text = (f"👥 <b>Реферальная Система</b>\n\n"
            f"Приглашай друзей и получай <b>5000 ⭐</b> за каждого нового игрока!\n\n"
            f"Вот ваша реферальная ссылка:\n<code>{ref_link}</code> ⚽")
    await message.answer(text)

@dp.message((F.text == "Получить Карту 🏆") | (F.text.casefold() == "фтклкарта"))
async def give_card_free(message: types.Message):
    user_id = message.from_user.id
    now = time.time()
    
    # КД 12 часов (43200 секунд)
    if user_id in cooldowns and now - cooldowns[user_id] < 43200:
        rem_sec = int(43200 - (now - cooldowns[user_id]))
        hours = rem_sec // 3600
        minutes = (rem_sec % 3600) // 60
        return await message.reply(f"⏳ Следующая бесплатная карта через <b>{hours}ч. {minutes}мин.</b>")
    
    card = get_card()
    if not card: return await message.reply("⚠️ В базе еще нет игроков.")
    
    reward = get_stars_by_rating(card['rating'])
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, user_id))
    cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (user_id, card['id']))
    conn.commit(); cur.close(); conn.close()

    cooldowns[user_id] = now
    cap = (f"👤 <b>{html.escape(card['name'])}</b> | {card['rating']}\n"
           f"🛡 {html.escape(card['club'])}\n"
           f"✨ {card['rarity']}\n"
           f"💰 Награда: <b>+{reward}</b> ⭐")
    await message.reply_photo(photo=card['photo_id'], caption=cap)

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id=%s", (message.from_user.id,))
    u = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=%s", (message.from_user.id,))
    c_count = cur.fetchone()[0]
    cur.close(); conn.close()
    
    bal = u['balance'] if u else 0
    await message.reply(f"👤 <b>Профиль @{message.from_user.username}</b>\n\n"
                        f"💰 Баланс: <b>{bal}</b> ⭐\n"
                        f"🗂 В коллекции: <b>{c_count}</b> шт.")

@dp.message(F.text == "Магазин 🛒")
async def open_shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Bronze Pack (500⭐)", callback_data="buy_bronze")
    kb.button(text="📦 Gold Pack (2500⭐)", callback_data="buy_gold")
    kb.button(text="📦 Brilliant Pack (5000⭐)", callback_data="buy_brilliant")
    kb.adjust(1)
    await message.answer("🛒 <b>Магазин паков</b>\nВыберите пак для покупки:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy_pack(callback: types.CallbackQuery):
    pack_type = callback.data.split("_")[1]
    costs = {"bronze": 500, "gold": 2500, "brilliant": 5000}
    cost = costs[pack_type]

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (callback.from_user.id,))
    res = cur.fetchone()
    
    if not res or res['balance'] < cost:
        return await callback.answer("❌ Недостаточно звезд!", show_alert=True)

    card = get_card(pack_type)
    reward = get_stars_by_rating(card['rating'])
    cur.execute("UPDATE users SET balance = balance - %s + %s WHERE user_id = %s", (cost, reward, callback.from_user.id))
    cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (callback.from_user.id, card['id']))
    conn.commit(); cur.close(); conn.close()
    
    cap = (f"👤 <b>{html.escape(card['name'])}</b> | {card['rating']}\n"
           f"✨ {card['rarity']}\n💰 Награда: <b>+{reward}</b> ⭐")
    await callback.message.reply_photo(photo=card['photo_id'], caption=cap)
    await callback.answer(f"Куплен {pack_type} пак!")

@dp.message(F.text == "ТОП-10 📊")
async def show_top(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    top_users = cur.fetchall(); cur.close(); conn.close()

    if not top_users: return await message.answer("📊 Список лидеров пуст.")

    text = "📊 <b>ТОП-10 Игроков по звёздам:</b>\n\n"
    for i, user in enumerate(top_users, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} <b>{html.escape(user['username'] or 'Игрок')}</b> — {user['balance']} ⭐\n"
    await message.answer(text)

# --- АДМИН ПАНЕЛЬ ---

@dp.message(Command("reset_progress"))
async def admin_reset(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("TRUNCATE TABLE user_cards")
    cur.execute("UPDATE users SET balance = 1000")
    conn.commit(); cur.close(); conn.close()
    await message.answer("✅ <b>Прогресс всех игроков сброшен!</b>")

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        photo = max(message.photo, key=lambda p: p.file_size)
        temp_photo_buffer[ADMIN_ID] = photo.file_id
        await message.reply("📸 Фото в буфере. Введи /add_player")

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    p_id = temp_photo_buffer.get(ADMIN_ID)
    if not p_id: return await message.reply("❌ Сначала отправь фото!")
    try:
        data = message.text.replace("/add_player ", "").split(", ")
        name, rating, pos, club = data[0].strip(), int(data[1].strip()), data[2].strip(), data[3].strip()
        rtype = "brilliant" if rating >= 90 else "gold" if rating >= 75 else "bronze"
        rlabel = "Brilliant 💎" if rtype == "brilliant" else "Gold 🥇" if rtype == "gold" else "Bronze 🥉"
        
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO all_cards (name, rating, position, rarity, rarity_type, club, photo_id) VALUES (%s,%s,%s,%s,%s,%s,%s)", 
                    (name, rating, pos, rlabel, rtype, club, p_id))
        conn.commit(); cur.close(); conn.close()
        await message.answer(f"✅ Игрок {name} добавлен!")
        del temp_photo_buffer[ADMIN_ID]
    except: await message.answer("❌ Формат: Имя, Рейтинг, Позиция, Клуб")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
