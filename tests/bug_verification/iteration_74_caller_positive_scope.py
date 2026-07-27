#!/usr/bin/env python3
import json, os, time
from pathlib import Path
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

ROOT=Path('/app')
load_dotenv(ROOT/'backend/.env')
base='https://homeivf-crm-2.preview.emergentagent.com/api'
client=MongoClient(os.environ['MONGO_URL'], serverSelectionTimeoutMS=5000)
coll=client[os.environ['DB_NAME']].leads
lead=coll.find_one({'active': True, 'pipeline': {'$ne': False}, 'user_id': 8, 'lead_stage': {'$type': 'string', '$nin':['']}, 'tags.0': {'$exists': True}}, {'_id':0,'id':1,'user_id':1,'lead_stage':1,'tags':1})
res={'candidate': lead}
if lead:
    token=requests.post(base+'/auth/login', json={'email':'caller16@homeivf.com','password':'TestPass@2026'}, timeout=15).json()['access_token']
    params={'bucket':'pipeline','lead_stage':lead['lead_stage'],'tags':str(lead['tags'][0]),'sort':'create_date','order':'desc','limit':200}
    st=time.perf_counter(); r=requests.get(base+'/leads', params=params, headers={'Authorization':f'Bearer {token}'}, timeout=25); dur=int((time.perf_counter()-st)*1000)
    data=r.json()
    users=sorted({it.get('user_id') for it in data.get('items',[])})
    ids=[it.get('id') for it in data.get('items',[])[:10]]
    res.update({'status':r.status_code,'duration_ms':dur,'params':params,'items_len':len(data.get('items',[])),'user_ids_in_result':users,'first_ids':ids,'scope_ok':r.status_code==200 and all(u in (None,8) for u in users)})
Path('/app/test_reports/iteration_74_caller_positive_scope.json').write_text(json.dumps(res, indent=2, sort_keys=True))
print(json.dumps(res, indent=2, sort_keys=True))
