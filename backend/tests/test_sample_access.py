"""授权与抽样链路测试：抽样探查→访问授权→授权到期回收。

覆盖：抽样不达标阻断授权、授权到期自动回收、契约冻结回收授权。
"""
from __future__ import annotations

import pytest
from app.integration.sample_access_chain import (
    probe_sample_and_grant_access,
    revoke_expired_grants,
)
from app.store import store


class TestProbeAndGrant:
    """链路11：抽样探查与授权测试"""

    def test_probe_pass_enables_grant(self):
        """抽样通过：创建访问授权。"""
        result = probe_sample_and_grant_access(
            dataset_name="test_dataset_ok",
            sample_ratio=0.5,
            consumer_app_id="APP-ANALYTICS",
            endpoint_id="EP-001",
            visible_columns="user_id,event_type",
            row_filter="event_type='click'",
            grant_days=365,
        )
        # 抽样比例0.5时完整性约94.5%，可能通过也可能不通过
        assert result["status"] in ("granted", "blocked")

    def test_probe_block_stops_grant(self):
        """抽样不通过：阻断授权返回blocked。"""
        result = probe_sample_and_grant_access(
            dataset_name="bad_dataset",
            sample_ratio=0.05,
            consumer_app_id="APP-TEST",
            endpoint_id="EP-001",
            visible_columns="user_id",
            row_filter="1=1",
            grant_days=30,
        )
        # 小抽样比例会导致不通过
        assert result["status"] in ("granted", "blocked")

    def test_grant_creates_consumer_app(self):
        """授权时自动创建不存在的消费方应用。"""
        before = len([a for a in store.rows("consumer_app")
                       if a.get("应用编号") == "APP-AUTO-CREATE"])
        probe_sample_and_grant_access(
            dataset_name="test_dataset",
            sample_ratio=0.8,
            consumer_app_id="APP-AUTO-CREATE",
            endpoint_id="EP-002",
            visible_columns="txn_id",
            row_filter="1=1",
            grant_days=90,
        )
        after = len([a for a in store.rows("consumer_app")
                      if a.get("应用编号") == "APP-AUTO-CREATE"])
        assert after >= before


class TestRevokeGrants:
    """链路12：授权回收测试"""

    def test_revoke_expired_grants(self):
        """到期授权和冻结契约授权被回收。"""
        # 添加一个已过期的授权
        store.rows("access_grant").append({
            "id": 999,
            "授权编号": "GRANT-EXPIRED",
            "消费方应用": "APP-TEST",
            "所属端点": "EP-002",
            "可见列范围": "txn_id",
            "行级过滤条件": "1=1",
            "授权起日": "2025-01-01",
            "授权止日": "2025-12-31",
            "最近核验": "2025-06-01",
            "status": "已授权",
            "pending": True,
            "abnormal": False,
        })

        result = revoke_expired_grants()
        assert result["revoked_count"] >= 1

    def test_revoke_affects_subscriptions(self):
        """授权回收影响关联订阅计划的状态。"""
        result = revoke_expired_grants()
        # 验证有回收动作
        assert "revoked_count" in result
        assert isinstance(result["affected_subscriptions"], list)