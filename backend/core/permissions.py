"""Role-based access control — permission matrix per role (admin/manager/caller).

Admin is always full-access and cannot be reduced (prevents lock-out).
Manager & caller permissions are editable by an admin in Admin -> Users.
"""
import time

from core.db import db

MODULE_PERMS = ["dashboard", "leads", "followups", "call_center", "whatsapp",
                "marketing", "reports", "templates", "admin"]
ACTION_PERMS = ["leads_view_all", "leads_edit", "leads_reassign", "leads_delete",
                "export", "migration", "manage_users", "admin_write"]
ALL_PERMS = MODULE_PERMS + ACTION_PERMS

# Human-friendly labels for the admin UI.
PERM_LABELS = {
    "dashboard": "Dashboard", "leads": "Leads", "followups": "Follow-ups",
    "call_center": "Call Center", "whatsapp": "WhatsApp", "marketing": "Marketing",
    "reports": "Reports", "templates": "Templates", "admin": "Admin panel",
    "leads_view_all": "See ALL leads (not just own)", "leads_edit": "Edit leads",
    "leads_reassign": "Reassign leads", "leads_delete": "Delete leads",
    "export": "Export (Excel/PDF)", "migration": "Migration & Odoo sync",
    "manage_users": "Manage users & settings", "admin_write": "Edit admin settings",
}

DEFAULT_PERMISSIONS = {
    "admin": {k: True for k in ALL_PERMS},
    "manager": {
        "dashboard": True, "leads": True, "followups": True, "call_center": True,
        "whatsapp": True, "templates": True, "marketing": True, "reports": True, "admin": True,
        "leads_view_all": True, "leads_edit": True, "leads_reassign": True,
        "leads_delete": False, "export": False, "migration": False,
        "manage_users": False, "admin_write": False,
    },
    "caller": {
        "dashboard": True, "leads": True, "followups": True, "call_center": True,
        "whatsapp": True, "templates": True, "marketing": False, "reports": False, "admin": False,
        "leads_view_all": False, "leads_edit": True, "leads_reassign": False,
        "leads_delete": False, "export": False, "migration": False,
        "manage_users": False, "admin_write": False,
    },
}


# get_current_user resolves permissions on EVERY authenticated request, so the
# raw stored-overrides doc is cached in-process (rebuilt fresh per call so callers
# may safely mutate the result). Busted on admin edit; short TTL as a safety net.
_perm_cache = {"stored": None, "ts": 0.0}
_PERM_CACHE_TTL = 60.0


def invalidate_role_permissions_cache() -> None:
    _perm_cache["stored"] = None
    _perm_cache["ts"] = 0.0


async def get_role_permissions() -> dict:
    """Full matrix: stored overrides merged over defaults. Admin always full.
    The stored overrides are cached for _PERM_CACHE_TTL seconds."""
    now = time.monotonic()
    stored = _perm_cache["stored"]
    if stored is None or (now - _perm_cache["ts"]) >= _PERM_CACHE_TTL:
        doc = await db.settings.find_one({"key": "role_permissions"}, {"_id": 0})
        stored = (doc or {}).get("value") or {}
        _perm_cache["stored"] = stored
        _perm_cache["ts"] = now
    result = {}
    for role, defaults in DEFAULT_PERMISSIONS.items():
        if role == "admin":
            result[role] = {k: True for k in ALL_PERMS}
        else:
            result[role] = {**defaults, **(stored.get(role) or {})}
    return result


async def effective_permissions(role: str) -> dict:
    perms = await get_role_permissions()
    return perms.get(role) or {k: False for k in ALL_PERMS}
