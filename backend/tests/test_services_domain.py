"""领域服务单元测试：覆盖补厚后的真实业务计算逻辑。

包括配额降级、用量对账、授权回收、新鲜度分级、SLA结算升级、
审计去重与缓存版本切换失效。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.services.access_grant import AccessGrantService
from app.services.cache_policy import CachePolicyService
from app.services.contract_audit import ContractAuditService
from app.services.freshness_track import FreshnessTrackService
from app.services.rate_quota import RateQuotaService
from app.services.result_set import ResultSetService
from app.services.sla_breach import SlaBreachService
from app.services.sla_target import SlaTargetService
from app.services.usage_meter import UsageMeterService
from app.store import store


class TestRateQuotaService:
    def test_consume_within_limit(self):
        service = RateQuotaService()
        result = service.consume_quota("APP-NEW-X", "EP-001")
        assert result["allowed"] is True
        assert result["degraded"] is False

    def test_consume_exceeded_degrades_not_drops(self):
        """超额时降级返回而不是拒绝执行。"""
        service = RateQuotaService()
        service.consume_quota("APP-OVER", "EP-009")
        quota = service._find_quota("APP-OVER", "EP-009")
        quota["当前用量"] = quota["日级上限"]
        result = service.consume_quota("APP-OVER", "EP-009")
        assert result["allowed"] is True
        assert result["degraded"] is True
        assert quota["status"] == "已超额"

    def test_frozen_quota_rejected(self):
        service = RateQuotaService()
        service.consume_quota("APP-FROZEN", "EP-009")
        quota = service._find_quota("APP-FROZEN", "EP-009")
        quota["status"] = "已冻结"
        result = service.consume_quota("APP-FROZEN", "EP-009")
        assert result["allowed"] is False

    def test_reset_window_only_once(self):
        service = RateQuotaService()
        service.consume_quota("APP-W", "EP-009")
        quota = service._find_quota("APP-W", "EP-009")
        quota["当前用量"] = "500"
        assert service.reset_window("APP-W", "EP-009", "2026-12") is True
        assert quota["当前用量"] == "0"
        assert service.reset_window("APP-W", "EP-009", "2026-12") is False


class TestUsageMeterService:
    def test_reconcile_with_plans_marks_mismatch(self):
        """计量读数与查询计划对不上时转待复核。"""
        service = UsageMeterService()
        plans = store.rows("query_plan")
        plan_id = max(int(p["id"]) for p in plans) + 1
        plans.append({
            "id": plan_id, "计划编号": f"QPLN-{plan_id}", "所属端点": "EP-002",
            "筛选条件": "{}", "扫描范围": "page=1", "预估行数": "10",
            "执行策略": "full", "实际行数": "42", "执行耗时": "5ms",
            "status": "已返回", "pending": False, "abnormal": False,
        })
        meter = service.record_usage("APP-M", "EP-002", 1, 99, plan_id=plan_id)
        result = service.reconcile_with_plans()
        assert result["mismatched"] >= 1
        assert meter["status"] == "待复核"

    def test_settle_window_aggregates(self):
        service = UsageMeterService()
        window = datetime.now().strftime("%Y-%m-%dT%H")
        service.record_usage("APP-S", "EP-002", 2, 50)
        service.record_usage("APP-S", "EP-002", 3, 70)
        bill = service.settle_window("APP-S", "EP-002", window[:10])
        assert bill["settled_count"] == 2
        assert bill["total_calls"] == 5
        assert bill["total_rows"] == 120


class TestAccessGrantService:
    def test_check_access_rejects_expired(self):
        service = AccessGrantService()
        service.authorize(
            "APP-G", "EP-002", ["txn_id"], "1=1",
            "2025-01-01", "2025-12-31",
        )
        result = service.check_access("APP-G", "EP-002", today="2026-11-21")
        assert result["allowed"] is False

    def test_revoke_expired_suspends_subscriptions(self):
        """授权回收联动暂停订阅。"""
        subs = store.rows("subscription_plan")
        sub_id = max(int(s["id"]) for s in subs) + 1
        subs.append({
            "id": sub_id, "订阅编号": f"SUBS-{sub_id}", "消费方应用": "APP-RV",
            "所属契约": "CTR-002", "订阅版本": "v1.3", "取数频率": "每小时",
            "配额上限": "100", "订阅起日": "2026-01-01", "最近取数": "",
            "status": "生效中", "pending": True, "abnormal": False,
        })
        service = AccessGrantService()
        service.authorize("APP-RV", "EP-002", ["txn_id"], "1=1", "2025-01-01", "2025-06-30")
        revoked = service.revoke_expired(today="2026-11-21")
        assert any(r["消费方应用"] == "APP-RV" for r in revoked)
        sub = store.find("subscription_plan", sub_id)
        assert sub["status"] == "已暂停"

    def test_apply_column_scope(self):
        service = AccessGrantService()
        grant = {"可见列范围": "txn_id,amount"}
        rows = [{"txn_id": "T1", "amount": "100", "secret": "x"}]
        scoped = service.apply_column_scope(grant, rows)
        assert scoped == [{"txn_id": "T1", "amount": "100"}]


class TestFreshnessTrackService:
    def test_classify_lag_levels(self):
        service = FreshnessTrackService()
        assert service.classify_lag(10, 5) == "达标"
        assert service.classify_lag(10, 15) == "轻微滞后"
        assert service.classify_lag(10, 25) == "严重滞后"

    def test_track_reading_shortens_snapshots(self):
        """滞后读数推进快照有效期水位。"""
        snaps = store.rows("result_set")
        snap_id = max(int(s["id"]) for s in snaps) + 1
        snaps.append({
            "id": snap_id, "快照编号": f"SNAP-{snap_id}", "所属计划": "1",
            "绑定版本": "CTR-009-v9", "快照行数": "10", "列摘要值": "x",
            "有效期": "2027-12-31T23:59:59", "引用次数": "0",
            "生成时间": "2026-11-21", "status": "可读", "pending": False, "abnormal": False,
        })
        service = FreshnessTrackService()
        reading = service.track_reading("CTR-009", 10, 55, "2026-11-21T11:00:00")
        assert reading["status"] == "严重滞后"
        snap = store.find("result_set", snap_id)
        assert snap["有效期"] != "2027-12-31T23:59:59"


class TestSlaServices:
    def test_settle_breach_generates_event(self):
        """SLA未达标结算产出违约事件数据集。"""
        target_service = SlaTargetService()
        breach_service = SlaBreachService()
        # 查询延迟P99 目标按 lagging 字段统计，构造 50% 滞后样本触发未达标
        samples = [{"lagging": False}] * 5 + [{"lagging": True}] * 5
        targets = [t for t in store.rows("sla_target") if t.get("所属契约") == "CTR-002"]
        target = targets[0]
        result = target_service.settle(int(target["id"]), samples)
        assert result["status"] == "settled"
        assert result["achievement"] == 50.0
        assert result["breached"] is True
        breach = breach_service.create_from_settlement(
            target["目标编号"], result["threshold"], result["achievement"], "2026-11"
        )
        assert breach["status"] == "已登记"
        assert int(breach["影响应用数"]) >= 1
        assert breach["偏离幅度"].endswith("%")

    def test_escalate_downgrades_contract_level(self):
        """违约升级回写契约承诺等级并写审计。"""
        breach_service = SlaBreachService()
        breach = breach_service.create_from_settlement("SLA-CTR-005", 99.0, 90.0, "2026-11")
        result = breach_service.escalate(breach["事件编号"], "连续未达标")
        assert result["status"] == "escalated"
        contract = next(
            c for c in store.rows("data_contract") if c.get("契约编号") == "CTR-005"
        )
        assert "违约降级" in contract["承诺等级"]
        audits = [
            a for a in store.rows("contract_audit")
            if a.get("所属契约") == "CTR-005" and a.get("操作类型") == "违约处置"
        ]
        assert len(audits) == 1

    def test_escalate_twice_rejected(self):
        breach_service = SlaBreachService()
        breach = breach_service.create_from_settlement("SLA-CTR-001", 99.0, 90.0, "2026-11")
        breach_service.escalate(breach["事件编号"], "第一次")
        second = breach_service.escalate(breach["事件编号"], "第二次")
        assert second["status"] == "error"


class TestResultSetService:
    def test_digest_and_hit_same_snapshot(self):
        """同一结果集重复读取命中同一份快照。"""
        service = ResultSetService()
        rows = [{"a": "1", "b": "2"}]
        digest = service.compute_column_digest(rows)
        snap1 = service.freeze_snapshot(777, "v1.0", rows)
        hit = service.hit_snapshot(777, digest)
        assert hit is not None
        assert hit["快照编号"] == snap1["快照编号"]
        assert int(hit["引用次数"]) == 2

    def test_expire_outdated(self):
        service = ResultSetService()
        snaps = store.rows("result_set")
        snap_id = max(int(s["id"]) for s in snaps) + 1
        snaps.append({
            "id": snap_id, "快照编号": f"SNAP-{snap_id}", "所属计划": "1",
            "绑定版本": "v1", "快照行数": "1", "列摘要值": "x",
            "有效期": "2020-01-01T00:00:00", "引用次数": "0",
            "生成时间": "2020-01-01", "status": "可读", "pending": False, "abnormal": False,
        })
        expired = service.expire_outdated()
        assert expired >= 1
        assert store.find("result_set", snap_id)["status"] == "已过期"


class TestCachePolicyService:
    def test_version_switch_invalidates_cache(self):
        """版本切换时旧缓存整体失效。"""
        service = CachePolicyService()
        cache = {}
        key = service.build_cache_key("EP-001", {"user_id": "U1"})
        service.record_access("EP-001", cache, key, {"rows": [1]}, hit=False)
        assert len(cache) == 1
        cleared = service.invalidate_on_version_switch("EP-001", cache)
        assert cleared == 1
        assert len(cache) == 0

    def test_lookup_expired_entry_returns_none(self):
        service = CachePolicyService()
        cache = {"k": {"payload": {"x": 1}, "expires_at": 1}}
        assert service.lookup(cache, "k") is None
        assert "k" not in cache


class TestContractAuditService:
    def test_record_and_dedupe_same_day(self):
        service = ContractAuditService()
        r1 = service.record_change("CTR-002", "版本演进", "contract_version", "v1.2", "v9.9", "tester")
        assert r1["status"] == "recorded"
        r2 = service.record_change("CTR-002", "版本演进", "contract_version", "v1.2", "v9.9", "tester")
        assert r2["status"] == "duplicate"

    def test_verify_chain_finds_gap(self):
        """未签署契约演进但无审计记录时检出缺口。"""
        service = ContractAuditService()
        result = service.verify_chain("CTR-005")
        # CTR-005 已签署但无签署审计 → 有缺口
        assert result["complete"] is False
        assert any("签署契约" in g for g in result["gaps"])

    def test_seal_chain_only_seals_checked(self):
        service = ContractAuditService()
        chain = service.get_audit_for_contract("CTR-001")
        for item in chain:
            if item.get("status") == "待核查":
                item["status"] = "已核查"
        sealed = service.seal_chain("CTR-001")
        assert sealed >= 1
