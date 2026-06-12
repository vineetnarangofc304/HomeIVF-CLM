import os

from dotenv import load_dotenv

load_dotenv()

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.db import db
from core.security import hash_password, verify_password
from core.utils import now_utc_str
from routes import admin as admin_routes
from routes import auth as auth_routes
from routes import catalogs as catalog_routes
from routes import chatter as chatter_routes
from routes import filters as filter_routes
from routes import leads as lead_routes
from routes import reports as report_routes
from routes import templates as template_routes
from routes import users as user_routes
from routes import webhooks as webhook_routes
from routes import whatsapp as whatsapp_routes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="HomeIVF CRM API")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi import APIRouter

api = APIRouter(prefix="/api")
api.include_router(auth_routes.router)
api.include_router(user_routes.router)
api.include_router(lead_routes.router)
api.include_router(chatter_routes.router)
api.include_router(catalog_routes.router)
api.include_router(template_routes.router)
api.include_router(whatsapp_routes.router)
api.include_router(report_routes.router)
api.include_router(webhook_routes.router)
api.include_router(filter_routes.router)
api.include_router(admin_routes.router)


@api.get("/health")
async def health():
    return {"status": "ok", "service": "HomeIVF CRM API", "powered_by": "TagQuest"}


app.include_router(api)

DEFAULT_LEAD_STAGES = ["Contact Attempt", "Contacted", "Converted", "Closed"]
DEFAULT_FOLLOW_UP_TAGS = ["Follow UP 1", "Follow UP 2", "Follow UP 3", "Follow UP 4", "Follow UP 5"]


@app.on_event("startup")
async def startup():
    # Indexes
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.login_attempts.create_index("identifier")
    await db.leads.create_index("id", unique=True)
    await db.leads.create_index([("create_date", -1)])
    await db.leads.create_index([("create_date_ist", -1)])
    await db.leads.create_index([("write_date", -1)])
    await db.leads.create_index("user_id")
    await db.leads.create_index("tags")
    await db.leads.create_index("lead_stage")
    await db.leads.create_index("phone_digits")
    await db.leads.create_index("follow_up_date")
    await db.leads.create_index("active")
    await db.messages.create_index([("lead_id", 1), ("date", -1)])
    await db.messages.create_index("id")
    await db.wa_messages.create_index([("channel_id", 1), ("date", -1)])
    await db.wa_channels.create_index("id", unique=True)
    await db.wa_channels.create_index("phone_digits")
    await db.wa_channels.create_index([("last_message_date", -1)])
    await db.activities.create_index([("user_id", 1), ("state", 1), ("date_deadline", 1)])
    await db.catalogs.create_index([("type", 1), ("id", 1)], unique=True)
    await db.contacts.create_index("id", unique=True)
    await db.webhooks.create_index("token")

    # Seed admin
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_password = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        await db.users.insert_one({
            "id": 1, "email": admin_email, "name": "HomeIVF Admin", "role": "admin",
            "active": True, "password_hash": hash_password(admin_password),
            "created_at": now_utc_str(),
        })
        logger.info("Seeded admin user")
    elif not verify_password(admin_password, existing.get("password_hash", "")):
        await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_password)}})

    # Counter floor for new user ids / lead ids (above odoo ranges)
    await db.counters.update_one({"_id": "user"}, {"$max": {"seq": 1000}}, upsert=True)
    await db.counters.update_one({"_id": "lead"}, {"$max": {"seq": 500000}}, upsert=True)
    await db.counters.update_one({"_id": "message"}, {"$max": {"seq": 5000000}}, upsert=True)
    await db.counters.update_one({"_id": "wa_message"}, {"$max": {"seq": 5000000}}, upsert=True)
    await db.counters.update_one({"_id": "activity"}, {"$max": {"seq": 1000}}, upsert=True)

    # Seed default lead stages / follow-up tags
    for i, name in enumerate(DEFAULT_LEAD_STAGES):
        await db.catalogs.update_one(
            {"type": "lead_stage", "name": name},
            {"$setOnInsert": {"id": i + 1, "type": "lead_stage", "name": name, "sequence": i + 1, "active": True}},
            upsert=True,
        )
    for i, name in enumerate(DEFAULT_FOLLOW_UP_TAGS):
        await db.catalogs.update_one(
            {"type": "follow_up_tag", "name": name},
            {"$setOnInsert": {"id": i + 1, "type": "follow_up_tag", "name": name, "sequence": i + 1, "active": True}},
            upsert=True,
        )
    # Seed default source_lead values
    for i, name in enumerate(["landing_page", "chatbot", "website", "App", "Callback_Request"]):
        await db.catalogs.update_one(
            {"type": "source_lead", "name": name},
            {"$setOnInsert": {"id": i + 1, "type": "source_lead", "name": name, "sequence": i + 1, "active": True}},
            upsert=True,
        )
    # Seed Indian states + countries (Case 1 dropdowns)
    if await db.catalogs.count_documents({"type": "state"}) == 0:
        states = ["Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
                  "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
                  "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
                  "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
                  "Uttarakhand", "West Bengal", "Andaman and Nicobar Islands", "Chandigarh",
                  "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir", "Ladakh",
                  "Lakshadweep", "Puducherry"]
        await db.catalogs.insert_many([
            {"id": i + 1, "type": "state", "name": n, "sequence": i + 1, "active": True}
            for i, n in enumerate(states)])
        await db.counters.update_one({"_id": "catalog_state"}, {"$max": {"seq": len(states) + 1}}, upsert=True)
    if await db.catalogs.count_documents({"type": "country"}) == 0:
        countries = ["India", "Nepal", "Bangladesh", "Sri Lanka", "United Arab Emirates", "Saudi Arabia",
                     "Qatar", "Oman", "Kuwait", "Bahrain", "United States", "United Kingdom", "Canada",
                     "Australia", "Singapore", "Malaysia", "Germany", "France", "Other"]
        await db.catalogs.insert_many([
            {"id": i + 1, "type": "country", "name": n, "sequence": i + 1, "active": True}
            for i, n in enumerate(countries)])
        await db.counters.update_one({"_id": "catalog_country"}, {"$max": {"seq": len(countries) + 1}}, upsert=True)
    logger.info("Startup complete")
