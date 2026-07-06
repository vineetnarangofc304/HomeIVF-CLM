import asyncio, os, re
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv()

async def main():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    # next id
    top = await db.leads.find_one({}, sort=[("id", -1)])
    nid = (top["id"] if top else 0) + 1
    # pick an existing pipeline lead phone for the dedup test
    dupe = await db.leads.find_one({"phone_digits": {"$exists": True, "$ne": None}, "ozonetel_lead": {"$ne": True}}, {"phone": 1, "phone_digits": 1})
    now = "2026-07-07 05:00:00"
    docs = [
        {"id": nid, "name": "9876500011", "contact_name": "9876500011", "phone": "+919876500011",
         "phone_digits": "9876500011", "source_lead": "Ozonetel Incoming Call", "ozonetel_lead": True,
         "active": True, "create_date": now, "write_date": now, "lead_stage": "New"},
        {"id": nid + 1, "name": "9876500022", "contact_name": "9876500022", "phone": "+919876500022",
         "phone_digits": "9876500022", "source_lead": "Ozonetel Missed Call", "ozonetel_lead": True,
         "active": True, "create_date": now, "write_date": now, "lead_stage": "New"},
    ]
    if dupe and dupe.get("phone_digits"):
        docs.append({"id": nid + 2, "name": dupe["phone_digits"], "contact_name": dupe["phone_digits"],
                     "phone": dupe.get("phone") or dupe["phone_digits"], "phone_digits": dupe["phone_digits"],
                     "source_lead": "Ozonetel Incoming Call", "ozonetel_lead": True, "active": True,
                     "create_date": now, "write_date": now, "lead_stage": "New"})
    await db.leads.insert_many(docs)
    print("Seeded ozonetel leads:", [d["id"] for d in docs], "| dupe phone:", dupe.get("phone_digits") if dupe else None)

asyncio.run(main())
