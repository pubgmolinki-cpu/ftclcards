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

CHANNELS = ["@ftclcardschannel", "@Dempik_lega", "@waxteamiftl"]
VIP_PRICE = 15000
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Кэши
cooldowns, penalty_cooldowns, pvp_cooldowns = {}, {}, {}
temp_photo_buffer, waiting_for_bet, active_duels = {}, {}, {}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def get_now_msk():
    return datetime.now(MOSCOW_TZ)

async def check_subscription(user_id):
    for ch in CHANNELS:
        try:
            m = await bot.get_chat_member(chat_id=ch, user_id=user_id)
            if m.status in ["member", "administrator", "creator"]: return True
        except: pass
    return False

def get_vip_info(user_id):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT vip_until FROM users WHERE user_id = %s", (user_id,))
        res = cur.fetchone()
        if res and res['vip_until']:
            vd = res['vip_until'].replace(tzinfo=pytz.UTC).astimezone(MOSCOW_TZ)
            if vd > get_now_msk(): return True, vd
        return False, None
    finally: cur.close(); conn.close()

# --- ЛОГИКА КАРТ ---
def get_card(rarity=None):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        if rarity:
            cur.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = %s ORDER BY RANDOM() LIMIT 1", (rarity.lower(),))
        else:
            r = random.randint(1, 1000)
            rt = "legend" if r==1 else "ivents" if 2<=r<=6 else "brilliant" if 7<=r<=56 else "gold" if 57<=r<=206 else "bronze"
            cur.execute("SELECT * FROM all_cards WHERE LOWER(rarity_type) = %s ORDER BY RANDOM() LIMIT 1", (rt,))
        return cur.fetchone()
    finally: cur.close(); conn.close()

def get_stars_by_rating(rating):
    if rating >= 99: return 10000 
    if rating >= 95: return 5000  
    for r, val in {90:2500, 85:2000, 80:1750, 75:1500, 70:1250, 60:1000, 55:500}.items():
        if rating >= r: return val
    return 250

# --- ОБРАБОТКА СТАВКИ ПВП (САМЫЙ ВЕРХНИЙ ПРИОРИТЕТ) ---
@dp.message(lambda m: m.from_user.id in waiting_for_bet)
async def bet_capture(message: types.Message):
    user_id = message.from_user.id
    state = waiting_for_bet[user_id]
    
    if not message.text.isdigit(): return
    bet = int(message.text)
    
    if state['type'] == 'pvp':
        p1_id = state['opponent']
        conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT balance, username FROM users WHERE user_id IN (%s, %s)", (p1_id, user_id))
        users = {u['user_id']: u for u in cur.fetchall()}
        
        if len(users) < 2 or any(u['balance'] < bet for u in users.values()):
            waiting_for_bet.pop(user_id, None)
            return await message.answer("❌ Недостаточно ⭐ у одного из игроков!")

        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id IN (%s, %s)", (bet, p1_id, user_id))
        conn.commit(); cur.close(); conn.close()
        
        waiting_for_bet.pop(user_id)
        pvp_cooldowns[p1_id] = pvp_cooldowns[user_id] = time.time()
        
        d_id = f"d_{p1_id}_{user_id}_{int(time.time())}"
        active_duels[d_id] = {
            "p1": p1_id, "p2": user_id, "bet": bet, "score": {p1_id: 0, user_id: 0},
            "round": 1, "stage": "kick", "att": p1_id, "def": user_id, "chat_id": message.chat.id,
            "names": {p1_id: users[p1_id]['username'], user_id: users[user_id]['username']}
        }
        await message.answer(f"🚀 Ставка {bet} ⭐ принята! Кнопки ударов в ЛС у игроков!")
        await pvp_step(d_id)
        
    elif state['type'] == 'bot':
        # Логика пенальти против бота (оставим стандартную)
        pass

# --- PvP МЕХАНИКА ---
async def pvp_step(d_id):
    d = active_duels[d_id]
    kb = InlineKeyboardBuilder()
    for s, n in {"L": "Лево ⬅️", "C": "Центр ⬆️", "R": "Право ➡️"}.items():
        kb.button(text=n, callback_data=f"p_do_{d_id}_{s}")
    
    status = f"🏟 Раунд {d['round']}\nСчет: {d['score'][d['p1']]} - {d['score'][d['p2']]}"
    try:
        await bot.send_message(d['att'], f"⚽️ <b>Твой удар!</b>\n{status}", reply_markup=kb.as_markup())
        await bot.send_message(d['def'], f"🧤 Ожидай удара соперника...\n{status}")
    except:
        await bot.send_message(d['chat_id'], f"❌ Игрок {d['names'][d['att']]} или {d['names'][d['def']]} не запустил бота в ЛС!")

@dp.callback_query(F.data.startswith("p_do_"))
async def pvp_logic(c: types.CallbackQuery):
    _, _, d_id, side = c.data.split("_")
    d = active_duels.get(d_id)
    if not d: return
    
    if d['stage'] == "kick" and c.from_user.id == d['att']:
        d['side'], d['stage'] = side, "save"
        await c.message.edit_text("🎯 Удар нанесен!")
        kb = InlineKeyboardBuilder()
        for s, n in {"L": "Лево ⬅️", "C": "Центр ⬆️", "R": "Право ➡️"}.items():
            kb.button(text=n, callback_data=f"p_do_{d_id}_{s}")
        await bot.send_message(d['def'], "🧤 Твой сейв! Куда прыгаешь?", reply_markup=kb.as_markup())
        
    elif d['stage'] == "save" and c.from_user.id == d['def']:
        goal = d['side'] != side
        if goal: d['score'][d['att']] += 1
        res = f"{'⚽️ ГОООЛ!' if goal else '🧤 СЕЙВ!'}\n{d['names'][d['att']]} бил {d['side']}, {d['names'][d['def']]} прыгнул {side}"
        await bot.send_message(d['p1'], res); await bot.send_message(d['p2'], res)
        
        if d['att'] == d['p1']:
            d['att'], d['def'], d['stage'] = d['p2'], d['p1'], "kick"
            await pvp_step(d_id)
        else:
            if d['round'] >= 3 and d['score'][d['p1']] != d['score'][d['p2']]:
                await pvp_finish(d_id)
            else:
                d['round'] += 1; d['att'], d['def'], d['stage'] = d['p1'], d['p2'], "kick"
                await pvp_step(d_id)

async def pvp_finish(d_id):
    d = active_duels[d_id]
    w_id = d['p1'] if d['score'][d['p1']] > d['score'][d['p2']] else d['p2']
    prize = d['bet'] * 2
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (prize, w_id))
    conn.commit(); cur.close(); conn.close()
    await bot.send_message(d['chat_id'], f"🏆 <b>Победа!</b>\nПобедитель: {d['names'][w_id]}\nСчет: {d['score'][d['p1']]}-{d['score'][d['p2']]}\nПриз: {prize} ⭐")
    active_duels.pop(d_id, None)

# --- ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(m: types.Message, command: CommandObject):
    uid, ref = m.from_user.id, command.args
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (uid, m.from_user.username or "Игрок"))
    if ref and ref.isdigit() and int(ref) != uid:
        cur.execute("UPDATE users SET balance = balance + 1500 WHERE user_id = %s", (int(ref),))
    conn.commit(); cur.close(); conn.close()
    kb = ReplyKeyboardBuilder()
    for b in ["Получить Карту 🏆", "Мини-Игры ⚽", "Магазин 🛒", "Профиль 👤", "Реферальная Система 👥", "ТОП-10 📊"]: kb.button(text=b)
    await m.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(F.text == "Магазин 🛒")
async def open_shop(m: types.Message):
    kb = InlineKeyboardBuilder()
    for p, c in [("Bronze", 4000), ("Gold", 5700), ("Brilliant", 7000)]:
        kb.button(text=f"📦 {p} ({c}⭐)", callback_data=f"buy_{p.lower()}")
    kb.button(text=f"⚡️ VIP 24ч ({VIP_PRICE}⭐)", callback_data="buy_vip")
    await m.answer("🛒 <b>Магазин паков:</b>", reply_markup=kb.adjust(1).as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def shop_buy(c: types.CallbackQuery):
    uid, action = c.from_user.id, c.data.split("_")[1]
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    
    if action == "vip":
        is_v, _ = get_vip_info(uid)
        if is_v: return await c.answer("VIP уже активен!", show_alert=True)
        if u['balance'] < VIP_PRICE: return await c.answer("Недостаточно звезд!", show_alert=True)
        exp = get_now_msk() + timedelta(hours=24)
        cur.execute("UPDATE users SET balance = balance - %s, vip_until = %s WHERE user_id = %s", (VIP_PRICE, exp, uid))
        await c.message.answer("🚀 <b>VIP активирован!</b>")
    else:
        prices = {"bronze": 4000, "gold": 5700, "brilliant": 7000}
        if u['balance'] < prices[action]: return await c.answer("Мало звезд!", show_alert=True)
        card = get_card(action)
        if not card: return await c.answer("Карт нет!", show_alert=True)
        rew = get_stars_by_rating(card['rating'])
        cur.execute("UPDATE users SET balance = balance - %s + %s WHERE user_id = %s", (prices[action], rew, uid))
        cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
        await c.message.reply_photo(photo=card['photo_id'], caption=f"📦 Открыт пак!\n👤 {card['name']}\n📊 {card['rating']}")
    
    conn.commit(); cur.close(); conn.close(); await c.answer()

@dp.message(F.text == "Мини-Игры ⚽")
async def games(m: types.Message):
    kb = InlineKeyboardBuilder().button(text="🔫 PvP Дуэль", callback_data="pvp_info").adjust(1)
    await m.answer("🎯 Выберите режим:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "pvp_info")
async def pvp_info(c: types.CallbackQuery):
    await c.message.edit_text("⚔️ Ответь на сообщение игрока командой <code>/duel</code>\nКД: 40 минут.", 
                             reply_markup=InlineKeyboardBuilder().button(text="Назад", callback_data="start").as_markup())

@dp.message(Command("duel"))
async def cmd_duel(m: types.Message):
    if not m.reply_to_message: return await m.reply("❌ Реплайни сообщение соперника!")
    p1, p2 = m.from_user, m.reply_to_message.from_user
    if p1.id == p2.id: return
    
    now = time.time()
    if p1.id in pvp_cooldowns and now - pvp_cooldowns[p1.id] < 2400:
        return await m.reply("⏳ Твое КД еще не вышло!")
    
    kb = InlineKeyboardBuilder().button(text="Принять ✅", callback_data=f"pvp_acc_{p1.id}").as_markup()
    await m.answer(f"⚽️ {p1.mention_html()} вызывает {p2.mention_html()}!", reply_markup=kb)

@dp.callback_query(F.data.startswith("pvp_acc_"))
async def pvp_acc(c: types.CallbackQuery):
    p1_id = int(c.data.split("_")[2])
    waiting_for_bet[c.from_user.id] = {"type": "pvp", "opponent": p1_id}
    await c.message.edit_text("💰 Введите сумму ставки числом:")

# --- ВЕБ-СЕРВЕР И ЗАПУСК ---
async def handle(r): return web.Response(text="Bot is online")
async def main():
    app = web.Application(); app.router.add_get("/", handle)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
