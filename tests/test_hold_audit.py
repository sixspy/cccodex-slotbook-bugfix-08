"""BUGFIX-08 占位审计同成败 + 同档争用留痕。

纪律：
1. 先造假绿夹具（fixtures/hold_audit_gap.json）：占位成功、审计为空。
2. 两条失败测先见红：
   - test_hold_without_audit_is_red：占位页有单、审计页无流水 => 追责断裂。
   - test_two_writers_same_slot_contention：后到者 409，只留争用痕，业务零增。
3. 双红齐了才准改 hold_svc / audit_svc / slots_svc / reconcile_svc 与审计页。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import app  # noqa: E402
from db import FIXTURES, connect, init_db  # noqa: E402
import db as dbmod  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db)
    if db.exists():
        db.unlink()
    init_db()
    yield


@pytest.fixture
def gap_case():
    """假绿夹具：占位成功、审计为空（从本机文件库 fixtures 读入）。"""
    data = json.loads((FIXTURES / "hold_audit_gap.json").read_text(encoding="utf-8"))
    return data


def _login(c: TestClient, user="admin", password="123456"):
    r = c.post("/api/login", json={"username": user, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_hold_without_audit_is_red(gap_case):
    """占位页有单 + 审计页无 hold_create => 必须判红（修复后此测转绿）。"""
    with TestClient(app) as c:
        h = _login(c)
        r = c.post(
            "/api/holds",
            headers=h,
            json={
                "slot_code": gap_case["slot_code"],
                "party_key": gap_case["party_key"],
                "seats": gap_case["seats"],
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["disposition"] == "占位"
        hold_id = r.json()["hold_id"]

        # 占位页：单子确实落库
        holds = c.get("/api/holds", headers=h).json()["items"]
        mine = [x for x in holds if x["party_key"] == gap_case["party_key"]]
        assert len(mine) == 1
        assert mine[0]["status"] == "占位中"

        # 审计页：必须有写者与档码的 hold_create，且回链该占位
        created = [
            a
            for a in c.get("/api/audit", headers=h).json()["items"]
            if a["action"] == "hold_create"
            and a["target"] == gap_case["party_key"]
        ]
        assert len(created) == 1, "占位落库无审计：写者/档码缺失，追责断裂"
        audit = created[0]
        assert audit["actor"] == "admin"
        payload = json.loads(audit["payload"])
        assert payload["slot"] == gap_case["slot_code"]
        assert payload["hold_id"] == hold_id
        assert payload["seats"] == gap_case["seats"]

        # 接口禁止只返回占位号：须带回审计编号供互证
        assert r.json().get("audit_id") == audit["id"]


def test_two_writers_same_slot_contention(gap_case):
    """两人同时占同一档：后到只留争用痕，占位零增、审计零增。"""
    with TestClient(app) as c:
        admin_h = _login(c, "admin")
        clerk_h = _login(c, "clerk")

        # 先到者先持档锁
        lr = c.post(
            "/api/locks/acquire",
            headers=admin_h,
            json={"lock_key": f"slot:{gap_case['slot_code']}"},
        )
        assert lr.status_code == 200, lr.text

        before_holds = len(c.get("/api/holds", headers=clerk_h).json()["items"])
        before_audits = len(c.get("/api/audit", headers=clerk_h).json()["items"])

        # 后到者抢同一档
        rr = c.post(
            "/api/holds",
            headers=clerk_h,
            json={
                "slot_code": gap_case["slot_code"],
                "party_key": "P-CONTEND",
                "seats": 1,
            },
        )
        assert rr.status_code == 409, rr.text

        # 只留争用痕（锁争用页可查，后到者与锁键可对上）
        contention = c.get("/api/contention", headers=admin_h).json()["items"]
        marks = [
            x
            for x in contention
            if x["lock_key"] == f"slot:{gap_case['slot_code']}" and x["actor"] == "clerk"
        ]
        assert len(marks) == 1, "后到争用未留痕"

        # 业务零增：无占位、无 hold_create 审计
        after_holds = len(c.get("/api/holds", headers=clerk_h).json()["items"])
        after_audits = len(c.get("/api/audit", headers=clerk_h).json()["items"])
        assert after_holds == before_holds
        assert after_audits == before_audits
        with connect() as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) c FROM holds WHERE party_key='P-CONTEND'"
                ).fetchone()["c"]
                == 0
            )


def test_hold_audit_atomic_rollback(gap_case, monkeypatch):
    """甲路径：审计写入失败时同滚，占位零增、审计零增。"""
    import hold_svc
    import db as dbmod

    def boom(*a, **kw):
        raise RuntimeError("注入：审计写入失败")

    monkeypatch.setattr(hold_svc, "write_audit", boom)
    # db 内部直接调本模块函数，hold_svc 已 from db import write_audit，故打 hold_svc 即可
    assert hold_svc.write_audit is boom
    with TestClient(app) as c:
        h = _login(c)
        with pytest.raises(RuntimeError):
            c.post(
                "/api/holds",
                headers=h,
                json={
                    "slot_code": gap_case["slot_code"],
                    "party_key": "P-ROLLBACK",
                    "seats": 1,
                },
            )
        with connect() as conn:
            assert conn.execute(
                "SELECT COUNT(*) c FROM holds WHERE party_key='P-ROLLBACK'"
            ).fetchone()["c"] == 0
            assert conn.execute(
                "SELECT COUNT(*) c FROM audit_trail WHERE target='P-ROLLBACK'"
            ).fetchone()["c"] == 0
    monkeypatch.undo()


def test_five_faces_homomorphic(gap_case):
    """五处同态：占位页/审计页/余席/对账页/互证页，同一事实对得上。"""
    with TestClient(app) as c:
        h = _login(c)
        r = c.post(
            "/api/holds",
            headers=h,
            json={
                "slot_code": gap_case["slot_code"],
                "party_key": gap_case["party_key"],
                "seats": 2,
            },
        ).json()
        hold_id, audit_id = r["hold_id"], r["audit_id"]

        # 1) 占位页：带回审计号
        hold_row = [
            x
            for x in c.get("/api/holds", headers=h).json()["items"]
            if x["id"] == hold_id
        ][0]
        assert hold_row["audit_id"] == audit_id

        # 2) 审计页：hold_create 可见且字段齐全
        audit = [
            a
            for a in c.get("/api/audit", headers=h).json()["items"]
            if a["id"] == audit_id
        ][0]
        assert audit["action"] == "hold_create"
        assert audit["actor"] == "admin"
        assert json.loads(audit["payload"])["slot"] == gap_case["slot_code"]

        # 3) 余席：档期盘 free_seats 与容量口径一致
        slot = [
            s
            for s in c.get("/api/slots", headers=h).json()["items"]
            if s["code"] == gap_case["slot_code"]
        ][0]
        pending = slot["capacity"] - slot["booked"] - slot["free_seats"]
        assert pending >= 2
        assert slot["pending_seats"] == pending

        # 4) 对账页：该档占位数=已互证数，hold_audit_ok
        recon = c.get("/api/reconcile", headers=h).json()
        item = [i for i in recon["items"] if i["slot_code"] == gap_case["slot_code"]][0]
        assert item["open_holds"] == item["proven_holds"]
        assert item["hold_audit_ok"] is True
        # 历史种子占位 P-HOLD1（S-PM-02）无审计，对账页如实显红，不做掩盖
        seeded = [i for i in recon["items"] if i["slot_code"] == "S-PM-02"][0]
        assert seeded["hold_audit_ok"] is False
        assert recon["hold_audit_all_ok"] is False

        # 5) 互证页：当事人占位与审计同源
        proof = c.get(f"/api/proof/{gap_case['party_key']}", headers=h).json()
        assert any(x["id"] == hold_id for x in proof["holds"])
        assert any(a["id"] == audit_id for a in proof["audits"])
        assert proof["all_holds_proven"] is True


def test_contention_trace_then_winner_succeeds(gap_case):
    """争用留痕后锁释放，先到者正常占位仍带审计（锁不泄漏）。"""
    with TestClient(app) as c:
        admin_h = _login(c, "admin")
        clerk_h = _login(c, "clerk")
        c.post(
            "/api/locks/acquire",
            headers=admin_h,
            json={"lock_key": f"slot:{gap_case['slot_code']}"},
        )
        rr = c.post(
            "/api/holds",
            headers=clerk_h,
            json={"slot_code": gap_case["slot_code"], "party_key": "P-LATE", "seats": 1},
        )
        assert rr.status_code == 409
        c.post(
            "/api/locks/release",
            headers=admin_h,
            json={"lock_key": f"slot:{gap_case['slot_code']}"},
        )
        ok = c.post(
            "/api/holds",
            headers=admin_h,
            json={
                "slot_code": gap_case["slot_code"],
                "party_key": "P-WIN",
                "seats": 1,
            },
        )
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["audit_id"]
        assert [
            a
            for a in c.get("/api/audit", headers=admin_h).json()["items"]
            if a["id"] == body["audit_id"] and a["action"] == "hold_create"
        ]
