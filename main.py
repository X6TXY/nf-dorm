import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get environment variables
API_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID'))
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

# Create keyboard markup
attendance_markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
attendance_markup.add(KeyboardButton("Present"), KeyboardButton("Absent"))

@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    await message.reply("Welcome! Use /attendance to mark your attendance for today.")

@dp.message_handler(commands=['attendance'])
async def start_attendance(message: types.Message):
    await AttendanceStates.waiting_for_confirmation.set()
    await message.reply("Are you present today?", reply_markup=attendance_markup)

@dp.message_handler(state=AttendanceStates.waiting_for_confirmation)
async def process_attendance(message: types.Message, state: FSMContext):
    if message.text not in ['Present', 'Absent']:
        await message.reply("Please use the provided buttons to respond.")
        return

    user_id = message.from_user.id
    username = message.from_user.username
    is_present = message.text == 'Present'
    date = datetime.now().strftime("%Y-%m-%d")

    attendance = {
        'user_id': user_id,
        'username': username,
        'date': date,
        'is_present': is_present
    }

    await db.attendance.update_one(
        {'user_id': user_id, 'date': date},
        {'$set': attendance},
        upsert=True
    )

    await state.finish()
    await message.reply("Your attendance has been recorded. Thank you!", reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(commands=['report'])
async def send_report(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.reply("Sorry, only admins can access the attendance report.")
        return

    date = datetime.now().strftime("%Y-%m-%d")
    cursor = db.attendance.find({'date': date})
    report = f"Attendance Report for {date}:\n\n"

    present_count = 0
    absent_count = 0

    async for doc in cursor:
        status = "Present" if doc['is_present'] else "Absent"
        report += f"User: {doc['username']} (ID: {doc['user_id']}) - {status}\n"
        if doc['is_present']:
            present_count += 1
        else:
            absent_count += 1

    report += f"\nSummary:\nPresent: {present_count}\nAbsent: {absent_count}"

    await message.reply(report)

async def main():
    await dp.start_polling()

if __name__ == '__main__':
    asyncio.run(main())