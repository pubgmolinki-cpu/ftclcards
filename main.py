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

# Глобальные состояния
cooldowns, pvp_cooldowns, guess_cooldowns = {}, {}, {}
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
    """)
    conn.commit(); cur.close(); conn.close()

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

async def check_sub(uid):
    for ch in CHANNELS:
        try:
            m = await bot.get_chat_member(ch, uid)
            if m.status not in ["member", "administrator", "creator"]: return False
        except: return False
    return True

# --- СИСТЕМА КОМАНДЫ ---
def auto_collect_team(user_id):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT c.id, c.name, c.rating, c.position FROM user_cards uc JOIN all_cards c ON uc.card_id = c.id WHERE uc.user_id = %s", (user_id,))
        cards = cur.fetchall()
        if len(cards) < 11: return False, "❌ Нужно минимум 11 карт!"
        pos_map = {"Вратарь": [], "Защитник": [], "Полузащитник": [], "Нападающий": []}
        for c in cards:
            if c['position'] in pos_map: pos_map[c['position']].append(c)
        if len(pos_map["Вратарь"]) < 1 or len(pos_map["Защитник"]) < 4 or len(pos_map["Полузащитник"]) < 3 or len(pos_map["Нападающий"]) < 3:
            return False, "❌ Не хватает игроков на позиции (1 GK, 4 DEF, 3 MID, 3 FWD)!"
        gk = sorted(pos_map["Вратарь"], key=lambda x: x['rating'], reverse=True)[0]
        defs = sorted(pos_map["Защитник"], key=lambda x: x['rating'], reverse=True)[:4]
        mids = sorted(pos_map["Полузащитник"], key=lambda x: x['rating'], reverse=True)[:3]
        fwds = sorted(pos_map["Нападающий"], key=lambda x: x['rating'], reverse=True)[:3]
        cur.execute("INSERT INTO active_teams (user_id, gk_id, def_ids, mid_ids, fwd_ids) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET gk_id=EXCLUDED.gk_id, def_ids=EXCLUDED.def_ids, mid_ids=EXCLUDED.mid_ids, fwd_ids=EXCLUDED.fwd_ids", (user_id, gk['id'], [d['id'] for d in defs], [m['id'] for m in mids], [f['id'] for f in fwds]))
        conn.commit(); return True, "✅ Состав 4-3-3 собран!"
    finally: cur.close(); conn.close()

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (message.from_user.id, message.from_user.username))
    conn.commit(); cur.close(); conn.close()
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Рефералка 👥"); kb.button(text="ТОП-10 📊")
    await message.answer("⚽️ <b>FTCL Cards приветствует тебя!</b>", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(F.text == "Профиль 👤")
async def profile_menu(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (message.from_user.id,))
    u = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id = %s", (message.from_user.id,))
    cnt = cur.fetchone()[0]
    kb = InlineKeyboardBuilder()
    kb.button(text="🛡 Моя Команда", callback_data="my_team")
    kb.button(text="💼 Моя Коллекция", callback_data="my_collection")
    await message.answer(f"👤 <b>Профиль:</b> @{message.from_user.username}\n💰 Баланс: <b>{u['balance']}</b> ⭐\n🗂 Карт: <b>{cnt}</b>", reply_markup=kb.adjust(1).as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data == "my_team")
async def show_team(callback: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM active_teams WHERE user_id = %s", (callback.from_user.id,))
    t = cur.fetchone()
    if not t: text = "❌ Команда не собрана."
    else:
        ids = [t['gk_id']] + t['def_ids'] + t['mid_ids'] + t['fwd_ids']
        cur.execute("SELECT name, rating, position FROM all_cards WHERE id = ANY(%s)", (ids,))
        text = "🛡 <b>Твой состав 4-3-3:</b>\n\n" + "\n".join([f"• {c['position']}: <b>{c['name']}</b> ({c['rating']})" for c in cur.fetchall()])
    kb = InlineKeyboardBuilder().button(text="🔄 Авто-Сбор", callback_data="auto_collect")
    await callback.message.answer(text, reply_markup=kb.as_markup()); await callback.answer()
    cur.close(); conn.close()

@dp.callback_query(F.data == "auto_collect")
async def handle_collect(callback: types.CallbackQuery):
    ok, msg = auto_collect_team(callback.from_user.id)
    await callback.answer(msg, show_alert=True)

# --- PvP МАТЧ ---

@dp.message(Command("match"))
async def match_cmd(message: types.Message, command: CommandObject):
    if not command.args or not command.args.isdigit(): return await message.answer("❌ /match 1000")
    bet = int(command.args); uid = message.from_user.id
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    cur.execute("SELECT 1 FROM active_teams WHERE user_id = %s", (uid,))
    if not cur.fetchone(): return await message.answer("❌ Собери команду в Профиле!")
    if u['balance'] < bet: return await message.answer("❌ Мало ⭐")
    
    m_id = f"{uid}_{int(time.time())}"
    active_matches[m_id] = {"p1": uid, "p1_name": message.from_user.full_name, "p2": None, "bet": bet, "round": 1, "score": [0,0]}
    kb = InlineKeyboardBuilder().button(text=f"Принять ({bet} ⭐)", callback_data=f"join_{m_id}")
    await message.answer(f"🏟 <b>{message.from_user.full_name}</b> зовет на матч!\n💰 Ставка: <b>{bet}</b> ⭐", reply_markup=kb.as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data.startswith("join_"))
async def join_p(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]; m = active_matches.get(m_id)
    uid = callback.from_user.id
    if not m or m['p2']: return await callback.answer("Уже занято!")
    if uid == m['p1']: return await callback.answer("С собой нельзя!")
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    cur.execute("SELECT 1 FROM active_teams WHERE user_id = %s", (uid,))
    if not cur.fetchone() or u['balance'] < m['bet']: 
        return await callback.answer("Ошибка: нет состава или ⭐", show_alert=True)

    cur.execute("UPDATE users SET balance = balance - %s WHERE user_id IN (%s, %s)", (m['bet'], m['p1'], uid))
    conn.commit(); cur.close(); conn.close()
    
    m['p2'] = uid; m['p2_name'] = callback.from_user.full_name
    kb = InlineKeyboardBuilder().button(text="🤜 Атаковать!", callback_data=f"kick_{m_id}")
    await callback.message.edit_text(f"⚽️ <b>Матч начался!</b>\n\n{m['p1_name']} 🆚 {m['p2_name']}", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("kick_"))
async def kick_p(callback: types.CallbackQuery):
    await callback.answer() # Сразу убираем состояние загрузки
    m_id = callback.data.split("_", 1)[1]; m = active_matches.get(m_id)
    if not m: return

    # Кто атакует в этом раунде
    atk_id = m['p1'] if m['round'] % 2 != 0 else m['p2']
    def_id = m['p2'] if m['round'] % 2 != 0 else m['p1']
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    try:
        cur.execute("SELECT fwd_ids FROM active_teams WHERE user_id = %s", (atk_id,))
        a_ids = cur.fetchone()['fwd_ids']
        cur.execute("SELECT def_ids FROM active_teams WHERE user_id = %s", (def_id,))
        d_ids = cur.fetchone()['def_ids']

        cur.execute("SELECT name, rating FROM all_cards WHERE id = %s", (random.choice(a_ids),))
        atk_p = cur.fetchone()
        cur.execute("SELECT name, rating FROM all_cards WHERE id = %s", (random.choice(d_ids),))
        def_p = cur.fetchone()

        goal = random.randint(1, 100) <= (50 + (atk_p['rating'] - def_p['rating']))
        if goal:
            if atk_id == m['p1']: m['score'][0] += 1
            else: m['score'][1] += 1
        
        icon = "🟢" if goal else "🔴"
        event = f"{icon} <b>{atk_p['name']}</b> атакует... " + ("ГОЛ!" if goal else "Защита {0} справилась!".format(def_p['name']))
        m['round'] += 1
        
        if m['round'] > 5:
            win_id = m['p1'] if m['score'][0] > m['score'][1] else (m['p2'] if m['score'][1] > m['score'][0] else None)
            bank = m['bet'] * 2
            if win_id: cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bank, win_id))
            else: cur.execute("UPDATE users SET balance = balance + %s WHERE user_id IN (%s, %s)", (m['bet'], m['p1'], m['p2']))
            conn.commit()
            await callback.message.edit_text(f"🏁 <b>ИТОГ: {m['score'][0]}:{m['score'][1]}</b>\nПобедил: <b>{m['p1_name'] if win_id == m['p1'] else (m['p2_name'] if win_id else 'Ничья')}</b>")
            active_matches.pop(m_id, None)
        else:
            kb = InlineKeyboardBuilder().button(text="🤜 Следующий момент", callback_data=f"kick_{m_id}")
            await callback.message.edit_text(f"⚽ Раунд {m['round']-1}/5\n\n{event}\n\n📊 Счёт <b>{m['score'][0]}:{m['score'][1]}</b>", reply_markup=kb.as_markup())
    finally: cur.close(); conn.close()

# --- ОСТАЛЬНОЕ ---
@dp.message(F.text == "Мини-Игры ⚽")
async def games_menu(message: types.Message):
    kb = InlineKeyboardBuilder().button(text="⚔️ PvP Матч", callback_data="pvp_info")
    await message.answer("🎮 Игры:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "pvp_info")
async def p_inf(callback: types.CallbackQuery):
    await callback.message.answer("⚔️ Напиши <code>/match [ставка]</code> в чате!"); await callback.answer()

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
