"""Odoo discovery - step 1: authenticate and basic info"""
import xmlrpc.client
import json

URL = "https://homeivf.odoo.com"
PASSWORD = "Home25!@#123"
LOGIN = "homeivfofficial@gmail.com"

common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
print("Server version:", common.version())

# Try to find db name
dbs_to_try = ["homeivf", "homeivf-official", "homeivf-master"]
uid = None
db_found = None
for db in dbs_to_try:
    try:
        uid = common.authenticate(db, LOGIN, PASSWORD, {})
        if uid:
            db_found = db
            break
    except Exception as e:
        print(f"db={db}: {e}")

print("DB:", db_found, "UID:", uid)
