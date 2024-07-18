# 18 July 18:49

import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get environment variables
API_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
MAIN_ADMIN_ID = int(os.getenv('MAIN_ADMIN_ID'))
DB_NAME = 'attendance_db'

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Initialize MongoDB client
client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

class AttendanceStates(StatesGroup):
    waiting_for_confirmation = State()

class AdminStates(StatesGroup):
    waiting_for_new_admin_id = State()

class WashingMachineStates(StatesGroup):
    waiting_for_status = State()

# Create main menu keyboard
async def get_main_menu_markup(user_id):
    main_menu_markup = InlineKeyboardMarkup()
    main_menu_markup.row(InlineKeyboardButton("Mark Attendance", callback_data="attendance"))
    main_menu_markup.row(InlineKeyboardButton("Washing Machines", callback_data="washing_machines"))
    if await is_admin(user_id):
        main_menu_markup.row(InlineKeyboardButton("Admin Menu", callback_data="admin_menu"))
    return main_menu_markup

# Create admin menu keyboard
admin_menu_markup = InlineKeyboardMarkup()
admin_menu_markup.row(InlineKeyboardButton("Generate Report", callback_data="generate_report"))
admin_menu_markup.row(InlineKeyboardButton("Add Admin", callback_data="add_admin"))
admin_menu_markup.row(InlineKeyboardButton("List Admins", callback_data="list_admins"))
admin_menu_markup.row(InlineKeyboardButton("Back to Main Menu", callback_data="main_menu"))

@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    markup = await get_main_menu_markup(message.from_user.id)
    await message.reply("Welcome! Please select an option:", reply_markup=markup)

@dp.callback_query_handler(lambda c: c.data == 'main_menu')
async def main_menu(callback_query: types.CallbackQuery):
    markup = await get_main_menu_markup(callback_query.from_user.id)
    await callback_query.message.edit_text("Main Menu:", reply_markup=markup)

@dp.callback_query_handler(lambda c: c.data == 'attendance')
async def start_attendance(callback_query: types.CallbackQuery):
    attendance_markup = InlineKeyboardMarkup()
    attendance_markup.row(InlineKeyboardButton("Present", callback_data="present"))
    attendance_markup.row(InlineKeyboardButton("Absent", callback_data="absent"))
    attendance_markup.row(InlineKeyboardButton("I'm late", callback_data="late"))
    await AttendanceStates.waiting_for_confirmation.set()
    await callback_query.message.edit_text("What's your attendance status for today?", reply_markup=attendance_markup)

@dp.callback_query_handler(state=AttendanceStates.waiting_for_confirmation)
async def process_attendance(callback_query: types.CallbackQuery, state: FSMContext):
    status_map = {'present': 'Present', 'absent': 'Absent', 'late': "I'm late"}
    status = status_map.get(callback_query.data)
    
    if not status:
        await callback_query.answer("Invalid option. Please try again.")
        return

    user_id = callback_query.from_user.id
    username = callback_query.from_user.username
    date = datetime.now().strftime("%Y-%m-%d")

    attendance = {
        'user_id': user_id,
        'username': username,
        'date': date,
        'status': status
    }

    await db.attendance.update_one(
        {'user_id': user_id, 'date': date},
        {'$set': attendance},
        upsert=True
    )

    await state.finish()
    await callback_query.message.edit_text(f"Your attendance has been recorded as '{status}'. Thank you!")
    markup = await get_main_menu_markup(user_id)
    await callback_query.message.answer("What would you like to do next?", reply_markup=markup)

async def is_admin(user_id: int) -> bool:
    admin = await db.admins.find_one({'user_id': user_id})
    return admin is not None

@dp.callback_query_handler(lambda c: c.data == 'admin_menu')
async def admin_menu(callback_query: types.CallbackQuery):
    if not await is_admin(callback_query.from_user.id):
        await callback_query.answer("Sorry, only admins can access this menu.")
        return
    await callback_query.message.edit_text("Admin Menu:", reply_markup=admin_menu_markup)

@dp.callback_query_handler(lambda c: c.data == 'generate_report')
async def send_report(callback_query: types.CallbackQuery):
    if not await is_admin(callback_query.from_user.id):
        await callback_query.answer("Sorry, only admins can access the attendance report.")
        return

    date = datetime.now().strftime("%Y-%m-%d")
    cursor = db.attendance.find({'date': date})
    report = f"Attendance Report for {date}:\n\n"

    present_list = []
    absent_list = []
    late_list = []

    async for doc in cursor:
        status = doc.get('status', 'Unknown')
        username = doc.get('username', 'Unknown')
        user_id = doc.get('user_id', 'Unknown')

        if status == 'Present':
            present_list.append(f"- {username} (ID: {user_id})")
        elif status == 'Absent':
            absent_list.append(f"- {username} (ID: {user_id})")
        elif status == "I'm late":
            late_list.append(f"- {username} (ID: {user_id})")

    report += "Present:\n" + "\n".join(present_list) + f"\n\nTotal Present: {len(present_list)}\n\n"
    report += "Absent:\n" + "\n".join(absent_list) + f"\n\nTotal Absent: {len(absent_list)}\n\n"
    report += "Late:\n" + "\n".join(late_list) + f"\n\nTotal Late: {len(late_list)}"

    await callback_query.message.answer(report)
    await callback_query.message.answer("Admin Menu:", reply_markup=admin_menu_markup)

@dp.callback_query_handler(lambda c: c.data == 'add_admin')
async def start_add_admin(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != MAIN_ADMIN_ID:
        await callback_query.answer("Sorry, only the main admin can add new admins.")
        return

    await AdminStates.waiting_for_new_admin_id.set()
    await callback_query.message.edit_text("Please enter the user ID of the new admin.")

@dp.message_handler(state=AdminStates.waiting_for_new_admin_id)
async def process_new_admin(message: types.Message, state: FSMContext):
    try:
        new_admin_id = int(message.text)
    except ValueError:
        await message.reply("Please enter a valid user ID (numbers only).")
        return

    await db.admins.update_one(
        {'user_id': new_admin_id},
        {'$set': {'user_id': new_admin_id}},
        upsert=True
    )

    await state.finish()
    await message.reply(f"User with ID {new_admin_id} has been added as an admin.")
    await message.answer("Admin Menu:", reply_markup=admin_menu_markup)

@dp.callback_query_handler(lambda c: c.data == 'list_admins')
async def list_admins(callback_query: types.CallbackQuery):
    if not await is_admin(callback_query.from_user.id):
        await callback_query.answer("Sorry, only admins can view the list of admins.")
        return

    cursor = db.admins.find()
    admin_list = ["Admin List:\n"]
    async for doc in cursor:
        admin_list.append(f"- User ID: {doc['user_id']}")

    await callback_query.message.answer("\n".join(admin_list))
    await callback_query.message.answer("Admin Menu:", reply_markup=admin_menu_markup)

@dp.callback_query_handler(lambda c: c.data == 'washing_machines')
async def washing_machines_menu(callback_query: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Check Availability", callback_data="check_washing_machines"))
    keyboard.add(InlineKeyboardButton("Update Status", callback_data="update_washing_machines"))
    keyboard.add(InlineKeyboardButton("Back to Main Menu", callback_data="main_menu"))
    await callback_query.message.edit_text("Washing Machines Menu:", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data == 'check_washing_machines')
async def check_washing_machines(callback_query: types.CallbackQuery):
    washing_machines = await db.washing_machines.find_one({'_id': 'status'})
    if washing_machines and 'available' in washing_machines:
        status = "available" if washing_machines['available'] else "not available"
        updated_by = washing_machines.get('updated_by', 'Unknown')
        updated_at = washing_machines.get('updated_at', 'Unknown time')
        message = f"Washing machines are currently {status}.\nLast updated by: {updated_by}\nLast updated at: {updated_at}"
    else:
        message = "No information available about washing machines."
    await callback_query.answer()
    await callback_query.message.answer(message)
    await callback_query.message.answer("Washing Machines Menu:", reply_markup=callback_query.message.reply_markup)

@dp.callback_query_handler(lambda c: c.data == 'update_washing_machines')
async def update_washing_machines(callback_query: types.CallbackQuery):
    await WashingMachineStates.waiting_for_status.set()
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Available", callback_data="washing_available"))
    keyboard.add(InlineKeyboardButton("Not Available", callback_data="washing_not_available"))
    await callback_query.answer()
    await callback_query.message.edit_text("Are the washing machines available?", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith('washing_'), state=WashingMachineStates.waiting_for_status)
async def process_washing_machine_status(callback_query: types.CallbackQuery, state: FSMContext):
    status = callback_query.data == 'washing_available'
    await db.washing_machines.update_one(
        {'_id': 'status'},
        {'$set': {
            'available': status,
            'updated_by': callback_query.from_user.username,
            'updated_at': datetime.now()
        }},
        upsert=True
    )
    await state.finish()
    await callback_query.answer("Thank you for updating the washing machine status!")
    status_text = "available" if status else "not available"
    await callback_query.message.edit_text(f"Washing machines are now marked as {status_text}.")
    await callback_query.message.answer("Washing Machines Menu:", reply_markup=callback_query.message.reply_markup)

async def main():
    # Ensure main admin is in the database
    await db.admins.update_one(
        {'user_id': MAIN_ADMIN_ID},
        {'$set': {'user_id': MAIN_ADMIN_ID}},
        upsert=True
    )
    await dp.start_polling()

if __name__ == '__main__':
    asyncio.run(main())