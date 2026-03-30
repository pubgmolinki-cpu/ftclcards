import asyncio, psycopg2, os, html, random, time
from datetime import datetime, timedelta
import pytz # Обязательно добавь в requirements.txt
from psycopg2.extras import DictCursor
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 1866813859))
PORT = int(os.getenv("PORT", 8080))
CHANNEL_ID = "@ftclcardschannel"
VIP_PRICE = 15000

# Установка Московского времени
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()
cooldowns = {} 
temp_photo_buffer = {}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def get_now_msk():
    return datetime.now(MOSCOW_TZ)

# --- ПРОВЕРКА ПОДПИСКИ ---
async def check_subscription(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# --- ЛОГИКА VIP ---
def get_vip_info(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT vip_until FROM users WHERE user_id = %s", (user_id,))
        res = cur.fetchone()
        now = get_now_msk()
        if res and res['vip_until']:
            # Приводим время из БД к МСК для сравнения
            vip_date = res['vip_until']
            if vip_date.tzinfo is None:
                vip_date = MOSCOW_TZ.localize(vip_date)
            
            if vip_date > now:
                return True, vip_date
        return False, None
    finally:
        cur.close(); conn.close()

# --- ВЕБ-СЕРВЕР ---
async def handle(request):
    return web.Response(text="Bot is running! ⚽️", content_type='text/html')

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

# --- ЛОГИКА КАРТ ---
def get_stars_by_rating(rating):
    if rating >= 99: return 10000 
    if rating >= 95: return 5000  
    rates = {90: 2500, 85: 2000, 80: 1750, 75: 1500, 70: 1250, 60: 1000, 55: 500}
    for r, val in rates.items():
        if rating >= r: return val
    return 250

def get_card(rarity_filter=None):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        if rarity_filter:
            cur.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = %s ORDER BY RANDOM() LIMIT 1", (rarity_filter.lower(),))
        else:
            r = random.randint(1, 1000)
            if r == 1: rtype = "legend"
            elif 2 <= r <= 6: rtype = "ivents"
            elif 7 <= r <= 56: rtype = "brilliant" 
            elif 57 <= r <= 206: rtype = "gold"   
            else: rtype = "bronze" 
            cur.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = %s ORDER BY RANDOM() LIMIT 1", (rtype,))
        card = cur.fetchone()
        if not card: 
            cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
            card = cur.fetchone()
        return card
    finally:
        cur.close(); conn.close()

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    referrer_id = command.args
    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
        is_new = cur.fetchone() is None
        cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", 
                     (user_id, message.from_user.username or "Игрок"))
        if is_new and referrer_id and referrer_id.isdigit() and int(referrer_id) != user_id:
            cur.execute("UPDATE users SET balance = balance + 1500 WHERE user_id = %s", (int(referrer_id),))
            try: await bot.send_message(int(referrer_id), "🎁 У вас новый реферал! <b>+1500 ⭐</b>")
            except: pass
        conn.commit()
    finally:
        cur.close(); conn.close()
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Магазин 🛒")
    kb.button(text="Профиль 👤"); kb.button(text="Реферальная Система 👥")
    kb.button(text="ТОП-10 📊")
    kb.adjust(2, 2, 1)
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message((F.text == "Получить Карту 🏆") | (F.text.casefold() == "фтклкарта"))
async def give_card_free(message: types.Message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        return await message.answer(f"❌ <b>Доступ ограничен!</b>\n\nПодпишись на канал:\n{CHANNEL_ID}",
            reply_markup=InlineKeyboardBuilder().button(text="Подписаться 📢", url="https://t.me/ftclcardschannel").as_markup())

    is_vip, until_date = get_vip_info(user_id)
    cooldown_limit = 7200 if is_vip else 14400 
    
    now_ts = time.time()
    if user_id in cooldowns and now_ts - cooldowns[user_id] < cooldown_limit:
        rem = int(cooldown_limit - (now_ts - cooldowns[user_id]))
        return await message.reply(f"⏳ Приходи через {rem//3600}ч. {(rem%3600)//60}мин.")
    
    card = get_card()
    if not card: return await message.reply("⚠️ База пуста.")
    
    reward = get_stars_by_rating(card['rating'])
    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, user_id))
        cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (user_id, card['id']))
        conn.commit()
        cooldowns[user_id] = now_ts
        
        status_tag = f"⚡️ VIP (до {until_date.strftime('%H:%M')})" if is_vip else "👤 Игрок"
        caption = (
            f"<b>ВАМ ВЫПАЛА КАРТА 🎉</b>\n\n"
            f"👤 <b>{html.escape(card['name'])}</b>\n"
            f"📊 {card['rating']} Рейтинг 🛎️\n"
            f"🛡 Клуб: {html.escape(card['club'])} 🎊\n"
            f"📈 Позиция: {html.escape(card['position'])}\n"
            f"✨ {card['rarity']}\n"
            f"💰 <b>+{reward}</b> ⭐\n\n"
            f"📋 Твой статус: {status_tag}"
        )
        await message.reply_photo(photo=card['photo_id'], caption=caption)
    finally:
        cur.close(); conn.close()

@dp.message(F.text == "Магазин 🛒")
async def open_shop(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Bronze (4000⭐)", callback_data="buy_bronze")
    kb.button(text="📦 Gold (5700⭐)", callback_data="buy_gold")
    kb.button(text="📦 Brilliant (7000⭐)", callback_data="buy_brilliant")
    kb.button(text=f"⚡️ VIP на 24ч ({VIP_PRICE}⭐)", callback_data="buy_vip")
    kb.adjust(1)
    await message.answer("🛒 <b>Магазин</b>", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    action = callback.data.split("_")[1]
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
        u = cur.fetchone()
        if action == "vip":
            is_vip, _ = get_vip_info(user_id)
            if is_vip: return await callback.answer("У вас уже есть VIP!", show_alert=True)
            if u['balance'] < VIP_PRICE: return await callback.answer("Недостаточно ⭐", show_alert=True)
            
            expire = get_now_msk() + timedelta(hours=24)
            cur.execute("UPDATE users SET balance = balance - %s, vip_until = %s WHERE user_id = %s", (VIP_PRICE, expire, user_id))
            conn.commit()
            await callback.message.answer(f"🚀 VIP активирован до {expire.strftime('%H:%M')} (МСК) завтра!")
        else:
            costs = {"bronze": 4000, "gold": 5700, "brilliant": 7000}
            cost = costs[action]
            if u['balance'] < cost: return await callback.answer("Недостаточно ⭐", show_alert=True)
            card = get_card(action)
            reward = get_stars_by_rating(card['rating'])
            cur.execute("UPDATE users SET balance = balance - %s + %s WHERE user_id = %s", (cost, reward, user_id))
            cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (user_id, card['id']))
            conn.commit()
            await callback.message.reply_photo(photo=card['photo_id'], caption=f"👤 <b>{card['name']}</b>\n💰 <b>+{reward}</b> ⭐")
        await callback.answer()
    finally:
        cur.close(); conn.close()

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT balance, vip_until FROM users WHERE user_id=%s", (message.from_user.id,))
        u = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=%s", (message.from_user.id,))
        c_count = cur.fetchone()[0]
        
        vip_status = "❌"
        if u and u['vip_until']:
            vip_date = u['vip_until']
            if vip_date.tzinfo is None: vip_date = MOSCOW_TZ.localize(vip_date)
            if vip_date > get_now_msk():
                vip_status = f"✅ до {vip_date.strftime('%d.%m %H:%M')} (МСК)"

        text = (f"👤 <b>@{message.from_user.username}</b>\n"
                f"💰 Баланс: <b>{u['balance'] if u else 0}</b> ⭐\n"
                f"🗂 Карт: <b>{c_count}</b>\n"
                f"⚡️ VIP: <b>{vip_status}</b>")
        
        kb = InlineKeyboardBuilder().button(text="Коллекция 🗂", callback_data="show_collection")
        await message.reply(text, reply_markup=kb.as_markup())
    finally:
        cur.close(); conn.close()

@dp.callback_query(F.data == "show_collection")
async def view_collection(callback: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT c.name, c.rating FROM all_cards c JOIN user_cards uc ON c.id = uc.card_id WHERE uc.user_id = %s ORDER BY c.rating DESC", (callback.from_user.id,))
        cards = cur.fetchall()
        if not cards: return await callback.answer("Пусто!", show_alert=True)
        text = "🗂 <b>Твоя коллекция:</b>\n\n" + "\n".join([f"▫️ {c['name']} ({c['rating']})" for c in cards[:40]])
        await callback.message.answer(text); await callback.answer()
    finally:
        cur.close(); conn.close()

@dp.message(F.text == "Реферальная Система 👥")
async def ref_system(message: types.Message):
    bot_me = await bot.get_me()
    ref_link = f"https://t.me/{bot_me.username}?start={message.from_user.id}"
    await message.answer(f"👥 <b>Рефералы</b>\nПолучай <b>1500 ⭐</b> за друга!\n\nСсылка:\n<code>{ref_link}</code>")

@dp.message(F.text == "ТОП-10 📊")
async def show_top(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
        top = cur.fetchall()
        text = "📊 <b>Лидеры:</b>\n\n" + "\n".join([f"{i}. {u['username']} — {u['balance']}⭐" for i, u in enumerate(top, 1)])
        await message.answer(text)
    finally:
        cur.close(); conn.close()

# --- АДМИНКА ---
@dp.message(F.photo & (F.from_user.id == ADMIN_ID))
async def handle_photo(message: types.Message):
    photo = max(message.photo, key=lambda p: p.file_size)
    temp_photo_buffer[ADMIN_ID] = photo.file_id
    await message.reply("📸 Фото в буфере. Жду: `/add_player Имя, Рейтинг, Поз, Клуб`")

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    p_id = temp_photo_buffer.get(ADMIN_ID)
    if not p_id: return await message.reply("❌ Сначала фото!")
    try:
        args = message.text.replace("/add_player ", "").split(",")
        name, rating, pos, club = args[0].strip(), int(args[1].strip()), args[2].strip(), args[3].strip()
        if rating >= 99: rtype, rlabel = "legend", "Legend ✨"
        elif rating >= 95: rtype, rlabel = "ivents", "Ivents 🎊"
        elif rating >= 90: rtype, rlabel = "brilliant", "Brilliant 💎"
        elif rating >= 75: rtype, rlabel = "gold", "Gold 🥇"
        else: rtype, rlabel = "bronze", "Bronze 🥉"
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO all_cards (name, rating, position, rarity, rarity_type, club, photo_id) VALUES (%s,%s,%s,%s,%s,%s,%s)", (name, rating, pos, rlabel, rtype, club, p_id))
        conn.commit(); cur.close(); conn.close()
        await message.answer(f"✅ Добавлен: {name}"); del temp_photo_buffer[ADMIN_ID]
    except: await message.answer("❌ Формат: Имя, Рейтинг, Поз, Клуб")

async def main():
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_until TIMESTAMP DEFAULT NULL;")
        conn.commit(); cur.close(); conn.close()
    except: pass
    asyncio.create_task(start_webserver())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
