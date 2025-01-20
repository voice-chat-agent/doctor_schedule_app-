import os
import asyncio
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

logging.basicConfig(level=logging.DEBUG)
load_dotenv()

async def test_connection():
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        print("MONGO_URI not found in environment variables.")
        return
    print(f"Using MONGO_URI: {mongo_uri}")

    try:
        # Pass tls and tlsAllowInvalidCertificates parameters explicitly
        client = AsyncIOMotorClient(
            mongo_uri,
            tls=True,
            tlsAllowInvalidCertificates=True
        )
        db = client["doctor_db"]
        result = await db.command("ping")
        print("Ping result:", result)
    except Exception as e:
        print("Exception occurred during connection:", e)

if __name__ == "__main__":
    asyncio.run(test_connection())
