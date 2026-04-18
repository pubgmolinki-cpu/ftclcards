import asyncio, psycopg2, os, html, random, time
from datetime import datetime, timedelta
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

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

# Состояния в памяти
cooldowns, active_matches, waiting_for_bet = {}, {}, {}

# --- ИНИЦИАЛИЗАЦИЯ БД ---
def init_db():
    conn = psycopg2.connect(DATABASE_URL); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 5000, is_banned BOOLEAN DEFAULT FALSE
        );
        CREATE TABLE IF NOT EXISTS active_teams (
            user_id BIGINT PRIMARY KEY, gk_id INTEGER, def_ids INTEGER[], mid_ids INTEGER[], fwd_ids INTEGER[]
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

# --- ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username", (message.from_user.id, message.from_user.username))
    conn.commit(); cur.close(); conn.close()
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить Карту 🏆"); kb.button(text="Мини-Игры ⚽")
    kb.button(text="Магазин 🛒"); kb.button(text="Профиль 👤")
    kb.button(text="Рефералка 👥"); kb.button(text="ТОП-10 📊")
    await message.answer("⚽️ <b>FTCL Cards: Твоя футбольная империя!</b>", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

# --- ПРОФИЛЬ И СОСТАВ ---
@dp.message(F.text == "Профиль 👤")
async def profile(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (message.from_user.id,))
    u = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM user_cards WHERE user_id = %s", (message.from_user.id,))
    cnt = cur.fetchone()[0]
    kb = InlineKeyboardBuilder().button(text="🛡 Моя Команда", callback_data="my_team").button(text="💼 Коллекция", callback_data="my_coll")
    await message.answer(f"👤 <b>Профиль:</b> @{message.from_user.username}\n💰 Баланс: <b>{u['balance']:,}</b> ⭐\n🗂 Карт: <b>{cnt}</b>", reply_markup=kb.adjust(1).as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data == "my_team")
async def show_team(callback: types.CallbackQuery):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM active_teams WHERE user_id = %s", (callback.from_user.id,))
    t = cur.fetchone()
    if not t: text = "❌ Состав не собран!"
    else:
        ids = [t['gk_id']] + t['def_ids'] + t['mid_ids'] + t['fwd_ids']
        cur.execute("SELECT name, rating, position FROM all_cards WHERE id = ANY(%s)", (ids,))
        text = "🛡 <b>Твой состав 4-3-3:</b>\n\n" + "\n".join([f"• {c['position']}: <b>{c['name']}</b> ({c['rating']})" for c in cur.fetchall()])
    kb = InlineKeyboardBuilder().button(text="🔄 Авто-Сбор", callback_data="auto_collect")
    await callback.message.edit_text(text, reply_markup=kb.as_markup()); cur.close(); conn.close()

@dp.callback_query(F.data == "auto_collect")
async def auto_collect(callback: types.CallbackQuery):
    uid = callback.from_user.id
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT c.id, c.position, c.rating FROM user_cards uc JOIN all_cards c ON uc.card_id = c.id WHERE uc.user_id = %s", (uid,))
    cards = cur.fetchall()
    if len(cards) < 11: return await callback.answer("❌ Нужно минимум 11 карт!", show_alert=True)
    
    # Упрощенная логика сбора лучших
    pos_map = {"Вратарь": [], "Защитник": [], "Полузащитник": [], "Нападающий": []}
    for c in cards: 
        if c['position'] in pos_map: pos_map[c['position']].append(c)
    
    if len(pos_map["Вратарь"]) < 1 or len(pos_map["Защитник"]) < 4 or len(pos_map["Полузащитник"]) < 3 or len(pos_map["Нападающий"]) < 3:
        return await callback.answer("❌ Не хватает игроков для схемы 4-3-3!", show_alert=True)

    gk = sorted(pos_map["Вратарь"], key=lambda x: x['rating'], reverse=True)[0]
    defs = [c['id'] for c in sorted(pos_map["Защитник"], key=lambda x: x['rating'], reverse=True)[:4]]
    mids = [c['id'] for c in sorted(pos_map["Полузащитник"], key=lambda x: x['rating'], reverse=True)[:3]]
    fwds = [c['id'] for c in sorted(pos_map["Нападающий"], key=lambda x: x['rating'], reverse=True)[:3]]
    
    cur.execute("INSERT INTO active_teams (user_id, gk_id, def_ids, mid_ids, fwd_ids) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET gk_id=EXCLUDED.gk_id, def_ids=EXCLUDED.def_ids, mid_ids=EXCLUDED.mid_ids, fwd_ids=EXCLUDED.fwd_ids", (uid, gk['id'], defs, mids, fwds))
    conn.commit(); cur.close(); conn.close()
    await callback.answer("✅ Лучший состав 4-3-3 собран!", show_alert=True)

# --- PvP ЛОГИКА ---
@dp.message(Command("match"))
async def start_match(message: types.Message, command: CommandObject):
    if not command.args or not command.args.isdigit(): return await message.answer("Введите ставку: /match 1000")
    bet = int(command.args); uid = message.from_user.id
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    if cur.fetchone()['balance'] < bet: return await message.answer("❌ Недостаточно ⭐")
    cur.execute("SELECT 1 FROM active_teams WHERE user_id = %s", (uid,))
    if not cur.fetchone(): return await message.answer("❌ Сначала собери состав в Профиле!")
    
    m_id = f"{uid}_{int(time.time())}"
    active_matches[m_id] = {"p1": uid, "p1_n": message.from_user.full_name, "p2": None, "bet": bet, "round": 1, "score": [0,0]}
    kb = InlineKeyboardBuilder().button(text=f"Принять ({bet} ⭐)", callback_data=f"join_{m_id}")
    await message.answer(f"🏟 <b>{message.from_user.full_name}</b> вызывает на матч!\n💰 Ставка: <b>{bet}</b> ⭐", reply_markup=kb.as_markup())
    cur.close(); conn.close()

@dp.callback_query(F.data.startswith("join_"))
async def join_match(callback: types.CallbackQuery):
    m_id = callback.data.split("_", 1)[1]; m = active_matches.get(m_id)
    uid = callback.from_user.id
    if not m or m['p2'] or uid == m['p1']: return
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (uid,))
    if cur.fetchone()['balance'] < m['bet']: return await callback.answer("❌ Нет денег!", show_alert=True)
    cur.execute("SELECT 1 FROM active_teams WHERE user_id = %s", (uid,))
    if not cur.fetchone(): return await callback.answer("❌ Собери состав!", show_alert=True)
    
    cur.execute("UPDATE users SET balance = balance - %s WHERE user_id IN (%s, %s)", (m['bet'], m['p1'], uid))
    conn.commit(); cur.close(); conn.close()
    
    m['p2'] = uid; m['p2_n'] = callback.from_user.full_name
    kb = InlineKeyboardBuilder().button(text="🤛 Атаковать!", callback_data=f"kick_{m_id}")
    await callback.message.edit_text(f"⚽️ <b>Матч начался!</b>\n{m['p1_n']} 🆚 {m['p2_n']}", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("kick_"))
async def kick_match(callback: types.CallbackQuery):
    await callback.answer()
    m_id = callback.data.split("_", 1)[1]; m = active_matches.get(m_id)
    if not m: return
    
    atk_id = m['p1'] if m['round'] % 2 != 0 else m['p2']
    def_id = m['p2'] if m['round'] % 2 != 0 else m['p1']
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT fwd_ids FROM active_teams WHERE user_id = %s", (atk_id,))
    a_fwd = random.choice(cur.fetchone()['fwd_ids'])
    cur.execute("SELECT def_ids FROM active_teams WHERE user_id = %s", (def_id,))
    d_def = random.choice(cur.fetchone()['def_ids'])
    
    cur.execute("SELECT name, rating FROM all_cards WHERE id = %s", (a_fwd,))
    atk_p = cur.fetchone()
    cur.execute("SELECT name, rating FROM all_cards WHERE id = %s", (d_def,))
    def_p = cur.fetchone()
    
    goal = random.randint(1, 100) <= (50 + (atk_p['rating'] - def_p['rating']))
    if goal:
        if atk_id == m['p1']: m['score'][0] += 1
        else: m['score'][1] += 1
    
    m['round'] += 1
    if m['round'] > 5:
        win_id = m['p1'] if m['score'][0] > m['score'][1] else (m['p2'] if m['score'][1] > m['score'][0] else None)
        if win_id: cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (m['bet']*2, win_id))
        else: cur.execute("UPDATE users SET balance = balance + %s WHERE user_id IN (%s, %s)", (m['bet'], m['p1'], m['p2']))
        conn.commit()
        await callback.message.edit_text(f"🏁 <b>ФИНАЛ: {m['score'][0]}:{m['score'][1]}</b>\nПобедил: <b>{m['p1_n'] if win_id == m['p1'] else (m['p2_n'] if win_id else 'Ничья')}</b>")
        active_matches.pop(m_id, None)
    else:
        kb = InlineKeyboardBuilder().button(text="🤜 Следующий момент", callback_data=f"kick_{m_id}")
        txt = f"⚽ Раунд {m['round']-1}/5\n{'🟢' if goal else '🔴'} <b>{atk_p['name']}</b> против <b>{def_p['name']}</b>... " + ("ГОЛ!" if goal else "СЕЙВ!")
        await callback.message.edit_text(f"{txt}\n\n📊 Счёт: <b>{m['score'][0]}:{m['score'][1]}</b>", reply_markup=kb.as_markup())
    cur.close(); conn.close()

# --- ПОЛУЧЕНИЕ КАРТЫ (ОПЕНИНГ) ---
@dp.message(F.text == "Получить Карту 🏆")
async def give_card(message: types.Message):
    uid = message.from_user.id
    if not await check_sub(uid): return await message.answer("❌ Подпишись на каналы!")
    now = time.time()
    if uid in cooldowns and now - cooldowns[uid] < 14400:
        rem = int(14400 - (now - cooldowns[uid]))
        return await message.answer(f"⏳ Жди {rem//3600}ч. {(rem%3600)//60}м.")
    
    msg = await message.answer("⏳ <i>Распаковка пака...</i>")
    await asyncio.sleep(2)
    
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT * FROM all_cards ORDER BY RANDOM() LIMIT 1")
    card = cur.fetchone()
    cooldowns[uid] = now
    cur.execute("UPDATE users SET balance = balance + 1000 WHERE user_id = %s", (uid,))
    cur.execute("INSERT INTO user_cards (user_id, card_id) VALUES (%s, %s)", (uid, card['id']))
    conn.commit(); cur.close(); conn.close()
    
    await msg.delete()
    await message.answer_photo(card['photo_id'], caption=f"🎉 <b>НОВАЯ КАРТА!</b>\n\n👤 <b>{card['name']}</b> ({card['rating']})\n🛡 {card['club']}\n\n💰 Награда: <b>+1,000 ⭐</b>")

# --- МАГАЗИН И ТОП ---
@dp.message(F.text == "Магазин 🛒")
async def shop(message: types.Message):
    kb = InlineKeyboardBuilder().button(text="🎫 Пак (5,000 ⭐)", callback_data="buy_5000")
    await message.answer("🛒 <b>Магазин паков:</b>", reply_markup=kb.as_markup())

@dp.message(F.text == "ТОП-10 📊")
async def top10(message: types.Message):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    res = cur.fetchall()
    txt = "🏆 <b>ТОП-10 ИГРОКОВ:</b>\n\n" + "\n".join([f"{i+1}. {r[0]} — {r[1]:,} ⭐" for i, r in enumerate(res)])
    await message.answer(txt); cur.close(); conn.close()

async def main():
    init_db(); await bot.delete_webhook(drop_pending_updates=True); await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
