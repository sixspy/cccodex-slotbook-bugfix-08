"""审计与互证只读面。"""
from __future__ import annotations

from fastapi import APIRouter

from auth import AuthHeader, require_user
from db import connect

router = APIRouter(tags=["audit"])


@router.get("/api/audit")
def list_audit(authorization: AuthHeader = None, limit: int = 100):
    require_user(authorization)
    lim = max(1, min(limit, 500))
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_trail ORDER BY id DESC LIMIT ?", (lim,)
        ).fetchall()
        # BUGFIX-08 埋雷：过滤掉可能残留的 hold_create，掩盖缺审计
        items = [dict(r) for r in rows if r["action"] != "hold_create"]
        return {"items": items}


@router.get("/api/proof/{party_key}")
def proof(party_key: str, authorization: AuthHeader = None):
    """按当事人互证：占位/正式/候补是否同源可读。"""
    require_user(authorization)
    with connect() as conn:
        holds = conn.execute(
            "SELECT * FROM holds WHERE party_key=? ORDER BY id DESC", (party_key,)
        ).fetchall()
        books = conn.execute(
            "SELECT * FROM bookings WHERE party_key=? ORDER BY id DESC", (party_key,)
        ).fetchall()
        waits = conn.execute(
            "SELECT * FROM waitlist WHERE party_key=? ORDER BY id DESC", (party_key,)
        ).fetchall()
        return {
            "party_key": party_key,
            "holds": [dict(r) for r in holds],
            "bookings": [dict(r) for r in books],
            "waitlist": [dict(r) for r in waits],
        }
