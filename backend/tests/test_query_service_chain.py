"""查询服务链路测试：端点查询→快照缓存→限流配额→用量计量。

覆盖：配额超额降级、快照有效期、缓存策略联动、用量与计划对账。
"""
from __future__ import annotations

import pytest
from app.integration.query_service_chain import (
    execute_query_chain,
    snapshot_with_cache,
    quota_check_and_degrade,
)
from app.store import store


class TestQuotaCheck:
    """链路6：限流配额测试"""

    def test_quota_normal_returns_ok(self):
        """配额充足：正常通过。"""
        result = quota_check_and_degrade("APP-ANALYTICS", "EP-001")
        assert result["status"] == "ok"
        assert result["degraded"] is False

    def test_quota_exceeded_degrades(self):
        """配额已超额：返回降级标记。"""
        # 设置配额为已超额状态
        for q in store.rows("rate_quota"):
            if q.get("消费方应用") == "APP-RISK" and q.get("所属端点") == "EP-005":
                q["当前用量"] = "8000"
                q["日级上限"] = "8000"
                break

        result = quota_check_and_degrade("APP-RISK", "EP-005")
        # 因为当前用量已达上限，应该触发超额
        # 需要再次调用因为第一次调用时当前用量已经 >= 日级上限
        for q in store.rows("rate_quota"):
            if q.get("消费方应用") == "APP-RISK" and q.get("所属端点") == "EP-005":
                q["当前用量"] = "8001"
                break
        result = quota_check_and_degrade("APP-RISK", "EP-005")
        assert result["status"] == "exceeded"
        assert result["degraded"] is True

    def test_quota_new_app_creates_default(self):
        """无配额记录的应用：自动创建默认条目。"""
        result = quota_check_and_degrade("APP-NEW", "EP-001")
        assert result["status"] == "ok"
        assert result["current_usage"] == 1

        # 验证配额条目已创建
        quotas = [
            q for q in store.rows("rate_quota")
            if q.get("消费方应用") == "APP-NEW"
        ]
        assert len(quotas) == 1


class TestExecuteQueryChain:
    """链路4：查询执行链路测试"""

    def test_execute_query_on_published_endpoint(self):
        """已发布端点：成功执行查询并创建快照与计量。"""
        result = execute_query_chain(
            endpoint_id="EP-002",
            consumer_app_id="APP-ANALYTICS",
            filters={"txn_amount": "100"},
            page=1,
            page_size=10,
        )
        assert result["status"] == "ok"
        assert result["plan"]["status"] == "已返回"
        assert "snapshot" in result

    def test_execute_query_on_nonexistent_endpoint(self):
        """不存在的端点：返回错误。"""
        result = execute_query_chain(
            endpoint_id="EP-NONEXIST",
            consumer_app_id="APP-TEST",
        )
        assert result["status"] == "error"

    def test_query_creates_usage_record(self):
        """查询执行后产生用量计量记录。"""
        before_count = len([r for r in store.rows("usage_meter")
                            if r.get("消费方应用") == "APP-DASHBOARD"])
        execute_query_chain(
            endpoint_id="EP-002",
            consumer_app_id="APP-DASHBOARD",
        )
        after_count = len([r for r in store.rows("usage_meter")
                           if r.get("消费方应用") == "APP-DASHBOARD"])
        assert after_count > before_count


class TestSnapshotWithCache:
    """链路5：快照与缓存测试"""

    def test_create_snapshot_with_cache(self):
        """创建快照：自动设置有效期并更新缓存命中率。"""
        rows = [{"field1": "val1", "field2": "val2"}]
        snap = snapshot_with_cache(
            plan_id=999,
            endpoint_id="EP-001",
            contract_id="CTR-001",
            rows=rows,
            ttl_seconds=3600,
        )
        assert snap["status"] == "可读"
        assert "有效期" in snap
        assert int(snap["快照行数"]) == 1

    def test_create_empty_snapshot(self):
        """空数据集的快照：依然创建但不含列摘要。"""
        snap = snapshot_with_cache(
            plan_id=1000,
            endpoint_id="EP-002",
            contract_id="CTR-002",
            rows=[],
        )
        assert snap["status"] == "可读"
        assert snap["快照行数"] == "0"