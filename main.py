import asyncio
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

# Библиотека для календаря
from aiogram_calendar import SimpleCalendar, SimpleCalendarCallback

# --- 1. НАСТРОЙКИ ---
API_TOKEN = '8727948676:AAHlEPiOj_lnL5va6FUfVq2DoaxkEhNvsBk'

ADMIN_PASSWORD = "мойпароль"   
VIEWER_PASSWORD = "отчет"  

CATEGORIES = ["🥤 Напитки", "🥨 Снэки", "🍫 Шоколад"]
STAFF_CATEGORIES = ["🥤 Напитки", "🍔 Еда"]
CONSUMPTION_TYPES = ["Съели кассиры", "Брак", "По сроку"]

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- 2. СОСТОЯНИЯ (FSM) ---
class AuthStates(StatesGroup):
    waiting_for_password = State()

class BotStates(StatesGroup):
    adding_prod_name = State(); adding_prod_cat = State(); deleting_prod = State()
    moving_machine = State(); moving_cat = State(); moving_prod = State(); moving_qty = State()
    inv_machine = State(); inv_cat = State(); inv_prod = State(); inv_qty = State()
    report_choosing_machine = State(); report_choosing_month = State()
    waiting_for_detailed_date = State()

class StaffStates(StatesGroup):
    adding_staff_name = State(); adding_staff_cat = State()
    consuming_cat = State(); consuming_prod = State(); consuming_type = State(); consuming_qty = State()

# --- 3. БАЗА ДАННЫХ ---
def init_db():
    with sqlite3.connect('vending.db') as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS authorized_users (user_id INTEGER PRIMARY KEY, role TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS movements (id INTEGER PRIMARY KEY AUTOINCREMENT, machine_id INTEGER, item_name TEXT, quantity INTEGER, date TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE, category TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, machine_id INTEGER, item_name TEXT, quantity INTEGER, timestamp TEXT, month_year TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS staff_products (name TEXT UNIQUE, category TEXT)')
        conn.execute('''CREATE TABLE IF NOT EXISTS staff_consumption 
                        (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, item_name TEXT, 
                         eaten INTEGER DEFAULT 0, defect INTEGER DEFAULT 0, expired INTEGER DEFAULT 0, added_by INTEGER)''')
        conn.commit()

def get_user_role(user_id):
    with sqlite3.connect('vending.db') as conn:
        res = conn.execute('SELECT role FROM authorized_users WHERE user_id = ?', (user_id,)).fetchone()
    return res[0] if res else None

# --- 4. ВСПОМОГАТЕЛЬНЫЕ КЛАВИАТУРЫ ---
def ikb_main(role):
    kb = []
    if role == "admin":
        kb.append([InlineKeyboardButton(text="🍽 Учёт цехового питания", callback_data="menu_staff_root")])
        kb.append([InlineKeyboardButton(text="📥 Перемещение", callback_data="menu_move"), 
                   InlineKeyboardButton(text="📋 Инвентаризация", callback_data="menu_inv")])
        kb.append([InlineKeyboardButton(text="⚙️ Управление товарами", callback_data="menu_manage")])
    else:
        kb.append([InlineKeyboardButton(text="🍽 Отчёт по цеховому", callback_data="staff_rep_months")])
    
    kb.append([InlineKeyboardButton(text="📊 Отчеты", callback_data="menu_rep_root")])
    kb.append([InlineKeyboardButton(text="📈 ПОДРОБНЫЙ ОТЧЕТ", callback_data="menu_det_rep")])
    kb.append([InlineKeyboardButton(text="🚪 Выйти", callback_data="logout")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def ikb_machines(prefix):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Аппарат 1", callback_data=f"{prefix}_1"), InlineKeyboardButton(text="Аппарат 2", callback_data=f"{prefix}_2")],
        [InlineKeyboardButton(text="Аппарат 3", callback_data=f"{prefix}_3"), InlineKeyboardButton(text="Аппарат 4", callback_data=f"{prefix}_4")],
        [InlineKeyboardButton(text="Аппарат 5", callback_data=f"{prefix}_5")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])

def ikb_back_only():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_main")]])

# --- 5. ВХОД И ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def start_cmd(msg: types.Message, state: FSMContext):
    await state.clear()
    role = get_user_role(msg.from_user.id)
    if role: await show_main_menu(msg, msg.from_user.id, state)
    else:
        await msg.answer("🔐 Введите пароль доступа:")
        await state.set_state(AuthStates.waiting_for_password)

@dp.message(AuthStates.waiting_for_password)
async def auth_check(msg: types.Message, state: FSMContext):
    role = "admin" if msg.text == ADMIN_PASSWORD else "viewer" if msg.text == VIEWER_PASSWORD else None
    if role:
        with sqlite3.connect('vending.db') as conn:
            conn.execute('INSERT OR REPLACE INTO authorized_users (user_id, role) VALUES (?, ?)', (msg.from_user.id, role))
        await msg.delete()
        await show_main_menu(msg, msg.from_user.id, state)
    else: await msg.answer("❌ Пароль не подходит.")

async def show_main_menu(msg_or_call, user_id, state: FSMContext, edit=False):
    await state.clear()
    role = get_user_role(user_id)
    text = f"👤 **МЕНЮ: {'АДМИНИСТРАТОР' if role=='admin' else 'ПРОСМОТР ОТЧЕТОВ'}**"
    kb = ikb_main(role)
    if edit: await msg_or_call.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    else: await msg_or_call.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "back_main")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_main_menu(call.message, call.from_user.id, state, edit=True)
    await call.answer()

@dp.callback_query(F.data == "logout")
async def logout(call: CallbackQuery, state: FSMContext):
    with sqlite3.connect('vending.db') as conn:
        conn.execute('DELETE FROM authorized_users WHERE user_id = ?', (call.from_user.id,))
    await call.message.edit_text("🚪 Вы вышли. Нажмите /start для входа.")
    await state.clear()
    await call.answer()

# --- 6. ПЕРЕМЕЩЕНИЕ И ИНВЕНТАРИЗАЦИЯ (ЦИКЛИЧНОСТЬ) ---
@dp.callback_query(F.data == "menu_move")
async def move_start(call: CallbackQuery):
    await call.message.edit_text("📥 **ПЕРЕМЕЩЕНИЕ**\nВыберите аппарат:", reply_markup=ikb_machines("movemac"))
    await call.answer()

@dp.callback_query(F.data.startswith("movemac_"))
async def move_select_cat(call: CallbackQuery, state: FSMContext):
    m_id = call.data.split("_")[1]
    await state.update_data(m_id=m_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"mcat_{i}")] for i, c in enumerate(CATEGORIES)] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]])
    await call.message.edit_text(f"🤖 Аппарат {m_id}\nВыберите категорию:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("mcat_"))
async def move_select_prod(call: CallbackQuery, state: FSMContext):
    cat_idx = int(call.data.split("_")[1])
    cat_name = CATEGORIES[cat_idx]
    await state.update_data(cat_name=cat_name, cat_idx=cat_idx)
    with sqlite3.connect('vending.db') as conn:
        prods = conn.execute('SELECT name FROM products WHERE category = ?', (cat_name,)).fetchall()
    if not prods: return await call.answer("Нет товаров!", show_alert=True)
    kb = [[InlineKeyboardButton(text=p[0], callback_data=f"mprod_{p[0]}")] for p in prods]
    kb.append([InlineKeyboardButton(text="📁 Другая категория", callback_data=f"movemac_{(await state.get_data())['m_id']}")])
    await call.message.edit_text(f"📦 {cat_name}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@dp.callback_query(F.data.startswith("mprod_"))
async def move_get_qty(call: CallbackQuery, state: FSMContext):
    await state.update_data(p_name=call.data.replace("mprod_", ""))
    await call.message.edit_text(f"🔢 Введите количество для **{call.data.replace('mprod_', '')}**:", parse_mode="Markdown")
    await state.set_state(BotStates.moving_qty)
    await call.answer()

@dp.message(BotStates.moving_qty)
async def move_finish(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit(): return await msg.answer("Введите число!")
    data = await state.get_data()
    with sqlite3.connect('vending.db') as conn:
        conn.execute('INSERT INTO movements (machine_id, item_name, quantity, date) VALUES (?,?,?,?)',
                     (data['m_id'], data['p_name'], int(msg.text), datetime.now().strftime("%Y-%m-%d")))
    await bot.delete_message(msg.chat.id, msg.message_id - 1)
    await msg.delete()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить ещё товар сюда", callback_data=f"mcat_{data['cat_idx']}")],
        [InlineKeyboardButton(text="📁 Другая категория", callback_data=f"movemac_{data['m_id']}")],
        [InlineKeyboardButton(text="✅ Завершить", callback_data="back_main")]
    ])
    await msg.answer(f"✅ Добавлено: {data['p_name']} ({msg.text} шт.)", reply_markup=kb)
    await state.set_state(None)

# Инвентаризация
@dp.callback_query(F.data == "menu_inv")
async def inv_start(call: CallbackQuery):
    await call.message.edit_text("📋 **ИНВЕНТАРИЗАЦИЯ**\nВыберите аппарат:", reply_markup=ikb_machines("invmac"))
    await call.answer()

@dp.callback_query(F.data.startswith("invmac_"))
async def inv_select_cat(call: CallbackQuery, state: FSMContext):
    m_id = call.data.split("_")[1]
    await state.update_data(m_id=m_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"icat_{i}")] for i, c in enumerate(CATEGORIES)] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]])
    await call.message.edit_text(f"📋 Аппарат {m_id}\nКатегория:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("icat_"))
async def inv_select_prod(call: CallbackQuery, state: FSMContext):
    cat_idx = int(call.data.split("_")[1])
    cat_name = CATEGORIES[cat_idx]
    await state.update_data(cat_name=cat_name, cat_idx=cat_idx)
    with sqlite3.connect('vending.db') as conn:
        prods = conn.execute('SELECT name FROM products WHERE category = ?', (cat_name,)).fetchall()
    kb = [[InlineKeyboardButton(text=p[0], callback_data=f"iprod_{p[0]}")] for p in prods]
    kb.append([InlineKeyboardButton(text="📁 Сменить категорию", callback_data=f"invmac_{(await state.get_data())['m_id']}")])
    await call.message.edit_text(f"🔍 Сверка {cat_name}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@dp.callback_query(F.data.startswith("iprod_"))
async def inv_get_qty(call: CallbackQuery, state: FSMContext):
    await state.update_data(p_name=call.data.replace("iprod_", ""))
    await call.message.edit_text(f"🔢 Остаток **{call.data.replace('iprod_', '')}**:", parse_mode="Markdown")
    await state.set_state(BotStates.inv_qty)
    await call.answer()

@dp.message(BotStates.inv_qty)
async def inv_finish(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit(): return await msg.answer("Введите число!")
    data = await state.get_data()
    with sqlite3.connect('vending.db') as conn:
        conn.execute('INSERT INTO inventory (machine_id, item_name, quantity, timestamp, month_year) VALUES (?,?,?,?,?)',
                     (data['m_id'], data['p_name'], int(msg.text), datetime.now().strftime("%d.%m %H:%M"), datetime.now().strftime("%Y-%m")))
    await bot.delete_message(msg.chat.id, msg.message_id - 1)
    await msg.delete()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Посчитать другой товар", callback_data=f"icat_{data['cat_idx']}")],
        [InlineKeyboardButton(text="📁 Другая категория", callback_data=f"invmac_{data['m_id']}")],
        [InlineKeyboardButton(text="✅ Завершить", callback_data="back_main")]
    ])
    await msg.answer(f"✅ Учтено: {data['p_name']} ({msg.text} шт.)", reply_markup=kb)
    await state.set_state(None)

# --- 7. ЦЕХОВОЕ ПИТАНИЕ ---
@dp.callback_query(F.data == "menu_staff_root")
async def staff_admin_menu(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить товар (Цех)", callback_data="staff_add_p")],
        [InlineKeyboardButton(text="📝 Записать списание", callback_data="staff_cons_start")],
        [InlineKeyboardButton(text="📊 Отчет по цеховому", callback_data="staff_rep_months")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])
    await call.message.edit_text("🍽 **УПРАВЛЕНИЕ ЦЕХОМ**", reply_markup=kb, parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "staff_add_p")
async def staff_add_init(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите название нового товара для цеха:")
    await state.set_state(StaffStates.adding_staff_name)
    await call.answer()

@dp.message(StaffStates.adding_staff_name)
async def staff_add_name_get(msg: types.Message, state: FSMContext):
    await state.update_data(s_name=msg.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"sac_{i}")] for i, c in enumerate(STAFF_CATEGORIES)])
    await msg.answer(f"Выберите категорию для '{msg.text}':", reply_markup=kb)
    await state.set_state(StaffStates.adding_staff_cat)

@dp.callback_query(F.data.startswith("sac_"))
async def staff_add_final(call: CallbackQuery, state: FSMContext):
    cat = STAFF_CATEGORIES[int(call.data.split("_")[1])]
    data = await state.get_data()
    with sqlite3.connect('vending.db') as conn:
        conn.execute('INSERT OR REPLACE INTO staff_products VALUES (?,?)', (data['s_name'], cat))
    await call.message.edit_text(f"✅ Товар '{data['s_name']}' добавлен в цех ({cat}).", reply_markup=ikb_back_only())
    await state.clear()
    await call.answer()

@dp.callback_query(F.data == "staff_cons_start")
async def staff_cons_cat(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"scat_{i}")] for i, c in enumerate(STAFF_CATEGORIES)] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_staff_root")]])
    await call.message.edit_text("Категория (Цех):", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("scat_"))
async def staff_cons_prod(call: CallbackQuery):
    cat = STAFF_CATEGORIES[int(call.data.split("_")[1])]
    with sqlite3.connect('vending.db') as conn:
        prods = conn.execute('SELECT name FROM staff_products WHERE category = ?', (cat,)).fetchall()
    if not prods: return await call.answer("Пусто!")
    kb = [[InlineKeyboardButton(text=p[0], callback_data=f"sprod_{p[0]}")] for p in prods]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="staff_cons_start")])
    await call.message.edit_text(f"Товар ({cat}):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@dp.callback_query(F.data.startswith("sprod_"))
async def staff_cons_type(call: CallbackQuery, state: FSMContext):
    await state.update_data(p_name=call.data.replace("sprod_", ""))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=f"stype_{i}")] for i, t in enumerate(CONSUMPTION_TYPES)] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="staff_cons_start")]])
    await call.message.edit_text("Причина:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("stype_"))
async def staff_cons_qty(call: CallbackQuery, state: FSMContext):
    await state.update_data(t_idx=int(call.data.split("_")[1]))
    await call.message.edit_text("Количество:")
    await state.set_state(StaffStates.consuming_qty)
    await call.answer()

@dp.message(StaffStates.consuming_qty)
async def staff_cons_finish(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit(): return await msg.answer("Число!")
    data = await state.get_data()
    qty = int(msg.text)
    eaten, defect, expired = (qty if data['t_idx'] == 0 else 0, qty if data['t_idx'] == 1 else 0, qty if data['t_idx'] == 2 else 0)
    with sqlite3.connect('vending.db') as conn:
        conn.execute('INSERT INTO staff_consumption (date, item_name, eaten, defect, expired, added_by) VALUES (?,?,?,?,?,?)',
                     (datetime.now().strftime("%Y-%m-%d"), data['p_name'], eaten, defect, expired, msg.from_user.id))
    await bot.delete_message(msg.chat.id, msg.message_id - 1)
    await msg.delete()
    await msg.answer(f"✅ Списано: {data['p_name']} ({qty} шт.)", reply_markup=ikb_back_only())
    await state.clear()

# --- 8. ОТЧЕТЫ (ЗДЕСЬ БЫЛА ГЛАВНАЯ ОШИБКА) ---
@dp.callback_query(F.data == "staff_rep_months")
async def staff_rep_months(call: CallbackQuery):
    with sqlite3.connect('vending.db') as conn:
        months = conn.execute('SELECT DISTINCT strftime("%Y-%m", date) FROM staff_consumption').fetchall()
    if not months: return await call.answer("Нет данных!", show_alert=True)
    kb = [[InlineKeyboardButton(text=f"🗓 {m[0]}", callback_data=f"smonth_{m[0]}")] for m in months]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])
    await call.message.edit_text("Выберите месяц:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@dp.callback_query(F.data.startswith("smonth_"))
async def staff_rep_show(call: CallbackQuery):
    month = call.data.split("_")[1]
    with sqlite3.connect('vending.db') as conn:
        data = conn.execute('SELECT date, item_name, eaten, defect, expired FROM staff_consumption WHERE date LIKE ? ORDER BY date DESC', (f"{month}%",)).fetchall()
    if not data: return await call.answer("Пусто")
    report = f"🍽 **ОТЧЕТ ПО ЦЕХУ: {month}**\n"
    curr_d = None
    for d, name, e, df, ex in data:
        if d != curr_d: report += f"\n📅 **{d}**\n"; curr_d = d
        res = []
        if e > 0: res.append(f"Съели: {e}")
        if df > 0: res.append(f"Брак: {df}")
        if ex > 0: res.append(f"Срок: {ex}")
        report += f"🔹 {name} — {', '.join(res)}\n"
    await call.message.edit_text(report, reply_markup=ikb_back_only(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "menu_rep_root")
async def rep_root(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Отчет перемещений", callback_data="rt_move")],
        [InlineKeyboardButton(text="📋 Отчет инвентаризации", callback_data="rt_inv")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])
    await call.message.edit_text("Выберите отчет:", reply_markup=kb)
    await call.answer()

# === ИСПРАВЛЕНИЕ: БЛОК ОТЧЕТА ПО ПЕРЕМЕЩЕНИЯМ ===
@dp.callback_query(F.data == "rt_move")
async def rep_move_start(call: CallbackQuery, state: FSMContext):
    await state.update_data(rtype="move")
    await call.message.edit_text("📦 Выберите аппарат для отчета перемещений:", reply_markup=ikb_machines("rmac"))
    await call.answer()

@dp.callback_query(F.data.startswith("rmac_"))
async def rep_move_months(call: CallbackQuery, state: FSMContext):
    m_id = call.data.split("_")[1]
    await state.update_data(m_id=m_id)
    with sqlite3.connect('vending.db') as conn:
        months = conn.execute('SELECT DISTINCT strftime("%Y-%m", date) FROM movements WHERE machine_id = ?', (m_id,)).fetchall()
    if not months: return await call.answer("Нет данных за этот период!", show_alert=True)
    kb = [[InlineKeyboardButton(text=m[0], callback_data=f"f_rep_{m[0]}")] for m in months]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_rep_root")])
    await call.message.edit_text(f"Аппарат {m_id}. Выберите месяц:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.set_state(BotStates.report_choosing_month)
    await call.answer()

@dp.callback_query(F.data == "rt_inv")
async def rep_inv_all(call: CallbackQuery, state: FSMContext):
    await state.update_data(rtype="inv")
    with sqlite3.connect('vending.db') as conn:
        months = conn.execute('SELECT DISTINCT month_year FROM inventory').fetchall()
    if not months: return await call.answer("Нет данных!")
    kb = [[InlineKeyboardButton(text=m[0], callback_data=f"f_rep_{m[0]}")] for m in months]
    await call.message.edit_text("Инвентаризация за:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.set_state(BotStates.report_choosing_month)
    await call.answer()

@dp.callback_query(F.data.startswith("f_rep_"))
async def rep_final(call: CallbackQuery, state: FSMContext):
    month = call.data.split("_")[2]
    data = await state.get_data()
    with sqlite3.connect('vending.db') as conn:
        if data.get('rtype') == 'inv':
            res = conn.execute('SELECT machine_id, item_name, quantity, timestamp FROM inventory WHERE month_year = ? ORDER BY machine_id', (month,)).fetchall()
            rep = f"📋 **ИНВЕНТАРКА: {month}**\n"
            curr = None
            for m_id, item, qty, ts in res:
                if m_id != curr: rep += f"\n🤖 **Аппарат {m_id}:**\n"; curr = m_id
                rep += f" ├ {item}: {qty} шт. ({ts})\n"
            await call.message.edit_text(rep, reply_markup=ikb_back_only(), parse_mode="Markdown")
        else: # ИСПРАВЛЕНИЕ ЛОГИКИ ПЕРЕМЕЩЕНИЙ
            res = conn.execute('SELECT item_name, SUM(quantity) FROM movements WHERE machine_id = ? AND date LIKE ? GROUP BY item_name', (data.get('m_id'), f"{month}%")).fetchall()
            rep = f"📦 **ПЕРЕМЕЩЕНИЯ: Аппарат {data.get('m_id')} ({month})**\n\n"
            for r in res:
                rep += f"• {r[0]}: {r[1]} шт.\n"
            await call.message.edit_text(rep, reply_markup=ikb_back_only(), parse_mode="Markdown")
    await call.answer()

# === ИСПРАВЛЕНИЕ: БЛОК ПОДРОБНОГО ОТЧЕТА (КАЛЕНДАРЬ) ===
@dp.callback_query(F.data == "menu_det_rep")
async def det_rep_start(call: CallbackQuery, state: FSMContext):
    # Инициализация календаря
    await call.message.edit_text("📅 Выберите дату для подробного отчета:", reply_markup=await SimpleCalendar().start_calendar())
    await state.set_state(BotStates.waiting_for_detailed_date)
    await call.answer()

@dp.callback_query(SimpleCalendarCallback.filter(), BotStates.waiting_for_detailed_date)
async def det_rep_finish(call: CallbackQuery, callback_data: SimpleCalendarCallback, state: FSMContext):
    # ОБЯЗАТЕЛЬНО: гасим индикатор загрузки сразу
    await call.answer()
    
    selected, date = await SimpleCalendar().process_selection(call, callback_data)
    if selected:
        f_date = date.strftime("%Y-%m-%d")
        with sqlite3.connect('vending.db') as conn:
            data = conn.execute('SELECT machine_id, item_name, quantity FROM movements WHERE date = ? ORDER BY machine_id', (f_date,)).fetchall()
        
        if not data:
            await call.message.edit_text(f"📭 Записей на {f_date} нет.", reply_markup=ikb_back_only())
        else:
            rep = f"📈 **ОТЧЕТ ЗА {f_date}**\n"
            curr = None
            for m_id, item, qty in data:
                if m_id != curr: rep += f"\n🤖 **Аппарат {m_id}:**\n"; curr = m_id
                rep += f" ├ {item}: {qty} шт.\n"
            await call.message.edit_text(rep, reply_markup=ikb_back_only(), parse_mode="Markdown")
        await state.clear()

# --- 9. УПРАВЛЕНИЕ АССОРТИМЕНТОМ ---
@dp.callback_query(F.data == "menu_manage")
async def mng_root(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="mng_add")],
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data="mng_del")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])
    await call.message.edit_text("⚙️ Управление:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data == "mng_add")
async def mng_add_name(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Название товара:")
    await state.set_state(BotStates.adding_prod_name)
    await call.answer()

@dp.message(BotStates.adding_prod_name)
async def mng_add_cat(msg: types.Message, state: FSMContext):
    await state.update_data(name=msg.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"ac_{i}")] for i, c in enumerate(CATEGORIES)])
    await msg.answer(f"Категория для {msg.text}:", reply_markup=kb)
    await state.set_state(BotStates.adding_prod_cat)

@dp.callback_query(F.data.startswith("ac_"))
async def mng_add_fin(call: CallbackQuery, state: FSMContext):
    cat = CATEGORIES[int(call.data.split("_")[1])]
    data = await state.get_data()
    with sqlite3.connect('vending.db') as conn:
        conn.execute('INSERT OR REPLACE INTO products VALUES (?,?)', (data['name'], cat))
    await call.message.edit_text(f"✅ {data['name']} добавлен.", reply_markup=ikb_back_only())
    await state.clear()
    await call.answer()

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
