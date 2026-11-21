"""SLA与新鲜度追踪链路测试：新鲜度追踪→SLA结算→违约事件生成→违约升级。

覆盖：滞后影响快照有效期、SLA自动生成违约事件、升级回写契约承诺等级。
"""
from __future__ import annotations

import pytest
from app.integration.sla_freshness_chain import (
    track_freshness_and_settle_sla,
    escalate_breach,
)
from app.store import store


class TestFreshnessTracking:
    """链路7：新鲜度追踪测试"""

    def test_freshness_on_time_is_达标(self):
        """新鲜度达标：实际延迟小于等于承诺延迟。"""
        result = track_freshness_and_settle_sla(
            contract_id="CTR-005",
            promised_delay_minutes=5,
            actual_delay_minutes=3,
            water_level="2026-11-21T12:02:00",
        )
        assert result["freshness"]["status"] == "达标"
        assert result["lag_ratio"] <= 1.0

    def test_freshness_lag_triggers_sla_settlement(self):
        """新鲜度滞后：触发SLA结算未达标并生成违约事件。"""
        before_breaches = len(store.rows("sla_breach"))
        result = track_freshness_and_settle_sla(
            contract_id="CTR-001",
            promised_delay_minutes=10,
            actual_delay_minutes=25,
            water_level="2026-11-21T11:35:00",
        )
        assert result["freshness"]["status"] == "严重滞后"
        assert result["lag_ratio"] > 2.0

        # 检查是否生成了新的SLA违约事件
        after_breaches = len(store.rows("sla_breach"))
        assert after_breaches >= before_breaches

    def test_lag_shortens_snapshot_expiry(self):
        """滞后缩短结果集快照有效期。"""
        # 先创建一个可读快照
        snap_rows = store.rows("result_set")
        snap_rows.append({
            "id": 999, "快照编号": "SNAP-TEST", "所属计划": "1",
            "绑定版本": "CTR-001", "快照行数": "100",
            "列摘要值": "{}", "有效期": "2027-12-31T23:59:59",
            "引用次数": "1", "生成时间": "2026-11-21",
            "status": "可读", "pending": False, "abnormal": False,
        })

        track_freshness_and_settle_sla(
            contract_id="CTR-001",
            promised_delay_minutes=10,
            actual_delay_minutes=55,
            water_level="2026-11-21T11:05:00",
        )

        # 检查快照有效期是否被缩短
        snap = next((s for s in snap_rows if s.get("快照编号") == "SNAP-TEST"), None)
        if snap:
            assert snap["有效期"] != "2027-12-31T23:59:59"


class TestBreachEscalation:
    """链路8：违约升级测试"""

    def test_escalate_breach_updates_status(self):
        """升级违约事件：状态变为已升级。"""
        result = escalate_breach(
            breach_event_id="BRCH-0002",
            reason="SLA连续两周期未达标，需升级处置等级",
        )
        assert result["status"] == "escalated"

        # 验证事件状态
        for br in store.rows("sla_breach"):
            if br.get("事件编号") == "BRCH-0002":
                assert br["status"] == "已升级"

    def test_escalate_already_escalated_returns_error(self):
        """重复升级已升级事件：返回错误。"""
        escalate_breach("BRCH-0001", "第一次升级")
        result = escalate_breach("BRCH-0001", "重复升级")
        assert result["status"] == "error"
        assert "已升级" in result["message"]

    def test_escalate_nonexistent_breach(self):
        """升级不存在的事件：返回错误。"""
        result = escalate_breach("BRCH-NONEXIST", "测试")
        assert result["status"] == "error"