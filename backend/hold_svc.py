"""占位：容量校验、并发锁、候补分流。

BUGFIX-08 甲路径（见 docs/占位审计说明.md）：
- 占位行与 hold_create 审计在同一事务同成败，失败两边同滚、占位零增；
- 抢档锁失败（争用）先提交 contention_log 再 409，后到只留争用痕、业务零增；
- 成功响应同时回 hold_id 与 audit_id，禁止只返回占位号。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from auth import AuthHeader, require_user, require_writer
from db import connect, write_audit
from locks import release, require_lock

router = APIRouter(tags=["holds"])


class HoldIn(BaseModel):
    slot_code: str
    party_key: str
    seats: int = Field(ge=1, le=50)


@router.get("/api/holds")
def list_holds(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT h.*, s.code AS slot_code,
                      (SELECT a.id FROM audit_trail a
                        WHERE a.action IN ('hold_create','waitlist_promote')
                          AND json_extract(a.payload, '$.hold_id') = h.id
                        ORDER BY a.id LIMIT 1) AS audit_id
               FROM holds h
               JOIN slots s ON s.id=h.slot_id ORDER BY h.id DESC LIMIT 200"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/holds")
def create_hold(body: HoldIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    lock_key = f"slot:{body.slot_code}"
    with connect() as conn:
        # 争用路径：require_lock 已写 contention_log，先提交留痕再 409，
        # 不进业务事务，占位与审计零增（后到只留争用痕）。
        try:
            require_lock(conn, lock_key, user)
        except HTTPException:
            conn.commit()
            raise
        try:
            slot = conn.execute(
                "SELECT * FROM slots WHERE code=?", (body.slot_code,)
            ).fetchone()
            if not slot:
                raise HTTPException(404, "档期不存在")
            if slot["status"] != "开放":
                raise HTTPException(409, "档期未开放，禁止占位")
            remain = int(slot["capacity"]) - int(slot["booked"])
            pending = conn.execute(
                "SELECT COALESCE(SUM(seats),0) s FROM holds WHERE slot_id=? AND status='占位中'",
                (slot["id"],),
            ).fetchone()["s"]
            free = remain - int(pending)
            now = datetime.now().isoformat(timespec="seconds")
            expire = (datetime.now() + timedelta(minutes=30)).isoformat(timespec="seconds")
            if body.seats > free:
                conn.execute(
                    """INSERT INTO waitlist(slot_id,party_key,seats,reason,status,created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (slot["id"], body.party_key, body.seats, "容量不足", "候补中", now),
                )
                write_audit(
                    conn,
                    user,
                    "hold_to_waitlist",
                    body.party_key,
                    {"slot": body.slot_code, "free": free, "want": body.seats},
                )
                conn.commit()
                return {"disposition": "候补", "free": free}
            # 甲路径：同一事务内先落占位、再写 hold_create，单次 commit 同成败。
            cur = conn.execute(
                """INSERT INTO holds(slot_id,party_key,seats,status,expire_at,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (slot["id"], body.party_key, body.seats, "占位中", expire, now),
            )
            hold_id = cur.lastrowid
            write_audit(
                conn,
                user,
                "hold_create",
                body.party_key,
                {"slot": body.slot_code, "hold_id": hold_id, "seats": body.seats},
            )
            audit_id = conn.execute(
                "SELECT last_insert_rowid() AS id"
            ).fetchone()["id"]
            conn.commit()
            # 禁止只返回占位号：hold_id 与 audit_id 同回，供互证。
            return {
                "disposition": "占位",
                "hold_id": hold_id,
                "audit_id": audit_id,
                "expire_at": expire,
            }
        except Exception:
            # 任一步失败：同滚，占位零增、审计零增。
            conn.rollback()
            raise
        finally:
            release(conn, lock_key, user)
            conn.commit()
