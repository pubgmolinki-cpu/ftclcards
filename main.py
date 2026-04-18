import asyncio, psycopg2, os, html, random, time
from datetime import datetime, timedelta
import pytz 
from psycopg2.extras import DictCursor
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 1866813859))

CHANNELS = ["@ftclcardschannel", "@waxteamiftl", "@ftcloff"]
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Словари состояний
cooldowns = {}          
penalty_cooldowns = {}  
guess_cooldowns = {}
pvp_cooldowns = {}      
temp_photo_buffer = {}  
waiting_for_bet = {}    
active_matches = {}     

# --- ИНИЦИАЛИЗАЦИЯ БД (ЛЕНИВАЯ) ---
def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 5000,
            vip_until TIMESTAMP,
            is_banned BOOLEAN DEFAULT FALSE
        );
        CREATE TABLE IF NOT EXISTS all_cards (
            id SERIAL PRIMARY KEY,
            name TEXT,
            rating INTEGER,
            position TEXT,
            rarity TEXT,
            rarity_type TEXT,
            club TEXT,
            photo_id TEXT
        );
        CREATE TABLE IF NOT EXISTS user_cards (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            card_id INTEGER
        );
        DO $$ 
        BEGIN 
            BEGIN
                ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE;
            EXCEPTION
                WHEN duplicate_column THEN NULL;
            END;
        END $$;
    """)
    conn.commit()
    cur.close()
    conn.close()

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def get_now_msk():
    return datetime.now(MOSCOW_TZ)

# --- ЛОГИ И АНТИЧИТ ---
async def send_log(text):
    try:
        await bot.send_message(ADMIN_ID, f"📑 <b>LOG:</b>\n{text}")
    except: pass

async def check_user_status(user_id):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT is_banned FROM users WHERE user_id = %s", (user_id,))
    res = cur.fetchone()
    cur.close(); conn.close()
    return res[0] if res else False

async def check_subscription(user_id):
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except: return False
    return True

def get_vip_info(user_id):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT vip_until FROM users WHERE user_id = %s", (user_id,))
        res = cur.fetchone()
        now = get_now_msk()
        if res and res['vip_until']:
            vd = res['vip_until']
            if vd.tzinfo is None: vd = MOSCOW_TZ.localize(vd)
            if vd > now: return True, vd
        return False, None
    finally: cur.close(); conn.close()

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
            rtype = "bronze"
            if r == 1: rtype = "legend"
            elif 2 <= r <= 6: rtype = "ivents"
            elif 7 <= r <= 56: rtype = "brilliant" 
            elif 57 <= r <= 206: rtype = "gold"   
            cur.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = %s ORDER BY RANDOM() LIMIT 1", (rtype,))
        return cur.fetchone()
    finally: cur.close(); conn.close()

async def animate_card_opening(message, card):
    steps = ["📦 <b>Открываем пак...</b>", f"\n\n🏃 Позиция: <b>{card['position']}</b>", f"\n🛡 Клуб: <b>{card['club']}</b>", f"\n⭐ Рейтинг: <b>{card['rating']}</b>"]
    txt = ""
    for s in steps:
        txt += s
        try: await message.edit_text(txt); await asyncio.sleep(0.7)
        except: pass
    await asyncio.sleep(0.5); await message.delete()

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    ref_id = command.args
    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
        is_new = cur.fetchone() is None
        cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", 
                     (user_id, message.from_user.username or "Игрок"))
        if is_new and ref_id and ref_id.isdigit() and int(ref_id) != user_id:
            cur.execute("UPDATE users SET balance = balance + 1500 WHERE user_id = %s", (int(ref_id),))
            try: await bot.send_message(int(ref_id), "🎁 У вас новый реферал! <b>+1500 ⭐</b>")
            except: pass
        conn.commit()
    finally: cur.close(); conn.close()
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Реферальная Система 👥"); kb.button(text="ТОП-10 📊")
    kb.adjust(2, 2, 2)
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message((F.text == "Получить Карту 🏆") | (F.text.casefold() == "фтклкарта"))
async def give_card_free(message: types.Message):
    user_id = message.from_user.id
    if await check_user_status(user_id): return await message.answer("🚫 Вы забанены.")
    if not await check_subscription(user_id):
        kb = InlineKeyboardBuilder()
        for ch in CHANNELS:
            kb.button(text=f"Подписаться на {ch}", url=f"https://t.me/{ch.replace('@','')}")
        return await message.answer("❌ <b>Чтобы играть, подпишись на все каналы:</b>", reply_markup=kb.adjust(1).as_markup())
    
    is_vip, _ = get_vip_info(user_id)
    limit = 7200 if is_vip else 14400 
    now = time.time()
    if user_id in cooldowns and (now - cooldowns[user_id]) < limit:
        rem = int(limit - (now - cooldowns[user_id]))
        return await message.reply(f"⏳ Жди {rem//3600}ч. {(rem%3600)//60}мин.")

    card = get_card()
    if not card: return await message.reply("⚠️ База пуста.")

    cooldowns[user_id] = now
    msg = await message.answer("🔄 Подготовка...")
    await animate_card_opening(msg, card)
    
    reward = get_stars_by_rating(card['rating'])
    conn = get_db_connection(); cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (reward, user_id))
        cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (user_id, card['id']))
        conn.commit()
        await message.reply_photo(card['photo_id'], caption=f"👤 {card['name']}\n📊 Рейтинг: {card['rating']}\n🛡 {card['club']}\n💰 +{reward} ⭐")
    finally: cur.close(); conn.close()

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT balance FROM users WHERE user_id=%s", (message.from_user.id,))
        u = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id=%s", (message.from_user.id,))
        cnt = cur.fetchone()[0]
        kb = InlineKeyboardBuilder().button(text="Моя Коллекция 💼", callback_data="my_collection")
        await message.reply(f"👤 <b>@{message.from_user.username}</b>\n💰 Баланс: <b>{u['balance'] if u else 0}</b> ⭐\n🗂 Карт: <b>{cnt}</b>", reply_markup=kb.as_markup())
    finally: cur.close(); conn.close()

@dp.callback_query(F.data == "my_collection")
async def show_collection(callback: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("""
            SELECT c.name, c.rating 
            FROM user_cards uc 
            JOIN all_cards c ON uc.card_id = c.id 
            WHERE uc.user_id = %s 
            ORDER BY c.rating DESC LIMIT 50
        """, (callback.from_user.id,))
        cards = cur.fetchall()
        if not cards: return await callback.answer("У вас еще нет карт!", show_alert=True)
        text = "💼 <b>Твоя коллекция (Топ-50):</b>\n\n" + "\n".join([f"• {c['name']} ({c['rating']})" for c in cards])
        await callback.message.answer(text); await callback.answer()
    finally: cur.close(); conn.close()

# --- МИНИ-ИГРЫ ---
@dp.message(F.text == "Мини-Игры ⚽")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="🥅 Пенальти (x2)", callback_data="game_penalty")
    kb.button(text="🧩 Угадай Игрока (x2)", callback_data="game_guess")
    kb.button(text="⚔️ Матч (PvP)", callback_data="pvp_info")
    kb.adjust(1)
    await message.answer("🎯 <b>Выберите игру:</b>", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "pvp_info")
async def pvp_info(callback: types.CallbackQuery):
    await callback.message.answer("⚔️ <b>Матч (PvP)</b>\n\nЧтобы вызвать игрока, напишите в группе команду: <code>/match [ставка]</code>\nКулдаун: 1 час.")
    await callback.answer()

# --- ПЕНАЛЬТИ (ИСПРАВЛЕНО) ---
@dp.callback_query(F.data == "game_penalty")
async def penalty_init(callback: types.CallbackQuery):
    if await check_user_status(callback.from_user.id): return
    waiting_for_bet[callback.from_user.id] = "penalty"
    await callback.message.edit_text("💰 Введите ставку на пенальти (от 1,000 ⭐):")

async def run_penalty(message: types.Message, bet: int):
    uid = message.from_user.id
    if bet <= 0: return await message.answer("❌ Ставка должна быть положительной!")
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    if not u or u['balance'] < bet:
        cur.close(); conn.close()
        return await message.answer("❌ Недостаточно ⭐!")
    cur.close(); conn.close()

    kb = InlineKeyboardBuilder()
    for s in ["Лево ⬅️", "Центр ⬆️", "Право ➡️"]: kb.button(text=s, callback_data=f"pnl_{bet}")
    await message.answer(f"🥅 Ставка {bet} ⭐. Куда бьем?", reply_markup=kb.adjust(3).as_markup())

@dp.callback_query(F.data.startswith("pnl_"))
async def penalty_finish(callback: types.CallbackQuery):
    uid = callback.from_user.id
    bet = int(callback.data.split("_")[1])
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    if u['balance'] < bet:
        conn.close(); return await callback.message.edit_text("❌ Ошибка баланса!")

    if random.choice([True, False]):
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet, uid))
        await callback.message.edit_text(f"⚽️ <b>ГОООЛ!</b> +{bet} ⭐")
        await send_log(f"💰 @{callback.from_user.username} +{bet} (Пенальти)")
    else:
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, uid))
        await callback.message.edit_text(f"🧤 <b>Вратарь отбил!</b> -{bet} ⭐")
        await send_log(f"📉 @{callback.from_user.username} -{bet} (Пенальти)")
    conn.commit(); cur.close(); conn.close()

# --- УГАДАЙ ИГРОКА ---
@dp.callback_query(F.data == "game_guess")
async def guess_init(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid in guess_cooldowns and time.time() - guess_cooldowns[uid] < 21600:
        rem = int(21600 - (time.time() - guess_cooldowns[uid]))
        return await callback.answer(f"⏳ КД! Жди {rem//3600}ч.", show_alert=True)
    waiting_for_bet[uid] = "guess"
    await callback.message.edit_text("💰 Введите ставку (1,000 - 100,000 ⭐):")

async def run_guess_game(message: types.Message, bet: int):
    uid = message.from_user.id
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
        if cur.fetchone()['balance'] < bet: return await message.answer("❌ Недостаточно ⭐")
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, uid))
        cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
        target = cur.fetchone()
        cur.execute("SELECT name FROM all_cards WHERE name != %s ORDER BY RANDOM() LIMIT 3", (target['name'],))
        names = [target['name']] + [r['name'] for r in cur.fetchall()]
        random.shuffle(names)
        kb = InlineKeyboardBuilder()
        for n in names: kb.button(text=n, callback_data=f"gs_{'w' if n == target['name'] else 'l'}_{bet}")
        guess_cooldowns[uid] = time.time(); conn.commit()
        await message.answer(f"🧩 <b>Угадай игрока</b>\n🛡 {target['club']}\n📊 {target['rating']}\n🏃 {target['position']}", reply_markup=kb.adjust(2).as_markup())
    finally: cur.close(); conn.close()

@dp.callback_query(F.data.startswith("gs_"))
async def guess_check(callback: types.CallbackQuery):
    _, res, bet = callback.data.split("_"); bet = int(bet)
    if res == 'w':
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet*2, callback.from_user.id))
        conn.commit(); cur.close(); conn.close()
        await callback.message.edit_text(f"✅ Верно! +{bet*2} ⭐")
    else: await callback.message.edit_text("❌ Неверно!")

# --- МАТЧ PvP ---
@dp.message(Command("match"))
async def pvp_start(message: types.Message, command: CommandObject):
    if message.chat.type == "private": return await message.answer("❌ Только в группах!")
    if not command.args or not command.args.isdigit(): return await message.answer("❌ /match 1000")
    bet = int(command.args)
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (message.from_user.id,))
    u = cur.fetchone()
    if not u or u['balance'] < bet: return await message.answer("❌ Мало ⭐")
    cur.close(); conn.close()

    m_id = f"m_{message.message_id}"
    active_matches[m_id] = {
        "p1": message.from_user.id, "p1_name": message.from_user.full_name,
        "p2": None, "bet": bet, "p1_ready": False, "p2_ready": False,
        "p1_pts": random.randint(180, 300), "p2_pts": random.randint(180, 300)
    }
    kb = InlineKeyboardBuilder().button(text=f"Принять ({bet} ⭐)", callback_data=f"pj_{m_id}")
    await message.answer(f"⚔️ {message.from_user.mention_html()} вызывает на матч!", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("pj_"))
async def pvp_join(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]
    match = active_matches.get(m_id)
    if not match or match['p2']: return
    if callback.from_user.id == match['p1']: return await callback.answer("Нельзя с собой!")

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (callback.from_user.id,))
    u = cur.fetchone()
    if not u or u['balance'] < match['bet']: return await callback.answer("Мало звезд!", show_alert=True)
    
    cur.execute("UPDATE users SET balance = balance - %s WHERE user_id IN (%s, %s)", (match['bet'], match['p1'], callback.from_user.id))
    conn.commit(); cur.close(); conn.close()

    match['p2'], match['p2_name'] = callback.from_user.id, callback.from_user.full_name
    kb = InlineKeyboardBuilder().button(text="Играть ✅", callback_data=f"pg_{m_id}")
    await callback.message.edit_text(f"⚔️ {match['p1_name']} vs {match['p2_name']}\nЖмите кнопку!", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("pg_"))
async def pvp_go(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]; match = active_matches.get(m_id)
    if not match: return
    if callback.from_user.id == match['p1']: match['p1_ready'] = True
    if callback.from_user.id == match['p2']: match['p2_ready'] = True
    
    if match['p1_ready'] and match['p2_ready']:
        await callback.message.edit_text("⚽️ Матч начался..."); await asyncio.sleep(2)
        p1, p2, bank = match['p1_pts'], match['p2_pts'], match['bet']*2
        conn = get_db_connection(); cur = conn.cursor()
        if p1 > p2:
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id=%s", (bank, match['p1']))
            res = f"🏆 Победил {match['p1_name']}!"
        elif p2 > p1:
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id=%s", (bank, match['p2']))
            res = f"🏆 Победил {match['p2_name']}!"
        else:
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id IN (%s,%s)", (match['bet'], match['p1'], match['p2']))
            res = "🤝 Ничья!"
        conn.commit(); cur.close(); conn.close()
        await callback.message.edit_text(f"🏁 {res}\n{p1} PTS vs {p2} PTS"); active_matches.pop(m_id, None)

# --- СИСТЕМНОЕ ---
@dp.message(F.text == "ТОП-10 📊")
async def show_top(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    top = cur.fetchall(); cur.close(); conn.close()
    await message.answer("📊 <b>ТОП-10:</b>\n\n" + "\n".join([f"{i+1}. {r[0]} - {r[1]}⭐" for i, r in enumerate(top)]))

@dp.message(F.text == "Магазин 🛒")
async def shop_menu(message: types.Message):
    kb = InlineKeyboardBuilder().button(text="📦 Gold (5.7к)", callback_data="buy_gold").button(text="📦 Brilliant (7к)", callback_data="buy_brilliant")
    await message.answer("🛒 Магазин паков:", reply_markup=kb.adjust(1).as_markup())

@dp.message(F.text == "Реферальная Система 👥")
async def ref_link(message: types.Message):
    bot_info = await bot.get_me()
    await message.answer(f"👥 Ссылка: <code>https://t.me/{bot_info.username}?start={message.from_user.id}</code>\n+1500 ⭐ за друга!")

@dp.message(lambda m: m.from_user.id in waiting_for_bet)
async def handle_bets(message: types.Message):
    state = waiting_for_bet.pop(message.from_user.id)
    if not message.text.isdigit(): return
    val = int(message.text)
    if state == "penalty": await run_penalty(message, val)
    elif state == "guess": await run_guess_game(message, val)

@dp.message(Command("ban"))
async def ban_user(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID or not command.args: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET is_banned = TRUE WHERE user_id = %s", (int(command.args),))
    conn.commit(); cur.close(); conn.close()
    await message.answer("🚫 Забанен.")

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
