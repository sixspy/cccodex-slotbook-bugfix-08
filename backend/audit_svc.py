"""审计与互证只读面。

BUGFIX-08：审计页不再过滤 hold_create，缺审计如实可见（见 docs/占位审计说明.md）。
"""
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
        return {"items": [dict(r) for r in rows]}


@router.get("/api/proof/{party_key}")
def proof(party_key: str, authorization: AuthHeader = None):
    """按当事人互证：占位/正式/候补与审计流水是否同源可读。"""
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
        audits = conn.execute(
            "SELECT * FROM audit_trail WHERE target=? ORDER BY id DESC", (party_key,)
        ).fetchall()
        hold_rows = [dict(r) for r in holds]
        # 每个占位是否有同源审计（hold_create 或晋升产生的 waitlist_promote，payload 回链 hold_id）
        proven_rows = conn.execute(
            """SELECT DISTINCT json_extract(payload, '$.hold_id') AS hold_id
               FROM audit_trail
               WHERE target=? AND action IN ('hold_create','waitlist_promote')""",
            (party_key,),
        ).fetchall()
        proven = {int(r["hold_id"]) for r in proven_rows if r["hold_id"] is not None}
        return {
            "party_key": party_key,
            "holds": hold_rows,
            "bookings": [dict(r) for r in books],
            "waitlist": [dict(r) for r in waits],
            "audits": [dict(r) for r in audits],
            "holds_total": len(hold_rows),
            "holds_proven": sum(1 for h in hold_rows if h["id"] in proven),
            "all_holds_proven": len(hold_rows) == len(proven),
        }
