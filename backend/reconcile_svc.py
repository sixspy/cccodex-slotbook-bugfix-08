"""对账：档期 booked 与正式册 seats 同源校验。

BUGFIX-08：对账页同时核对占位与 hold_create 审计的同态（见 docs/占位审计说明.md）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user
from db import connect

router = APIRouter(tags=["reconcile"])


def _hold_audit_stats(conn, slot_id: int) -> tuple[int, int]:
    """返回 (开放占位数, 已与审计互证占位数)。"""
    open_holds = conn.execute(
        "SELECT COUNT(*) c FROM holds WHERE slot_id=? AND status='占位中'",
        (slot_id,),
    ).fetchone()["c"]
    proven = conn.execute(
        """SELECT COUNT(*) c FROM holds h
           WHERE h.slot_id=? AND h.status='占位中'
             AND EXISTS (
               SELECT 1 FROM audit_trail a
               WHERE a.action IN ('hold_create','waitlist_promote')
                 AND json_extract(a.payload, '$.hold_id') = h.id)""",
        (slot_id,),
    ).fetchone()["c"]
    return int(open_holds), int(proven)


@router.get("/api/reconcile")
def reconcile_all(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        slots = conn.execute("SELECT * FROM slots ORDER BY code").fetchall()
        items = []
        for s in slots:
            booked_sum = conn.execute(
                """SELECT COALESCE(SUM(seats),0) s FROM bookings
                   WHERE slot_id=? AND status='已确认'""",
                (s["id"],),
            ).fetchone()["s"]
            open_holds, proven_holds = _hold_audit_stats(conn, s["id"])
            ok = int(booked_sum) == int(s["booked"])
            hold_audit_ok = open_holds == proven_holds
            items.append(
                {
                    "slot_code": s["code"],
                    "slot_booked": s["booked"],
                    "booking_seats": booked_sum,
                    "generation": s["generation"],
                    "status": s["status"],
                    "ok": ok,
                    "open_holds": open_holds,
                    "proven_holds": proven_holds,
                    "hold_audit_ok": hold_audit_ok,
                }
            )
        return {
            "items": items,
            "all_ok": all(i["ok"] for i in items),
            "hold_audit_all_ok": all(i["hold_audit_ok"] for i in items),
        }


@router.get("/api/reconcile/{code}")
def reconcile_one(code: str, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        s = conn.execute("SELECT * FROM slots WHERE code=?", (code,)).fetchone()
        if not s:
            raise HTTPException(404, "档期不存在")
        booked_sum = conn.execute(
            """SELECT COALESCE(SUM(seats),0) s FROM bookings
               WHERE slot_id=? AND status='已确认'""",
            (s["id"],),
        ).fetchone()["s"]
        open_holds, proven_holds = _hold_audit_stats(conn, s["id"])
        return {
            "slot_code": code,
            "slot_booked": s["booked"],
            "booking_seats": booked_sum,
            "open_holds": open_holds,
            "proven_holds": proven_holds,
            "hold_audit_ok": open_holds == proven_holds,
            "ok": int(booked_sum) == int(s["booked"]),
            "generation": s["generation"],
        }
