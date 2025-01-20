import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

mongo_client = None

def connect_mongo():
    global mongo_client
    mongo_uri = os.getenv("MONGO_URI")
    mongo_client = AsyncIOMotorClient(mongo_uri)
    print("Connected to MongoDB")

def get_db():
    return mongo_client["doctor_db"]
