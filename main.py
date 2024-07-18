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

# Create keyboard markup
attendance_markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
attendance_markup.add(KeyboardButton("Present"), KeyboardButton("Absent"), KeyboardButton("I'm late"))

@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    await message.reply("Welcome! Use /attendance to mark your attendance for today. Use /washing_machines to check or update washing machine status.")

@dp.message_handler(commands=['attendance'])
async def start_attendance(message: types.Message):
    await AttendanceStates.waiting_for_confirmation.set()
    await message.reply("What's your attendance status for today?", reply_markup=attendance_markup)

@dp.message_handler(state=AttendanceStates.waiting_for_confirmation)
async def process_attendance(message: types.Message, state: FSMContext):
    if message.text not in ['Present', 'Absent', "I'm late"]:
        await message.reply("Please use the provided buttons to respond.")
        return

    user_id = message.from_user.id
    username = message.from_user.username
    status = message.text
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
    await message.reply(f"Your attendance has been recorded as '{status}'. Thank you!", reply_markup=types.ReplyKeyboardRemove())

async def is_admin(user_id: int) -> bool:
    admin = await db.admins.find_one({'user_id': user_id})
    return admin is not None

@dp.message_handler(commands=['report'])
async def send_report(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Sorry, only admins can access the attendance report.")
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

    await message.reply(report)

@dp.message_handler(commands=['add_admin'])
async def start_add_admin(message: types.Message):
    if message.from_user.id != MAIN_ADMIN_ID:
        await message.reply("Sorry, only the main admin can add new admins.")
        return

    await AdminStates.waiting_for_new_admin_id.set()
    await message.reply("Please enter the user ID of the new admin.")

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

@dp.message_handler(commands=['list_admins'])
async def list_admins(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Sorry, only admins can view the list of admins.")
        return

    cursor = db.admins.find()
    admin_list = ["Admin List:\n"]
    async for doc in cursor:
        admin_list.append(f"- User ID: {doc['user_id']}")

    await message.reply("\n".join(admin_list))

@dp.message_handler(commands=['washing_machines'])
async def washing_machines_menu(message: types.Message):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Check Availability", callback_data="check_washing_machines"))
    keyboard.add(InlineKeyboardButton("Update Status", callback_data="update_washing_machines"))
    await message.reply("Washing Machines Menu:", reply_markup=keyboard)

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
    await callback_query.message.reply(message)

@dp.callback_query_handler(lambda c: c.data == 'update_washing_machines')
async def update_washing_machines(callback_query: types.CallbackQuery):
    await WashingMachineStates.waiting_for_status.set()
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Available", callback_data="washing_available"))
    keyboard.add(InlineKeyboardButton("Not Available", callback_data="washing_not_available"))
    await callback_query.answer()
    await callback_query.message.reply("Are the washing machines available?", reply_markup=keyboard)

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
    await callback_query.message.reply(f"Washing machines are now marked as {status_text}.")

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