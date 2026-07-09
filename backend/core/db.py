import os
from motor.motor_asyncio import AsyncIOMotorClient

client = AsyncIOMotorClient(os.environ["MONGO_URL"], maxPoolSize=25)
db = client[os.environ["DB_NAME"]]
