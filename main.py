import asyncio, psycopg2, os, html, random, time
from datetime import datetime, timedelta
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
CHANNEL_ID = "@ftclcardschannel"  # Юзернейм твоего канала
VIP_PRICE = 15000                 # Цена VIP-статуса

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()
cooldowns = {} 
temp_photo_buffer = {}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

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
        if res and res['vip_until'] and res['vip_until'] > datetime.now():
            return True, res['vip_until']
        return False, None
    finally:
        cur.close(); conn.close()

# --- ВЕБ-СЕРВЕР (АНТИ-СОН) ---
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
        cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", 
                     (user_id, message.from_user.username or "Игрок"))
        if referrer_id and referrer_id.isdigit() and int(referrer_id) != user_id:
            cur.execute("UPDATE users SET balance = balance + 1500 WHERE user_id = %s", (int(referrer_id),))
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
    
    # Проверка подписки
    if not await check_subscription(user_id):
        return await message.answer(
            f"❌ <b>Доступ ограничен!</b>\n\nПодпишись на наш канал, чтобы получать карты:\n{CHANNEL_ID}",
            reply_markup=InlineKeyboardBuilder().button(text="Подписаться 📢", url=f"https://t.me/ftclcardschannel").as_markup()
        )

    # Проверка VIP и КД
    is_vip, until_date = get_vip_info(user_id)
    cooldown_limit = 7200 if is_vip else 14400 # 2ч или 4ч
    
    now = time.time()
    if user_id in cooldowns and now - cooldowns[user_id] < cooldown_limit:
        rem = int(cooldown_limit - (now - cooldowns[user_id]))
        return await message.reply(f"⏳ Приходи через {rem//3600}ч. {(rem%3600)//60}мин.")
    
    card = get_card()
    if not card: return await message.reply("⚠️ База пуста.")
    
    reward = get_stars_by_rating(card['rating'])
    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, user_id))
        cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (user_id, card['id']))
        conn.commit()
        cooldowns[user_id] = now
        
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
    await message.answer("🛒 <b>Магазин улучшений</b>", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "buy_vip")
async def buy_vip_status(callback: types.CallbackQuery):
    is_vip, _ = get_vip_info(callback.from_user.id)
    if is_vip: return await callback.answer("⚡️ У тебя уже есть VIP!", show_alert=True)
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT balance FROM users WHERE user_id = %s", (callback.from_user.id,))
        res = cur.fetchone()
        if not res or res['balance'] < VIP_PRICE: 
            return await callback.answer(f"❌ Нужно {VIP_PRICE} ⭐", show_alert=True)
            
        expire_date = datetime.now() + timedelta(hours=24)
        cur.execute("UPDATE users SET balance = balance - %s, vip_until = %s WHERE user_id = %s", 
                    (VIP_PRICE, expire_date, callback.from_user.id))
        conn.commit()
        await callback.message.answer(f"🚀 <b>VIP активирован на 24 часа!</b>\nКД снижено до 2 часов.")
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
        
        vip_str = "❌"
        if u and u['vip_until'] and u['vip_until'] > datetime.now():
            vip_str = f"✅ до {u['vip_until'].strftime('%H:%M')}"

        text = (f"👤 <b>@{message.from_user.username}</b>\n"
                f"💰 Баланс: <b>{u['balance'] if u else 0}</b> ⭐\n"
                f"🗂 Карт в коллекции: <b>{c_count}</b>\n"
                f"⚡️ VIP-статус: <b>{vip_str}</b>")
        
        kb = InlineKeyboardBuilder().button(text="Коллекция 🗂", callback_data="show_collection")
        await message.reply(text, reply_markup=kb.as_markup())
    finally:
        cur.close(); conn.close()

# --- АДМИНКА ---

@dp.message(F.photo & (F.from_user.id == ADMIN_ID))
async def handle_photo(message: types.Message):
    photo = max(message.photo, key=lambda p: p.file_size)
    temp_photo_buffer[ADMIN_ID] = photo.file_id
    await message.reply("📸 Фото сохранено. Теперь: `/add_player Имя, Рейтинг, Поз, Клуб`")

@dp.message(Command("add_player"))
async def add_player(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    p_id = temp_photo_buffer.get(ADMIN_ID)
    if not p_id: return await message.reply("❌ Нет фото в буфере!")
    try:
        args = message.text.replace("/add_player ", "").split(",")
        name, rating, pos, club = args[0].strip(), int(args[1].strip()), args[2].strip(), args[3].strip()
        
        if rating >= 99: rtype, rlabel = "legend", "Legend ✨"
        elif rating >= 95: rtype, rlabel = "ivents", "Ivents 🎊"
        elif rating >= 90: rtype, rlabel = "brilliant", "Brilliant 💎"
        elif rating >= 75: rtype, rlabel = "gold", "Gold 🥇"
        else: rtype, rlabel = "bronze", "Bronze 🥉"

        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("INSERT INTO all_cards (name, rating, position, rarity, rarity_type, club, photo_id) VALUES (%s,%s,%s,%s,%s,%s,%s)", 
                    (name, rating, pos, rlabel, rtype, club, p_id))
        conn.commit(); cur.close(); conn.close()
        await message.answer(f"✅ Добавлен: {name}"); del temp_photo_buffer[ADMIN_ID]
    except: await message.answer("❌ Формат: Имя, Рейтинг, Поз, Клуб")

# --- ЗАПУСК И ЛЕНИВАЯ БД ---
async def main():
    # Ленивый способ добавления колонки
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS vip_until TIMESTAMP DEFAULT NULL;")
        conn.commit(); cur.close(); conn.close()
        print("✅ БД обновлена")
    except Exception as e:
        print(f"Ошибка БД: {e}")

    asyncio.create_task(start_webserver())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
