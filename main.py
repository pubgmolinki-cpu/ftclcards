import asyncio, psycopg2, os, html, random, time
from datetime import datetime, timedelta
import pytz 
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

CHANNELS = ["@ftclcardschannel", "@waxteamiftl"]
VIP_PRICE = 15000
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Словари состояний в памяти
cooldowns = {}          
penalty_cooldowns = {}  
guess_cooldowns = {}
pvp_cooldowns = {}      
temp_photo_buffer = {}  
waiting_for_bet = {}    # {user_id: тип_ожидания}
pvp_lobby = {}          # {opponent_id: {challenger_id, bet}}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def get_now_msk():
    return datetime.now(MOSCOW_TZ)

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
    if not await check_subscription(user_id):
        return await message.answer("❌ Подпишись на каналы проекта!")
    
    is_vip, _ = get_vip_info(user_id)
    limit = 7200 if is_vip else 14400 
    now = time.time()
    if user_id in cooldowns and (now - cooldowns[user_id]) < limit:
        rem = int(limit - (now - cooldowns[user_id]))
        return await message.reply(f"⏳ Жди {rem//3600}ч. {(rem%3600)//60}мин.")

    cooldowns[user_id] = now
    card = get_card()
    if not card: 
        del cooldowns[user_id]
        return await message.reply("⚠️ База пуста.")

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
    await callback.message.answer("⚔️ <b>Матч (PvP)</b>\n\nЧтобы вызвать игрока, ответьте на его сообщение в чате командой <code>/match</code>\nКулдаун: 1 час.")
    await callback.answer()

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
        for n in names:
            kb.button(text=n, callback_data=f"gs_{'w' if n == target['name'] else 'l'}_{bet}")
        
        guess_cooldowns[uid] = time.time()
        conn.commit()
        await message.answer(f"🧩 <b>Угадай, кто это?</b>\n\n🛡 Клуб: {target['club']}\n📊 Рейтинг: {target['rating']}\n🏃 Поз: {target['position']}", reply_markup=kb.adjust(2).as_markup())
    finally: cur.close(); conn.close()

@dp.callback_query(F.data.startswith("gs_"))
async def guess_check(callback: types.CallbackQuery):
    _, res, bet = callback.data.split("_"); bet = int(bet)
    if res == 'w':
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet*2, callback.from_user.id))
        conn.commit(); cur.close(); conn.close()
        await callback.message.edit_text(f"✅ Правильно! Вы выиграли {bet*2} ⭐")
    else:
        await callback.message.edit_text(f"❌ Неверно! Ставка {bet} ⭐ потеряна.")

# --- ТОВАРИЩЕСКИЙ МАТЧ (PvP) ---
@dp.message(Command("match"))
async def pvp_start(message: types.Message):
    if not message.reply_to_message: return await message.reply("❌ Ответьте на сообщение соперника!")
    ch_id, opp_id = message.from_user.id, message.reply_to_message.from_user.id
    if ch_id == opp_id: return
    
    for u in [ch_id, opp_id]:
        if u in pvp_cooldowns and time.time() - pvp_cooldowns[u] < 3600:
            return await message.answer("⏳ Один из игроков еще не отошел от прошлого матча (КД 1ч).")

    pvp_lobby[opp_id] = {"ch_id": ch_id}
    kb = InlineKeyboardBuilder().button(text="Принять ✅", callback_data=f"pvpok_{ch_id}").button(text="Отказ ❌", callback_data="pvpno")
    await bot.send_message(opp_id, f"⚔️ @{message.from_user.username} вызывает вас на матч!", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("pvpok_"))
async def pvp_accept(callback: types.CallbackQuery):
    ch_id = int(callback.data.split("_")[1])
    waiting_for_bet[callback.from_user.id] = f"pbet_{ch_id}"
    await callback.message.edit_text("💰 Введите сумму вашей ставки:")

@dp.message(lambda m: m.from_user.id in waiting_for_bet)
async def handle_all_bets(message: types.Message):
    uid = message.from_user.id
    state = waiting_for_bet.pop(uid)
    if not message.text.isdigit(): return
    val = int(message.text)

    if state == "guess": await run_guess_game(message, val)
    elif state.startswith("pbet_"):
        ch_id = int(state.split("_")[1])
        pvp_lobby[uid]["bet"] = val
        kb = InlineKeyboardBuilder().button(text="Начать матч! ⚽️", callback_data=f"pgo_{uid}_{val}")
        await bot.send_message(ch_id, f"💰 Соперник поставил {val} ⭐. Подтверждаете?", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("pgo_"))
async def pvp_engine(callback: types.CallbackQuery):
    _, opp_id, bet = callback.data.split("_"); opp_id, bet = int(opp_id), int(bet)
    ch_id = callback.from_user.id
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT balance FROM users WHERE user_id IN (%s, %s)", (ch_id, opp_id))
        if any(r[0] < bet for r in cur.fetchall()): return await callback.message.answer("❌ У кого-то кончились звезды!")
        
        def get_pwr(u):
            cur.execute("SELECT c.rating FROM user_cards uc JOIN all_cards c ON uc.card_id=c.id WHERE uc.user_id=%s ORDER BY RANDOM() LIMIT 3", (u,))
            res = [r[0] for r in cur.fetchall()]
            return sum(res), res

        p1_t, p1_c = get_pwr(ch_id); p2_t, p2_c = get_pwr(opp_id)
        if not p1_c or not p2_c: return await callback.message.answer("❌ Нет карт!")

        pvp_cooldowns[ch_id] = pvp_cooldowns[opp_id] = time.time()
        if p1_t > p2_t:
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id=%s", (bet, ch_id))
            cur.execute("UPDATE users SET balance = balance - %s WHERE user_id=%s", (bet, opp_id))
            win_txt = f"🏆 Победил @{callback.from_user.username}!"
        elif p2_t > p1_t:
            cur.execute("UPDATE users SET balance = balance + %s WHERE user_id=%s", (bet, opp_id))
            cur.execute("UPDATE users SET balance = balance - %s WHERE user_id=%s", (bet, ch_id))
            win_txt = "🏆 Победил соперник!"
        else: win_txt = "🤝 Ничья!"

        conn.commit()
        res = f"⚔️ <b>Матч:</b> {p1_t} ПТС vs {p2_t} ПТС\n\n{win_txt}"
        await callback.message.answer(res); await bot.send_message(opp_id, res)
    finally: cur.close(); conn.close()

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

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
