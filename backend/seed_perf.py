import os, random, datetime, pymongo

c = pymongo.MongoClient(os.environ["MONGO_URL"])
db = c[os.environ["DB_NAME"]]

callers = [u["id"] for u in db.users.find({"active": True, "role": "caller"}, {"_id": 0, "id": 1})]
if not callers:
    callers = [1001]
stages = ["New / Unassigned", "Contact Attempt", "Contacted", "Converted", "Closed"]
sources = ["Website", "Meta Lead Ads", "landing_page", "chatbot", "App"]
cities = ["Delhi", "Mumbai", "Bangalore", "Chennai", "Pune", "Hyderabad", "Kolkata"]

N = 120000
BATCH = 5000
base = datetime.datetime(2024, 1, 1)
start_id = 600000
batch = []
inserted = 0
for i in range(N):
    lid = start_id + i
    dt = base + datetime.timedelta(minutes=random.randint(0, 900000))
    ds = dt.strftime("%Y-%m-%d %H:%M:%S")
    ist = (dt + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    doc = {
        "id": lid, "active": True, "type": "lead", "stage_id": random.randint(1, 5),
        "name": f"Lead {lid}", "contact_name": f"Lead {lid}",
        "phone": f"98{random.randint(10000000, 99999999)}",
        "phone_digits": str(random.randint(1000000000, 9999999999)),
        "email_from": f"lead{lid}@example.com",
        "city": random.choice(cities), "state_name": "Delhi",
        "lead_stage": random.choice(stages), "tags": [], "user_id": random.choice(callers),
        "create_date": ds, "create_date_ist": ist, "write_date": ds,
        "source_lead": random.choice(sources), "priority": "0",
    }
    batch.append(doc)
    if len(batch) >= BATCH:
        db.leads.insert_many(batch, ordered=False)
        inserted += len(batch)
        batch = []
        print(f"inserted {inserted}", flush=True)
if batch:
    db.leads.insert_many(batch, ordered=False)
    inserted += len(batch)
print(f"DONE inserted {inserted}, total leads now {db.leads.estimated_document_count()}", flush=True)
