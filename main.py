import asyncio
import logging
import aiosqlite # ИЗМЕНЕНО: Асинхронная работа с БД
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

from dotenv import load_dotenv

load_dotenv()
from aiogram_calendar import SimpleCalendar, SimpleCalendarCallback

# --- 1. НАСТРОЙКИ ---
API_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_PASSWORD = os.getenv('ADMIN_PASS')   
VIEWER_PASSWORD = os.getenv('VIEWER_PASS')  

if not API_TOKEN:
    raise ValueError("❌ ОШИБКА: Токен бота не найден! Укажите BOT_TOKEN.")

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
    adding_prod_name = State()
    adding_prod_cat = State()
    moving_qty = State()
    inv_qty = State()

class StaffStates(StatesGroup):
    adding_staff_name = State()
    adding_staff_cat = State()
    consuming_qty = State()

# --- 3. БАЗА ДАННЫХ (Теперь Асинхронная) ---
async def init_db():
    async with aiosqlite.connect('vending.db') as conn:
        await conn.execute('CREATE TABLE IF NOT EXISTS authorized_users (user_id INTEGER PRIMARY KEY, role TEXT)')
        await conn.execute('CREATE TABLE IF NOT EXISTS movements (id INTEGER PRIMARY KEY AUTOINCREMENT, machine_id INTEGER, item_name TEXT, quantity INTEGER, date TEXT)')
        await conn.execute('CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE, category TEXT)')
        await conn.execute('CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, machine_id INTEGER, item_name TEXT, quantity INTEGER, timestamp TEXT, month_year TEXT)')
        await conn.execute('CREATE TABLE IF NOT EXISTS staff_products (name TEXT UNIQUE, category TEXT)')
        await conn.execute('''CREATE TABLE IF NOT EXISTS staff_consumption 
                        (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, item_name TEXT, 
                         eaten INTEGER DEFAULT 0, defect INTEGER DEFAULT 0, expired INTEGER DEFAULT 0, added_by INTEGER)''')
        await conn.commit()

async def get_user_role(user_id):
    async with aiosqlite.connect('vending.db') as conn:
        cursor = await conn.execute('SELECT role FROM authorized_users WHERE user_id = ?', (user_id,))
        res = await cursor.fetchone()
    return res[0] if res else None

# --- 4. КЛАВИАТУРЫ ---
def ikb_main(role):
    kb = []
    if role == "admin":
        kb.append([InlineKeyboardButton(text="🍽 Учёт цехового питания", callback_data="menu_staff_root")])
        kb.append([InlineKeyboardButton(text="📥 Перемещение", callback_data="menu_move"), 
                   InlineKeyboardButton(text="📋 Инвентаризация", callback_data="menu_inv")])
        kb.append([InlineKeyboardButton(text="⚙️ Управление товарами", callback_data="menu_manage")])
    else:
        kb.append([InlineKeyboardButton(text="🍽 Отчёт по цеховому", callback_data="staff_rep_months")])
    
    kb.append([InlineKeyboardButton(text="📊 Отчеты по аппаратам", callback_data="menu_rep_root")])
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
    role = await get_user_role(msg.from_user.id)
    if role: 
        await show_main_menu(msg, msg.from_user.id, state)
    else:
        await msg.answer("🔐 Введите пароль доступа:")
        await state.set_state(AuthStates.waiting_for_password)

@dp.message(AuthStates.waiting_for_password)
async def auth_check(msg: types.Message, state: FSMContext):
    role = "admin" if msg.text == ADMIN_PASSWORD else "viewer" if msg.text == VIEWER_PASSWORD else None
    if role:
        async with aiosqlite.connect('vending.db') as conn:
            await conn.execute('INSERT OR REPLACE INTO authorized_users (user_id, role) VALUES (?, ?)', (msg.from_user.id, role))
            await conn.commit()
        await msg.delete()
        await show_main_menu(msg, msg.from_user.id, state)
    else: 
        await msg.answer("❌ Пароль не подходит.")

@dp.message(Command("get_db"))
async def send_db_file(msg: types.Message):
    role = await get_user_role(msg.from_user.id)
    if role == "admin":
        if os.path.exists('vending.db'):
            await msg.answer_document(FSInputFile('vending.db'), caption="📦 Актуальный файл базы данных.")
        else:
            await msg.answer("❌ Файл базы данных не найден.")
    else:
        await msg.answer("⛔️ У вас нет прав для выполнения этой команды.")

async def show_main_menu(msg_or_call, user_id, state: FSMContext, edit=False):
    await state.clear()
    role = await get_user_role(user_id)
    text = f"👤 **МЕНЮ: {'АДМИНИСТРАТОР' if role=='admin' else 'ПРОСМОТР ОТЧЕТОВ'}**"
    kb = ikb_main(role)
    if edit: 
        await msg_or_call.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    else: 
        await msg_or_call.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "back_main")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_main_menu(call.message, call.from_user.id, state, edit=True)
    await call.answer()

@dp.callback_query(F.data == "logout")
async def logout(call: CallbackQuery, state: FSMContext):
    async with aiosqlite.connect('vending.db') as conn:
        await conn.execute('DELETE FROM authorized_users WHERE user_id = ?', (call.from_user.id,))
        await conn.commit()
    await call.message.edit_text("🚪 Вы вышли. Нажмите /start для входа.")
    await state.clear()
    await call.answer()

# --- 6. ПЕРЕМЕЩЕНИЕ И ИНВЕНТАРИЗАЦИЯ ---
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
    async with aiosqlite.connect('vending.db') as conn:
        cursor = await conn.execute('SELECT name FROM products WHERE category = ?', (cat_name,))
        prods = await cursor.fetchall()
    if not prods: 
        return await call.answer("Нет товаров в этой категории!", show_alert=True)
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
    if not msg.text.isdigit(): 
        return await msg.answer("Введите число!")
    data = await state.get_data()
    async with aiosqlite.connect('vending.db') as conn:
        await conn.execute('INSERT INTO movements (machine_id, item_name, quantity, date) VALUES (?,?,?,?)',
                     (data['m_id'], data['p_name'], int(msg.text), datetime.now().strftime("%Y-%m-%d")))
        await conn.commit()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ещё товар сюда", callback_data=f"mcat_{data['cat_idx']}")],
        [InlineKeyboardButton(text="📁 Другая категория", callback_data=f"movemac_{data['m_id']}")],
        [InlineKeyboardButton(text="✅ Завершить", callback_data="back_main")]
    ])
    await msg.answer(f"✅ Добавлено: {data['p_name']} ({msg.text} шт.)", reply_markup=kb)
    await state.set_state(None)

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
    async with aiosqlite.connect('vending.db') as conn:
        cursor = await conn.execute('SELECT name FROM products WHERE category = ?', (cat_name,))
        prods = await cursor.fetchall()
    if not prods:
        return await call.answer("Нет товаров!", show_alert=True)
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
    if not msg.text.isdigit(): 
        return await msg.answer("Введите число!")
    data = await state.get_data()
    async with aiosqlite.connect('vending.db') as conn:
        await conn.execute('INSERT INTO inventory (machine_id, item_name, quantity, timestamp, month_year) VALUES (?,?,?,?,?)',
                     (data['m_id'], data['p_name'], int(msg.text), datetime.now().strftime("%d.%m %H:%M"), datetime.now().strftime("%Y-%m")))
        await conn.commit()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Посчитать другой", callback_data=f"icat_{data['cat_idx']}")],
        [InlineKeyboardButton(text="✅ Завершить", callback_data="back_main")]
    ])
    await msg.answer(f"✅ Учтено: {data['p_name']} ({msg.text} шт.)", reply_markup=kb)
    await state.set_state(None)

# --- 7. ОТЧЕТЫ ПО АППАРАТАМ ---
@dp.callback_query(F.data == "menu_rep_root")
async def rep_root(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Отчет перемещений", callback_data="rt_move")],
        [InlineKeyboardButton(text="📋 Отчет инвентаризации", callback_data="rt_inv")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])
    await call.message.edit_text("Выберите отчет:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data == "rt_move")
async def rep_move_start(call: CallbackQuery):
    await call.message.edit_text("📦 Выберите аппарат:", reply_markup=ikb_machines("rmac"))
    await call.answer()

@dp.callback_query(F.data.startswith("rmac_"))
async def rep_move_months(call: CallbackQuery, state: FSMContext):
    m_id = call.data.split("_")[1]
    await state.update_data(m_id=m_id, rtype="move")
    async with aiosqlite.connect('vending.db') as conn:
        cursor = await conn.execute('SELECT DISTINCT strftime("%Y-%m", date) FROM movements WHERE machine_id = ?', (m_id,))
        months = await cursor.fetchall()
    if not months: 
        return await call.answer("Нет данных!", show_alert=True)
    kb = [[InlineKeyboardButton(text=m[0], callback_data=f"f_rep_{m[0]}")] for m in months]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_rep_root")])
    await call.message.edit_text(f"Аппарат {m_id}. Месяц:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@dp.callback_query(F.data == "rt_inv")
async def rep_inv_months(call: CallbackQuery, state: FSMContext):
    await state.update_data(rtype="inv")
    async with aiosqlite.connect('vending.db') as conn:
        cursor = await conn.execute('SELECT DISTINCT month_year FROM inventory')
        months = await cursor.fetchall()
    if not months: 
        return await call.answer("Нет данных!", show_alert=True)
    kb = [[InlineKeyboardButton(text=m[0], callback_data=f"f_rep_{m[0]}")] for m in months]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_rep_root")])
    await call.message.edit_text("Инвентаризация за месяц:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@dp.callback_query(F.data.startswith("f_rep_"))
async def rep_final(call: CallbackQuery, state: FSMContext):
    month = call.data.split("_")[2]
    data = await state.get_data()
    rep = ""
    async with aiosqlite.connect('vending.db') as conn:
        if data.get('rtype') == 'inv':
            cursor = await conn.execute('SELECT machine_id, item_name, quantity, timestamp FROM inventory WHERE month_year = ? ORDER BY machine_id', (month,))
            res = await cursor.fetchall()
            rep = f"📋 **ИНВЕНТАРКА: {month}**\n"
            curr = None
            for m_id, item, qty, ts in res:
                if m_id != curr: 
                    rep += f"\n🤖 **Аппарат {m_id}:**\n"
                    curr = m_id
                rep += f" ├ {item}: {qty} шт. ({ts})\n"
        else:
            cursor = await conn.execute('SELECT item_name, SUM(quantity) FROM movements WHERE machine_id = ? AND date LIKE ? GROUP BY item_name', (data.get('m_id'), f"{month}%"))
            res = await cursor.fetchall()
            rep = f"📦 **ПЕРЕМЕЩЕНИЯ: Аппарат {data.get('m_id')} ({month})**\n\n"
            for r in res: 
                rep += f"• {r[0]}: {r[1]} шт.\n"
    
    await call.message.edit_text(rep or "Данные не найдены", reply_markup=ikb_back_only(), parse_mode="Markdown")
    await call.answer()

# --- 8. ПОДРОБНЫЙ ОТЧЕТ (КАЛЕНДАРЬ) ---
@dp.callback_query(F.data == "menu_det_rep")
async def det_rep_start(call: CallbackQuery):
    await call.message.edit_text("📅 Выберите дату:", reply_markup=await SimpleCalendar().start_calendar())
    await call.answer()

@dp.callback_query(SimpleCalendarCallback.filter())
async def det_rep_finish(call: CallbackQuery, callback_data: SimpleCalendarCallback):
    selected, date = await SimpleCalendar().process_selection(call, callback_data)
    if selected:
        f_date = date.strftime("%Y-%m-%d")
        async with aiosqlite.connect('vending.db') as conn:
            cursor = await conn.execute('SELECT machine_id, item_name, quantity FROM movements WHERE date = ? ORDER BY machine_id', (f_date,))
            data = await cursor.fetchall()
        if not data: 
            await call.message.edit_text(f"📭 На {f_date} записей нет.", reply_markup=ikb_back_only())
        else:
            rep = f"📈 **ОТЧЕТ ЗА {f_date}**\n"
            curr = None
            for m_id, item, qty in data:
                if m_id != curr: 
                    rep += f"\n🤖 **Аппарат {m_id}:**\n"
                    curr = m_id
                rep += f" ├ {item}: {qty} шт.\n"
            await call.message.edit_text(rep, reply_markup=ikb_back_only(), parse_mode="Markdown")
    await call.answer()

# --- 9. УПРАВЛЕНИЕ ТОВАРАМИ (ДОБАВЛЕНИЕ И УДАЛЕНИЕ) ---
@dp.callback_query(F.data == "menu_manage")
async def mng_root(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="mng_add")],
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data="mng_del")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])
    await call.message.edit_text("⚙️ **УПРАВЛЕНИЕ АССОРТИМЕНТОМ**", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data == "mng_add")
async def mng_add_name(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите название нового товара:")
    await state.set_state(BotStates.adding_prod_name)
    await call.answer()

@dp.message(BotStates.adding_prod_name)
async def mng_add_cat(msg: types.Message, state: FSMContext):
    await state.update_data(name=msg.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"ac_{i}")] for i, c in enumerate(CATEGORIES)])
    await msg.answer(f"Выберите категорию для '{msg.text}':", reply_markup=kb)
    await state.set_state(BotStates.adding_prod_cat)

@dp.callback_query(F.data.startswith("ac_"))
async def mng_add_fin(call: CallbackQuery, state: FSMContext):
    cat = CATEGORIES[int(call.data.split("_")[1])]
    data = await state.get_data()
    async with aiosqlite.connect('vending.db') as conn:
        await conn.execute('INSERT OR REPLACE INTO products VALUES (?,?)', (data.get('name', 'Без имени'), cat))
        await conn.commit()
    
    # ИСПРАВЛЕНИЕ: Автоматически возвращаем в меню управления
    await call.answer(f"✅ Товар '{data.get('name')}' добавлен!", show_alert=True)
    await state.clear()
    await mng_root(call)

@dp.callback_query(F.data == "mng_del")
async def mng_del_start(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"dc_{i}")] for i, c in enumerate(CATEGORIES)] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_manage")]])
    await call.message.edit_text("🗑 Из какой категории удалить товар?", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("dc_"))
async def mng_del_list(call: CallbackQuery):
    cat_idx = int(call.data.split("_")[1])
    cat_name = CATEGORIES[cat_idx]
    async with aiosqlite.connect('vending.db') as conn:
        cursor = await conn.execute('SELECT name FROM products WHERE category = ?', (cat_name,))
        prods = await cursor.fetchall()
    if not prods: 
        return await call.answer("Категория пуста!", show_alert=True)
    kb = [[InlineKeyboardButton(text=f"❌ {p[0]}", callback_data=f"delp_{p[0]}")] for p in prods]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mng_del")])
    await call.message.edit_text(f"Выберите товар для удаления из {cat_name}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@dp.callback_query(F.data.startswith("delp_"))
async def mng_del_fin(call: CallbackQuery):
    p_name = call.data.replace("delp_", "")
    async with aiosqlite.connect('vending.db') as conn:
        await conn.execute('DELETE FROM products WHERE name = ?', (p_name,))
        await conn.commit()
    await call.answer(f"Товар {p_name} удален")
    await mng_del_start(call)

# --- 10. ЦЕХОВОЕ ПИТАНИЕ ---
@dp.callback_query(F.data == "menu_staff_root")
async def staff_root(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить товар (цех)", callback_data="st_add")],
        [InlineKeyboardButton(text="📉 Списание (Учет)", callback_data="st_cons")],
        [InlineKeyboardButton(text="📊 Отчеты по цеху", callback_data="staff_rep_months")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])
    await call.message.edit_text("🍽 **ЦЕХОВОЕ ПИТАНИЕ**", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data == "st_add")
async def staff_add_name(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Название товара для цеха:")
    await state.set_state(StaffStates.adding_staff_name)
    await call.answer()

@dp.message(StaffStates.adding_staff_name)
async def staff_add_cat(msg: types.Message, state: FSMContext):
    await state.update_data(name=msg.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"sac_{i}")] for i, c in enumerate(STAFF_CATEGORIES)])
    await msg.answer("Категория для цехового товара:", reply_markup=kb)
    await state.set_state(StaffStates.adding_staff_cat)

@dp.callback_query(F.data.startswith("sac_"))
async def staff_add_fin(call: CallbackQuery, state: FSMContext):
    cat_idx = int(call.data.split("_")[1])
    cat = STAFF_CATEGORIES[cat_idx]
    data = await state.get_data()
    async with aiosqlite.connect('vending.db') as conn:
        await conn.execute('INSERT OR REPLACE INTO staff_products VALUES (?,?)', (data.get('name', 'Без имени'), cat))
        await conn.commit()
    
    # ИСПРАВЛЕНИЕ: Автоматически возвращаем в меню цеха
    await call.answer(f"✅ {data.get('name')} добавлен!", show_alert=True)
    await state.clear()
    await staff_root(call)

@dp.callback_query(F.data == "st_cons")
async def staff_cons_cat(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"scc_{i}")] for i, c in enumerate(STAFF_CATEGORIES)] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_staff_root")]])
    await call.message.edit_text("Выберите категорию для списания:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("scc_"))
async def staff_cons_prod(call: CallbackQuery, state: FSMContext):
    cat = STAFF_CATEGORIES[int(call.data.split("_")[1])]
    async with aiosqlite.connect('vending.db') as conn:
        cursor = await conn.execute('SELECT name FROM staff_products WHERE category = ?', (cat,))
        prods = await cursor.fetchall()
    if not prods: 
        return await call.answer("Нет товаров!", show_alert=True)
    kb = [[InlineKeyboardButton(text=p[0], callback_data=f"scp_{p[0]}")] for p in prods]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="st_cons")])
    await call.message.edit_text(f"Что списываем ({cat})?", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@dp.callback_query(F.data.startswith("scp_"))
async def staff_cons_type(call: CallbackQuery, state: FSMContext):
    await state.update_data(p_name=call.data.replace("scp_", ""))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=f"sctype_{i}")] for i, t in enumerate(CONSUMPTION_TYPES)] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="st_cons")]])
    await call.message.edit_text("Причина списания:", reply_markup=kb)
    await call.answer()

@dp.callback_query(F.data.startswith("sctype_"))
async def staff_cons_qty(call: CallbackQuery, state: FSMContext):
    await state.update_data(ctype=int(call.data.split("_")[1]))
    data = await state.get_data()
    await call.message.edit_text(f"Введите количество для **{data['p_name']}**:", parse_mode="Markdown")
    await state.set_state(StaffStates.consuming_qty)
    await call.answer()

@dp.message(StaffStates.consuming_qty)
async def staff_cons_finish(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit(): 
        return await msg.answer("Введите число!")
    data = await state.get_data()
    date = datetime.now().strftime("%Y-%m-%d")
    qty = int(msg.text)
    col = "eaten" if data['ctype'] == 0 else "defect" if data['ctype'] == 1 else "expired"
    
    async with aiosqlite.connect('vending.db') as conn:
        await conn.execute(f'INSERT INTO staff_consumption (date, item_name, {col}, added_by) VALUES (?,?,?,?)', (date, data['p_name'], qty, msg.from_user.id))
        await conn.commit()
    
    await msg.answer(f"✅ Учтено: {data['p_name']} — {qty} шт.", reply_markup=ikb_back_only())
    await state.clear()

@dp.callback_query(F.data == "staff_rep_months")
async def staff_rep_months(call: CallbackQuery):
    async with aiosqlite.connect('vending.db') as conn:
        cursor = await conn.execute('SELECT DISTINCT strftime("%Y-%m", date) FROM staff_consumption')
        months = await cursor.fetchall()
    if not months: 
        return await call.answer("Нет данных!", show_alert=True)
    kb = [[InlineKeyboardButton(text=m[0], callback_data=f"strm_{m[0]}")] for m in months]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")])
    await call.message.edit_text("Отчет по цеху. Месяц:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@dp.callback_query(F.data.startswith("strm_"))
async def staff_rep_days(call: CallbackQuery):
    month = call.data.split("_")[1]
    async with aiosqlite.connect('vending.db') as conn:
        cursor = await conn.execute('SELECT DISTINCT date FROM staff_consumption WHERE date LIKE ?', (f"{month}%",))
        days = await cursor.fetchall()
    kb = [[InlineKeyboardButton(text=d[0], callback_data=f"strd_{d[0]}")] for d in days]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="staff_rep_months")])
    await call.message.edit_text(f"День ({month}):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await call.answer()

@dp.callback_query(F.data.startswith("strd_"))
async def staff_rep_final(call: CallbackQuery):
    date = call.data.split("_")[1]
    async with aiosqlite.connect('vending.db') as conn:
        cursor = await conn.execute('SELECT item_name, SUM(eaten), SUM(defect), SUM(expired) FROM staff_consumption WHERE date = ? GROUP BY item_name', (date,))
        res = await cursor.fetchall()
    rep = f"🍽 **ОТЧЕТ ЦЕХ: {date}**\n\n"
    for r in res:
        rep += f"🔸 **{r[0]}**\n   └ Кассиры: {r[1]} | Брак: {r[2]} | Срок: {r[3]}\n"
    await call.message.edit_text(rep or "Нет данных", reply_markup=ikb_back_only(), parse_mode="Markdown")
    await call.answer()

# --- 11. ЗАПУСК ---
async def main():
    await init_db()
    # ИСПРАВЛЕНИЕ: Очищаем очередь старых кликов, чтобы не было ошибки Flood Limit при старте!
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

