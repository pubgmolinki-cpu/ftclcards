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

# Состояния
cooldowns, pvp_cooldowns = {}, {}
active_matches, waiting_for_bet = {}, {}

# --- ИНИЦИАЛИЗАЦИЯ БД ---
def init_db():
    conn = psycopg2.connect(DATABASE_URL); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 5000,
            is_banned BOOLEAN DEFAULT FALSE
        );
        CREATE TABLE IF NOT EXISTS active_teams (
            user_id BIGINT PRIMARY KEY,
            gk_id INTEGER, def_ids INTEGER[], mid_ids INTEGER[], fwd_ids INTEGER[]
        );
        DO $$ BEGIN 
            ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE;
        EXCEPTION WHEN duplicate_column THEN NULL; END $$;
    """)
    conn.commit(); cur.close(); conn.close()
    print("✅ БД Инициализирована")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# --- АНТИЧИТ И ЛОГИ ---
async def send_log(text):
    try: await bot.send_message(ADMIN_ID, f"📑 <b>LOG:</b>\n{text}")
    except: pass

async def is_user_banned(user_id):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT is_banned FROM users WHERE user_id = %s", (user_id,))
    res = cur.fetchone()
    cur.close(); conn.close()
    return res[0] if res else False

# --- ЛОГИКА АВТОСБОРА ---
def auto_collect_team(user_id):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("""
            SELECT c.id, c.name, c.rating, c.position 
            FROM user_cards uc 
            JOIN all_cards c ON uc.card_id = c.id 
            WHERE uc.user_id = %s
        """, (user_id,))
        cards = cur.fetchall()
        if len(cards) < 11: return False, "Нужно минимум 11 карт!"

        pos_map = {"Вратарь": [], "Защитник": [], "Полузащитник": [], "Нападающий": []}
        for c in cards:
            if c['position'] in pos_map: pos_map[c['position']].append(c)

        if len(pos_map["Вратарь"]) < 1 or len(pos_map["Защитник"]) < 4 or len(pos_map["Полузащитник"]) < 3 or len(pos_map["Нападающий"]) < 3:
            return False, "Не хватает игроков для схемы 4-3-3!"

        gk = sorted(pos_map["Вратарь"], key=lambda x: x['rating'], reverse=True)[0]
        defs = sorted(pos_map["Защитник"], key=lambda x: x['rating'], reverse=True)[:4]
        mids = sorted(pos_map["Полузащитник"], key=lambda x: x['rating'], reverse=True)[:3]
        fwds = sorted(pos_map["Нападающий"], key=lambda x: x['rating'], reverse=True)[:3]

        cur.execute("""
            INSERT INTO active_teams (user_id, gk_id, def_ids, mid_ids, fwd_ids)
            VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET 
            gk_id=EXCLUDED.gk_id, def_ids=EXCLUDED.def_ids, mid_ids=EXCLUDED.mid_ids, fwd_ids=EXCLUDED.fwd_ids
        """, (user_id, gk['id'], [d['id'] for d in defs], [m['id'] for m in mids], [f['id'] for f in fwds]))
        conn.commit(); return True, "Состав 4-3-3 собран!"
    finally: cur.close(); conn.close()

# --- МАТЧИ И РАУНДЫ ---
def get_event_text(atk, dfnd, goal):
    wins = [f"⚽️ <b>{atk}</b> прорвался сквозь защиту и забил!", f"🎯 <b>{atk}</b> бахнул точно в девять!"]
    fails = [f"🧤 <b>{atk}</b> бил сильно, но вратарь вытащил!", f"🛑 <b>{dfnd}</b> заблокировал удар!"]
    return random.choice(wins if goal else fails)

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    uid = message.from_user.id
    ref_id = command.args
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (uid, message.from_user.username))
    if ref_id and ref_id.isdigit() and int(ref_id) != uid:
        cur.execute("UPDATE users SET balance = balance + 1500 WHERE user_id = %s", (int(ref_id),))
    conn.commit(); cur.close(); conn.close()
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Рефералка 👥"); kb.button(text="ТОП-10 📊")
    await message.answer("⚽️ <b>FTCL Cards:</b> Управляй, играй, побеждай!", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (message.from_user.id,))
    u = cur.fetchone()
    await message.answer(f"👤 <b>Профиль</b>\n💰 Баланс: {u['balance']} ⭐\n🆔 ID: <code>{message.from_user.id}</code>")
    cur.close(); conn.close()

@dp.message(F.text == "Мини-Игры ⚽")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder().button(text="⚔️ PvP Матч", callback_data="pvp_info")
    kb.button(text="🛡 Моя Команда", callback_data="my_team").adjust(1)
    await message.answer("🎯 Выберите раздел:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "my_team")
async def show_team(callback: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM active_teams WHERE user_id = %s", (callback.from_user.id,))
    t = cur.fetchone()
    if not t: text = "Команда не собрана."
    else: text = "📋 <b>Ваша Команда 4-3-3:</b>\n<i>Нажмите 'Автосбор', чтобы обновить</i>"
    kb = InlineKeyboardBuilder().button(text="🔄 Автосбор", callback_data="auto_collect")
    await callback.message.edit_text(text, reply_markup=kb.as_markup()); cur.close(); conn.close()

@dp.callback_query(F.data == "auto_collect")
async def handle_collect(callback: types.CallbackQuery):
    ok, msg = auto_collect_team(callback.from_user.id)
    await callback.answer(msg, show_alert=True)
    if ok: await show_team(callback)

@dp.message(Command("match"))
async def start_match_cmd(message: types.Message, command: CommandObject):
    uid = message.from_user.id
    if await is_user_banned(uid): return
    if uid in pvp_cooldowns and time.time() - pvp_cooldowns[uid] < 1800:
        return await message.answer("⏳ КД 30 мин!")
    
    if not command.args or not command.args.isdigit(): return await message.answer("Юзай: /match 1000")
    bet = int(command.args)
    if bet <= 0: 
        await send_log(f"🛑 ЧИТЕР @{message.from_user.username} поставил {bet}!"); return

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    cur.execute("SELECT 1 FROM active_teams WHERE user_id = %s", (uid,))
    if not cur.fetchone(): return await message.answer("❌ Сначала сделай Автосбор в меню Команда!")
    if not u or u['balance'] < bet: return await message.answer("❌ Мало ⭐")
    
    m_id = f"m_{uid}_{int(time.time())}"
    active_matches[m_id] = {"p1": uid, "p1_name": message.from_user.full_name, "p2": None, "bet": bet, "round": 1, "score": [0,0]}
    kb = InlineKeyboardBuilder().button(text=f"Принять ({bet} ⭐)", callback_data=f"join_{m_id}")
    await message.answer(f"🏟 <b>{message.from_user.full_name}</b> зовет на матч!\n💰 Ставка: {bet}", reply_markup=kb.as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data.startswith("join_"))
async def match_join(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]; m = active_matches.get(m_id)
    uid = callback.from_user.id
    if not m or m['p2']: return await callback.answer("Упс, матч занят.")
    if uid == m['p1']: return await callback.answer("С собой нельзя!")
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    cur.execute("SELECT 1 FROM active_teams WHERE user_id = %s", (uid,))
    if not cur.fetchone(): return await callback.answer("Собери команду!", show_alert=True)
    if u['balance'] < m['bet']: return await callback.answer("Нет денег!")

    cur.execute("UPDATE users SET balance = balance - %s WHERE user_id IN (%s, %s)", (m['bet'], m['p1'], uid))
    conn.commit(); cur.close(); conn.close()
    
    m['p2'] = uid; m['p2_name'] = callback.from_user.full_name
    pvp_cooldowns[m['p1']] = pvp_cooldowns[uid] = time.time()
    kb = InlineKeyboardBuilder().button(text="🤜 Атаковать!", callback_data=f"kick_{m_id}")
    await callback.message.edit_text(f"⚽️ <b>Матч начался!</b>\n{m['p1_name']} vs {m['p2_name']}", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("kick_"))
async def match_kick(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]; m = active_matches.get(m_id)
    if not m or callback.from_user.id not in [m['p1'], m['p2']]: return

    atk_id = m['p1'] if m['round'] % 2 != 0 else m['p2']
    def_id = m['p2'] if m['round'] % 2 != 0 else m['p1']
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT name, rating FROM all_cards WHERE id = ANY((SELECT fwd_ids FROM active_teams WHERE user_id = %s)) ORDER BY RANDOM() LIMIT 1", (atk_id,))
    atk_p = cur.fetchone()
    cur.execute("SELECT name, rating FROM all_cards WHERE id = ANY((SELECT def_ids FROM active_teams WHERE user_id = %s)) ORDER BY RANDOM() LIMIT 1", (def_id,))
    def_p = cur.fetchone()

    goal = random.randint(1, 100) <= (50 + (atk_p['rating'] - def_p['rating']))
    if goal:
        if atk_id == m['p1']: m['score'][0] += 1
        else: m['score'][1] += 1
    
    txt = get_event_text(atk_p['name'], def_p['name'], goal)
    m['round'] += 1
    
    if m['round'] > 5:
        win_id = m['p1'] if m['score'][0] > m['score'][1] else (m['p2'] if m['score'][1] > m['score'][0] else None)
        bank = m['bet'] * 2
        if win_id: cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bank, win_id))
        else: cur.execute("UPDATE users SET balance = balance + %s WHERE user_id IN (%s, %s)", (m['bet'], m['p1'], m['p2']))
        conn.commit(); cur.close(); conn.close()
        await callback.message.edit_text(f"🏁 <b>ФИНАЛ: {m['score'][0]}:{m['score'][1]}</b>\nПобедил: {m['p1_name'] if win_id == m['p1'] else (m['p2_name'] if win_id else 'Ничья')}")
        await send_log(f"⚔️ Матч окончен {m['p1_name']} vs {m['p2_name']} | Счёт {m['score'][0]}:{m['score'][1]}")
        active_matches.pop(m_id, None)
    else:
        kb = InlineKeyboardBuilder().button(text="🤜 След. Раунд", callback_data=f"kick_{m_id}")
        await callback.message.edit_text(f"Раунд {m['round']-1}/5\n{txt}\n\n📊 Счёт {m['score'][0]}:{m['score'][1]}", reply_markup=kb.as_markup())
        cur.close(); conn.close()

# --- АДМИНКА ---
@dp.message(Command("ban"))
async def ban(m: types.Message, c: CommandObject):
    if m.from_user.id != ADMIN_ID: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET is_banned = TRUE WHERE user_id = %s", (int(c.args),))
    conn.commit(); cur.close(); conn.close(); await m.answer("Бан выдан.")

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
