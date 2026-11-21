"""发布与口径对账链路测试：数据集发布→口径对账→双跑比对→差异归因。

用真实的两侧来源数据集验证逐行对账、匹配/差异行数计算、平账判定、
差异登记阻断发布、双跑收敛判定与偏离逐条归因。
"""
from __future__ import annotations

import pytest
from app.integration.release_reconcile_chain import (
    release_dataset_with_reconcile,
    dual_run_and_attribute,
)
from app.services.reconcile_task import ReconcileTaskService
from app.services.dual_run import DualRunService
from app.services.diff_attrib import DiffAttribService
from app.store import store


def _clean_rows():
    """两侧完全一致的干净数据集。"""
    left = [
        {"txn_id": "T1", "amount": "100", "merchant": "M1"},
        {"txn_id": "T2", "amount": "200", "merchant": "M2"},
        {"txn_id": "T3", "amount": "300", "merchant": "M3"},
    ]
    right = [dict(r) for r in left]
    return left, right


def _dirty_rows():
    """右侧存在字段偏离与缺失行的脏数据集。"""
    left = [
        {"txn_id": "T1", "amount": "100", "merchant": "M1"},
        {"txn_id": "T2", "amount": "200", "merchant": "M2"},
        {"txn_id": "T3", "amount": "300", "merchant": "M3"},
        {"txn_id": "T4", "amount": "400", "merchant": "M4"},
    ]
    right = [
        {"txn_id": "T1", "amount": "100", "merchant": "M1"},
        {"txn_id": "T2", "amount": "250", "merchant": "M2"},  # amount 偏离
        {"txn_id": "T3", "amount": "300", "merchant": "M3"},
        # T4 右侧缺失
    ]
    return left, right


class TestReconcileService:
    """口径对账领域服务的逐行对账能力"""

    def test_reconcile_clean_rows_all_matched(self):
        """干净数据集：全部匹配，差异为零，判定已平账。"""
        left, right = _clean_rows()
        service = ReconcileTaskService()
        result = service.reconcile_rows(left, right, key_fields=["txn_id"])
        assert result["matched_rows"] == 3
        assert result["diff_rows"] == 0
        assert service.judge_settlement(result["matched_rows"], result["diff_rows"]) == "已平账"

    def test_reconcile_dirty_rows_detects_diff(self):
        """脏数据集：检出字段偏离与右侧缺失两类差异。"""
        left, right = _dirty_rows()
        service = ReconcileTaskService()
        result = service.reconcile_rows(left, right, key_fields=["txn_id"])
        assert result["matched_rows"] == 2
        assert result["diff_rows"] == 2
        assert service.judge_settlement(result["matched_rows"], result["diff_rows"]) == "存在差异"
        diff_types = {d["diff_type"] for d in result["diff_details"]}
        assert "字段不一致" in diff_types
        assert "右侧缺失" in diff_types

    def test_build_reconcile_record_persists(self):
        """对账记录落库：写入匹配/差异行数与对账窗口。"""
        left, right = _clean_rows()
        service = ReconcileTaskService()
        record = service.build_reconcile_record(
            reconcile_id="RECON-TEST-CLEAN",
            left_source="src-a", right_source="src-b",
            left_rows=left, right_rows=right, key_fields=["txn_id"],
        )
        assert record["status"] == "已平账"
        assert record["匹配行数"] == "3"
        assert record["差异行数"] == "0"
        found = service.find_by_reconcile_id("RECON-TEST-CLEAN")
        assert found is not None


class TestDatasetRelease:
    """链路9：数据集发布准入"""

    def test_release_clean_dataset_succeeds(self):
        """对账平账且探查通过：数据集成功发布。"""
        # 预置一个已通过的探查记录满足准入
        store.rows("sample_probe").append({
            "id": 901, "样本编号": "PROBE-CLEAN", "所属数据集": "clean_dataset",
            "抽样比例": "20%", "抽样行数": "3", "字段完整率": "100%",
            "异常值条数": "0", "探查结论": "通过", "探查时间": "2026-11-21",
            "status": "已通过", "pending": False, "abnormal": False,
        })
        left, right = _clean_rows()
        result = release_dataset_with_reconcile(
            dataset_name="clean_dataset", version_id="v1.0",
            left_rows=left, right_rows=right, key_fields=["txn_id"],
            subscribe_scope="APP-ANALYTICS", release_tag="正式",
        )
        assert result["status"] == "released"
        assert result["release"]["数据行数"] == "3"

    def test_release_blocked_by_diff(self):
        """对账存在差异：阻断发布并登记差异批次。"""
        left, right = _dirty_rows()
        result = release_dataset_with_reconcile(
            dataset_name="dirty_dataset", version_id="v1.0",
            left_rows=left, right_rows=right, key_fields=["txn_id"],
            subscribe_scope="APP-ANALYTICS", release_tag="灰度",
        )
        assert result["status"] == "blocked"
        assert result["reconcile"]["status"] == "存在差异"
        assert result["diff_registered"]["diff_count"] == 2


class TestDualRunAttribute:
    """链路10：双跑比对与差异归因"""

    def test_dual_run_converged_no_attribution(self):
        """新旧口径完全一致：已收敛，无归因条目。"""
        left, right = _clean_rows()
        result = dual_run_and_attribute(
            reconcile_id="RECON-DUAL-CLEAN",
            old_caliber_version="v1.0", new_caliber_version="v2.0",
            old_rows=left, new_rows=right, key_fields=["txn_id"],
            compare_fields=["amount", "merchant"],
        )
        assert result["consistent_rows"] == 3
        assert result["divergent_rows"] == 0
        assert result["dual_run"]["status"] == "已收敛"
        assert result["attributions"] == []

    def test_dual_run_divergent_creates_attributions(self):
        """新旧口径偏离：检出偏离并逐条归因到字段。"""
        old_rows = [
            {"id": "R1", "amount": "100", "event_time": "2026-01-01T00:00:00"},
            {"id": "R2", "amount": "200", "event_time": "2026-01-02T00:00:00"},
        ]
        new_rows = [
            {"id": "R1", "amount": "100", "event_time": "2026-01-01T08:00:00"},  # 时区偏移
            {"id": "R2", "amount": "250", "event_time": "2026-01-02T08:00:00"},  # 金额+时区
        ]
        result = dual_run_and_attribute(
            reconcile_id="RECON-DUAL-DIRTY",
            old_caliber_version="v1.0", new_caliber_version="v2.0",
            old_rows=old_rows, new_rows=new_rows, key_fields=["id"],
            compare_fields=["amount", "event_time"],
        )
        assert result["divergent_rows"] == 2
        assert len(result["attributions"]) == 2
        # 偏离超限（2/2 > 0.2）
        assert result["dual_run"]["status"] == "偏离超限"

    def test_diff_attrib_classifies_time_field(self):
        """差异归因：时间字段归类为时区转换。"""
        service = DiffAttribService()
        category, root = service.classify_divergence("event_time")
        assert category == "时区转换"

    def test_diff_attrib_classifies_amount_field(self):
        """差异归因：金额字段归类为精度差异。"""
        service = DiffAttribService()
        category, root = service.classify_divergence("txn_amount")
        assert category == "精度差异"


class TestDualRunService:
    """双跑比对领域服务的收敛判定"""

    def test_convergence_rate(self):
        """收敛率计算正确。"""
        service = DualRunService()
        assert service.compute_convergence_rate(80, 20) == 80.0

    def test_judge_convergence_boundary(self):
        """偏离占比恰好等于阈值判为已收敛。"""
        service = DualRunService()
        assert service.judge_convergence(80, 20) == "已收敛"
        assert service.judge_convergence(70, 30) == "偏离超限"


class TestConsumerAndSubscription:
    """订阅与消费方管理测试"""

    def test_seed_data_has_active_subscriptions(self):
        """种子数据包含生效中的订阅。"""
        active = [
            s for s in store.rows("subscription_plan")
            if s.get("status") == "生效中"
        ]
        assert len(active) >= 2

    def test_seed_data_has_connected_consumer_apps(self):
        """种子数据包含已接入的消费方应用。"""
        connected = [
            a for a in store.rows("consumer_app")
            if a.get("status") == "已接入"
        ]
        assert len(connected) >= 3
