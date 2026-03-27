import asyncio, psycopg2, os, html, random, time
from psycopg2.extras import DictCursor
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = 1866813859 

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()
cooldowns = {} 
temp_photo_buffer = {}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# --- ЛОГИКА НАГРАД ---
def get_stars_by_rating(rating):
    if rating >= 99: return 10000 # Legend ✨
    if rating >= 95: return 5000  # Ivents 🎊
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
        # Шансы: Бронза 76%, Голд 15%, Бриллиант 5%, Ивент 3%, Легенд 1%
        r = random.randint(1, 100)
        if r <= 76: rtype = "bronze"
        elif r <= 91: rtype = "gold"
        elif r <= 96: rtype = "brilliant"
        elif r <= 99: rtype = "ivents"
        else: rtype = "legend"
        
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
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", 
                 (user_id, message.from_user.username or "Игрок"))
    if is_new and referrer_id and referrer_id.isdigit() and int(referrer_id) != user_id:
        ref_id = int(referrer_id)
        cur.execute("UPDATE users SET balance = balance + 5000 WHERE user_id = %s", (ref_id,))
        try: await bot.send_message(ref_id, "🎁 У вас новый реферал! Зачислено <b>5000 ⭐</b>")
        except: pass
    conn.commit(); cur.close(); conn.close()
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆")
    kb.button(text="Магазин 🛒")
    kb.button(text="Профиль 👤")
    kb.button(text="Реферальная Система 👥")
    kb.button(text="ТОП-10 📊")
    kb.adjust(2, 2, 1)
    await message.answer("⚽️ <b>FTCL Cards готов к старту!</b>", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text == "Реферальная Система 👥")
async def ref_system(message: types.Message):
    bot_me = await bot.get_me()
    ref_link = f"https://t.me/{bot_me.username}?start={message.from_user.id}"
    await message.answer(f"👥 <b>Реферальная Система</b>\n\nПриглашай друзей и получай <b>5000 ⭐</b>!\n\nВот ваша ссылка:\n<code>{ref_link}</code> ⚽")

@dp.message((F.text == "Получить Карту 🏆") | (F.text.casefold() == "фтклкарта"))
async def give_card_free(message: types.Message):
    user_id = message.from_user.id
    now = time.time()
    if user_id in cooldowns and now - cooldowns[user_id] < 28800: # 8 часов
        rem = int(28800 - (now - cooldowns[user_id]))
        return await message.reply(f"⏳ Карта будет доступна через <b>{rem//3600}ч. {(rem%3600)//60}мин.</b>")
    
    card = get_card()
    if not card: return await message.reply("⚠️ База пуста.")
    reward = get_stars_by_rating(card['rating'])
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, user_id))
    cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (user_id, card['id']))
    conn.commit(); cur.close(); conn.close()
    cooldowns[user_id] = now
    await message.reply_photo(photo=card['photo_id'], caption=f"👤 <b>{html.escape(card['name'])}</b> | {card['rating']}\n✨ {card['rarity']}\n💰 <b>+{reward}</b> ⭐")

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id=%s", (message.from_user.id,))
    u = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=%s", (message.from_user.id,))
    c_count = cur.fetchone()[0]
    cur.close(); conn.close()
    kb = InlineKeyboardBuilder()
    kb.button(text="Посмотреть Коллекцию 🗂", callback_data="show_collection")
    await message.reply(f"👤 <b>Профиль @{message.from_user.username}</b>\n\n💰 Баланс: <b>{u['balance'] if u else 0}</b> ⭐\n🗂 В коллекции: <b>{c_count}</b> шт.", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "show_collection")
async def view_collection(callback: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("""SELECT c.name, c.rating FROM all_cards c 
                   JOIN user_cards uc ON c.id = uc.card_id 
                   WHERE uc.user_id = %s""", (callback.from_user.id,))
    cards = cur.fetchall(); cur.close(); conn.close()
    if not cards: return await callback.answer("Пусто!", show_alert=True)
    text = "🗂 <b>Твоя коллекция:</b>\n\n" + "\n".join([f"▫️ {c['name']} ({c['rating']})" for c in cards])
    await callback.message.answer(text[:4096]); await callback.answer()

@dp.message(F.text == "Магазин 🛒")
async def open_shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Bronze (1000⭐)", callback_data="buy_bronze")
    kb.button(text="📦 Gold (1850⭐)", callback_data="buy_gold")
    kb.button(text="📦 Brilliant (2500⭐)", callback_data="buy_brilliant")
    kb.adjust(1)
    await message.answer("🛒 <b>Магазин паков</b>", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy_pack(callback: types.CallbackQuery):
    pack = callback.data.split("_")[1]
    costs = {"bronze": 1000, "gold": 1850, "brilliant": 2500}
    cost = costs[pack]
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (callback.from_user.id,))
    res = cur.fetchone()
    if not res or res['balance'] < cost: return await callback.answer("❌ Мало звезд!", show_alert=True)
    card = get_card(pack)
    reward = get_stars_by_rating(card['rating'])
    cur.execute("UPDATE users SET balance = balance - %s + %s WHERE user_id = %s", (cost, reward, callback.from_user.id))
    cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (callback.from_user.id, card['id']))
    conn.commit(); cur.close(); conn.close()
    await callback.message.reply_photo(photo=card['photo_id'], caption=f"👤 <b>{card['name']}</b>\n💰 <b>+{reward}</b> ⭐")
    await callback.answer("Успешно!")

@dp.message(F.text == "ТОП-10 📊")
async def show_top(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    top = cur.fetchall(); cur.close(); conn.close()
    text = "📊 <b>Лидеры:</b>\n\n" + "\n".join([f"{i}. {u['username']} — {u['balance']}⭐" for i, u in enumerate(top, 1)])
    await message.answer(text)

# --- АДМИН ПАНЕЛЬ ---

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        photo = max(message.photo, key=lambda p: p.file_size)
        temp_photo_buffer[ADMIN_ID] = photo.file_id
        await message.reply("📸 Фото сохранено. Введи /add_player")

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    p_id = temp_photo_buffer.get(ADMIN_ID)
    if not p_id: return await message.reply("❌ Сначала фото!")
    try:
        data = message.text.replace("/add_player ", "").split(", ")
        name, rating, pos, club = data[0].strip(), int(data[1].strip()), data[2].strip(), data[3].strip()
        if rating == 99: rtype, rlabel = "legend", "Legend ✨"
        elif rating == 95: rtype, rlabel = "ivents", "Ivents 🎊"
        elif rating >= 90: rtype, rlabel = "brilliant", "Brilliant 💎"
        elif rating >= 75: rtype, rlabel = "gold", "Gold 🥇"
        else: rtype, rlabel = "bronze", "Bronze 🥉"
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO all_cards (name, rating, position, rarity, rarity_type, club, photo_id) VALUES (%s,%s,%s,%s,%s,%s,%s)", 
                    (name, rating, pos, rlabel, rtype, club, p_id))
        conn.commit(); cur.close(); conn.close()
        await message.answer(f"✅ Добавлен: {name} ({rlabel})")
        del temp_photo_buffer[ADMIN_ID]
    except: await message.answer("❌ Ошибка формата!")

@dp.message(Command("reset_progress"))
async def admin_reset(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("TRUNCATE TABLE user_cards"); cur.execute("UPDATE users SET balance = 1000")
        conn.commit(); cur.close(); conn.close()
        await message.answer("✅ Прогресс сброшен.")

async def main(): await dp.start_polling(bot)
if __name__ == "__main__": asyncio.run(main())
