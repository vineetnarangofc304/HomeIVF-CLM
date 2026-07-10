import json
import os
import re
import asyncio
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import db
from core.security import require_permission
from routes.reports import DIMS, build_match, resolve_labels, key_str

load_dotenv()

router = APIRouter(prefix="/ai", tags=["ai"])

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY")
AI_MODEL = ("openai", "gpt-5.5")
CONVERTED = "Converted"

# dims exposed to the AI Brain (label -> mongo expr key in DIMS)
BRAIN_DIMS = ["user_id", "lead_stage", "source_lead", "campaign_name", "ads_platform",
              "state_name", "city", "priority", "follow_up_tag", "tags",
              "create_date:day", "create_date:month"]


async def _grouped(match, dim_key, limit=50, unwind=False):
    """Group leads by a DIMS key returning total + converted per bucket."""
    pipeline = [{"$match": match}]
    if unwind:
        pipeline.append({"$unwind": {"path": "$tags", "preserveNullAndEmptyArrays": True}})
    gid = DIMS[dim_key] if dim_key else None
    pipeline += [
        {"$group": {"_id": gid, "total": {"$sum": 1},
                    "converted": {"$sum": {"$cond": [{"$eq": ["$lead_stage", CONVERTED]}, 1, 0]}}}},
        {"$sort": {"total": -1}},
        {"$limit": limit},
    ]
    return await db.leads.aggregate(pipeline, maxTimeMS=15000).to_list(limit)


async def _labelled(rows, dim_key):
    labels = await resolve_labels(dim_key, [r["_id"] for r in rows])
    out = []
    for r in rows:
        k = r["_id"]
        label = labels.get(k, k)
        if label in (None, False, ""):
            label = "—"
        out.append({"label": str(label), "total": r["total"], "converted": r["converted"],
                    "rate": round(r["converted"] / r["total"] * 100, 1) if r["total"] else 0})
    return out


# ---------------- Advanced analytics (all charts in one call) ----------------
@router.get("/analytics")
async def analytics(date_from: str = None, date_to: str = None,
                    user: dict = Depends(require_permission("reports"))):
    filters = {"active": "all"}
    if date_from:
        filters["date_from"] = date_from
    if date_to:
        filters["date_to"] = date_to
    match = build_match(filters, user)

    trend_pipeline = [{"$match": match},
                      {"$group": {"_id": {"$substrCP": ["$create_date_ist", 0, 10]}, "total": {"$sum": 1},
                                  "converted": {"$sum": {"$cond": [{"$eq": ["$lead_stage", CONVERTED]}, 1, 0]}}}},
                      {"$sort": {"_id": -1}}, {"$limit": 30}]

    # run every aggregation concurrently — sequential awaits were the "Loading…" slowness
    (stage_rows, source_rows, caller_rows, platform_rows,
     campaign_rows, geo_rows, trend_raw) = await asyncio.gather(
        _grouped(match, "lead_stage", 50),
        _grouped(match, "source_lead", 12),
        _grouped(match, "user_id", 15),
        _grouped(match, "ads_platform", 10),
        _grouped(match, "campaign_name", 10),
        _grouped(match, "state_name", 40),
        db.leads.aggregate(trend_pipeline, maxTimeMS=15000).to_list(30),
    )

    STAGE_ORDER = ["New", "Contact Attempt", "Contacted", "Qualified", "Proposition", "Converted", "Closed"]
    funnel = sorted(
        [{"label": r["_id"], "value": r["total"]} for r in stage_rows if r["_id"]],
        key=lambda x: STAGE_ORDER.index(x["label"]) if x["label"] in STAGE_ORDER else 99)

    source, caller, platform, campaign = await asyncio.gather(
        _labelled(source_rows, "source_lead"),
        _labelled(caller_rows, "user_id"),
        _labelled(platform_rows, "ads_platform"),
        _labelled(campaign_rows, "campaign_name"),
    )

    geo = [{"label": str(r["_id"]), "value": r["total"]} for r in geo_rows
           if r["_id"] and re.fullmatch(r"[A-Za-z][A-Za-z .&]{1,39}", str(r["_id"]))][:15]

    trend_raw = [r for r in trend_raw if r["_id"]]
    trend = [{"label": r["_id"], "total": r["total"], "converted": r["converted"]} for r in reversed(trend_raw)]

    total = sum(r["total"] for r in stage_rows)
    converted = next((r["total"] for r in stage_rows if r["_id"] == CONVERTED), 0)
    return {
        "kpis": {"total": total, "converted": converted,
                 "conversion_rate": round(converted / total * 100, 1) if total else 0},
        "funnel": funnel, "source": source, "caller": caller,
        "platform": platform, "campaign": campaign, "geo": geo, "trend": trend,
    }


# ---------------- AI Brain (natural-language analytics) ----------------
class BrainBody(BaseModel):
    question: str
    session_id: str = "default"


SYSTEM_PROMPT = f"""You are the analytics engine for HomeIVF CRM. Convert the user's question into a JSON query spec.
Available metrics: "leads" (count of leads), "conversions" (leads with stage Converted), "conversion_rate".
Available dimensions (group-by): {", ".join(BRAIN_DIMS)}. Use "user_id" for caller/agent. Use null for a single number.
Available filters: date_from (YYYY-MM-DD), date_to (YYYY-MM-DD), source_lead, lead_stage, ads_platform, state_name, city, user_id (int).
chart_type: one of "bar", "line", "pie", "number".
Return ONLY valid JSON, no prose, with keys:
{{"metric": "...", "dimension": "... or null", "chart_type": "...", "filters": {{}}, "title": "short chart title"}}
Rules: for "how many / total" use dimension null + number. For "by/per/top/which" pick the dimension. Use line for time (create_date:day/month), pie for share, bar otherwise."""


def _extract_json(text):
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no json")
    return json.loads(m.group(0))


async def _run_spec(spec, user):
    metric = spec.get("metric", "leads")
    dim = spec.get("dimension")
    if dim not in DIMS:
        dim = None
    filters = spec.get("filters") or {}
    filters.setdefault("active", "all")
    match = build_match(filters, user)
    rows = await _grouped(match, dim, limit=25, unwind=(dim == "tags"))
    if dim:
        data = await _labelled(rows, dim)
        data = [d for d in data if d["label"] not in ("—", "", "None")]
        for d in data:
            d["value"] = d["rate"] if metric == "conversion_rate" else (d["converted"] if metric == "conversions" else d["total"])
        data = sorted(data, key=lambda x: x["value"], reverse=True)
        return data
    r = rows[0] if rows else {"total": 0, "converted": 0}
    val = (round(r["converted"] / r["total"] * 100, 1) if r["total"] else 0) if metric == "conversion_rate" \
        else (r["converted"] if metric == "conversions" else r["total"])
    return [{"label": "Total", "value": val, "total": r["total"], "converted": r["converted"]}]


def _summary(question, spec, data):
    metric = spec.get("metric", "leads")
    unit = {"leads": "leads", "conversions": "conversions", "conversion_rate": "% conversion"}.get(metric, "")
    if not data:
        return "No matching data found for that question."
    if spec.get("dimension"):
        top = data[0]
        suffix = "%" if metric == "conversion_rate" else ""
        total = sum(d.get("total", 0) for d in data)
        return f"{spec.get('title', 'Result')}: top is **{top['label']}** with {top['value']}{suffix} {unit}. " \
               f"({len(data)} groups, {total:,} leads total)."
    d = data[0]
    suffix = "%" if metric == "conversion_rate" else ""
    return f"{spec.get('title', 'Result')}: **{d['value']}{suffix} {unit}**."


@router.post("/brain")
async def brain(body: BrainBody, user: dict = Depends(require_permission("reports"))):
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail="AI is not configured (missing key).")
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"brain-{body.session_id}",
                   system_message=SYSTEM_PROMPT).with_model(*AI_MODEL)
    try:
        resp = await chat.send_message(UserMessage(text=body.question))
        spec = _extract_json(resp if isinstance(resp, str) else str(resp))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI could not interpret that question: {str(e)[:120]}")
    data = await _run_spec(spec, user)
    answer = _summary(body.question, spec, data)
    ct = spec.get("chart_type") if spec.get("dimension") else "number"
    await db.ai_chats.insert_one({"session_id": body.session_id, "question": body.question,
                                  "spec": spec, "answer": answer, "created_at": datetime.now(timezone.utc).isoformat()})
    return {"answer": answer, "chart": {"type": ct, "title": spec.get("title", ""), "data": data}, "spec": spec}


@router.get("/brain/history")
async def brain_history(session_id: str = "default", user: dict = Depends(require_permission("reports"))):
    rows = await db.ai_chats.find({"session_id": session_id}, {"_id": 0}).sort("created_at", 1).to_list(50)
    return rows
