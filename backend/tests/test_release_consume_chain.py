"""发布撤回—订阅消费交接链路测试。

还原题述冲突：发布人员撤回数据集 A 的 v2 批次时，数据集 B 的 v2 批次
正在供数，A 的替代发布与撤回操作在同一批次的消费交接上发生冲突；
随后两个消费方应用各发一个取数请求，核验 B 继续供数、A 走替代发布
或进入明确等候。

覆盖修复点：
- 撤回按订阅实际依赖的发布批次暂停，不再仅凭同版本号误伤其他数据集订阅；
- 取数记录按实际发布批次查询，并关联本次实际使用的发布；
- 已撤回批次不能再交付任何新取数；
- 撤回重试不覆盖已凭独立有效发布恢复的订阅；
- 无替代批次时订阅暂停并保留可核验的等候原因。
"""
from __future__ import annotations

import pytest

from app.integration.release_consume_chain import (
    withdraw_release,
    restore_subscription_with_release,
    submit_fetch_request,
    query_fetch_records_by_release,
    query_fetch_records_by_subscription,
)
from app.services.dataset_release import DatasetReleaseService
from app.services.subscription_plan import SubscriptionPlanService
from app.store import store


def _make_release(release_id: int, dataset: str, version: str, scope: str) -> dict:
    row = {
        "id": release_id,
        "发布编号": f"REL-{release_id:04d}",
        "数据集名称": dataset,
        "绑定版本": version,
        "数据行数": "1000",
        "对账结论": "已平账",
        "可订阅范围": scope,
        "发布标签": "正式",
        "发布时间": f"2026-11-2{release_id} 10:00:00",
        "status": "已发布",
        "pending": False,
        "abnormal": False,
    }
    store.rows("dataset_release").append(row)
    return row


def _make_subscription(sub_id: int, app_id: str, version: str, backing_id: int) -> dict:
    row = {
        "id": sub_id,
        "订阅编号": f"SUB-T{sub_id}",
        "消费方应用": app_id,
        "所属契约": f"CTR-T{sub_id}",
        "订阅版本": version,
        "取数频率": "实时",
        "配额上限": "10000",
        "订阅起日": "2026-11-01",
        "最近取数": "",
        "status": "生效中",
        "pending": True,
        "abnormal": False,
        "_backing_release_id": backing_id,
    }
    store.rows("subscription_plan").append(row)
    return row


@pytest.fixture()
def conflict_scene():
    """构造 A/B 两个数据集同为 v2、各自有独立发布与订阅的冲突现场。"""
    rel_a = _make_release(101, "dataset_A", "v2", "APP-A")
    rel_b = _make_release(102, "dataset_B", "v2", "APP-B")
    rel_a_replacement = _make_release(103, "dataset_A_alt", "v2", "APP-A")
    sub_a = _make_subscription(201, "APP-A", "v2", backing_id=101)
    sub_b = _make_subscription(202, "APP-B", "v2", backing_id=102)
    return {
        "rel_a": rel_a,
        "rel_b": rel_b,
        "rel_a_replacement": rel_a_replacement,
        "sub_a": sub_a,
        "sub_b": sub_b,
    }


class TestWithdrawScoping:
    """撤回只影响真正依赖该发布批次的订阅。"""

    def test_withdraw_a_v2_does_not_suspend_b_v2(self, conflict_scene):
        """B 的 v2 是独立发布批次，撤回 A 的 v2 不得暂停 B。"""
        result = withdraw_release(conflict_scene["rel_a"]["id"])

        assert result["status"] == "withdrawn"
        assert conflict_scene["rel_a"]["status"] == "已撤回"
        assert conflict_scene["rel_b"]["status"] == "已发布"

        sub_b = store.find("subscription_plan", conflict_scene["sub_b"]["id"])
        assert sub_b["status"] == "生效中"
        assert sub_b["_backing_release_id"] == conflict_scene["rel_b"]["id"]
        assert str(sub_b["订阅编号"]) in result["untouched_subscriptions"]

    def test_withdraw_rebounds_to_independent_valid_release(self, conflict_scene):
        """A 有同版本独立有效发布时，撤回交接直接改绑，订阅保持生效。"""
        result = withdraw_release(conflict_scene["rel_a"]["id"])

        assert result["rebound_subscriptions"] == 1
        assert result["suspended_subscriptions"] == 0
        sub_a = store.find("subscription_plan", conflict_scene["sub_a"]["id"])
        assert sub_a["status"] == "生效中"
        assert sub_a["_backing_release_id"] == conflict_scene["rel_a_replacement"]["id"]
        assert sub_a["_backing_release_no"] == conflict_scene["rel_a_replacement"]["发布编号"]

    def test_withdraw_suspends_when_no_replacement(self):
        """无替代发布时仅暂停依赖该批次的订阅并写明等候原因。"""
        rel_a = _make_release(301, "dataset_A", "v2", "APP-A")
        rel_b = _make_release(302, "dataset_B", "v2", "APP-B")
        sub_a = _make_subscription(401, "APP-A", "v2", backing_id=301)
        sub_b = _make_subscription(402, "APP-B", "v2", backing_id=302)

        result = withdraw_release(rel_a["id"])

        assert result["suspended_subscriptions"] == 1
        assert result["rebound_subscriptions"] == 0
        assert store.find("subscription_plan", sub_a["id"])["status"] == "已暂停"
        reason = store.find("subscription_plan", sub_a["id"])["_waiting_reason"]
        assert "已撤回" in reason and "有效发布" in reason
        # B 同版本但不同批次，依旧生效
        assert store.find("subscription_plan", sub_b["id"])["status"] == "生效中"


class TestFetchByActualRelease:
    """取数按实际发布批次交付，取数记录关联实际发布。"""

    def test_b_keeps_serving_after_a_withdrawn(self, conflict_scene):
        """撤回 A 后，B 的应用取数仍走 B 的发布批次。"""
        withdraw_release(conflict_scene["rel_a"]["id"])

        result = submit_fetch_request(conflict_scene["sub_b"]["id"], 200)
        assert result["status"] == "fetched"
        assert result["release"]["id"] == conflict_scene["rel_b"]["id"]

        records = query_fetch_records_by_release(conflict_scene["rel_b"]["id"])
        assert len(records) == 1
        assert records[0]["关联发布编号"] == conflict_scene["rel_b"]["发布编号"]
        assert records[0]["消费方应用"] == "APP-B"
        assert records[0]["交付行数"] == 200

    def test_a_fetches_replacement_release_after_handover(self, conflict_scene):
        """A 的应用取数时实际交付的是替代发布批次而非已撤回批次。"""
        withdraw_release(conflict_scene["rel_a"]["id"])

        result = submit_fetch_request(conflict_scene["sub_a"]["id"], 150)
        assert result["status"] == "fetched"
        assert result["release"]["id"] == conflict_scene["rel_a_replacement"]["id"]
        assert result["release"]["id"] != conflict_scene["rel_a"]["id"]

        records = query_fetch_records_by_subscription(conflict_scene["sub_a"]["id"])
        assert len(records) == 1
        assert records[0]["关联发布id"] == conflict_scene["rel_a_replacement"]["id"]
        # 撤回批次名下没有任何新取数记录
        assert query_fetch_records_by_release(conflict_scene["rel_a"]["id"]) == []

    def test_withdrawn_release_can_never_serve_new_fetch(self):
        """任一新取数不能再交付已撤回批次的数据。"""
        rel = _make_release(501, "dataset_X", "v2", "APP-X")
        sub = _make_subscription(601, "APP-X", "v2", backing_id=501)

        withdraw_release(rel["id"])
        # 撤回后没有同版本替代发布，订阅先被暂停，取数被阻断而非交付撤回数据
        result = submit_fetch_request(sub["id"], 100)
        assert result["status"] == "blocked"
        assert result["reason"].startswith("订阅当前状态为已暂停")
        assert "已撤回" in result["waiting_reason"]
        assert "有效发布" in result["waiting_reason"]
        assert query_fetch_records_by_release(rel["id"]) == []

        # 即使绕过状态门强行把订阅改回生效，发布查询也解析不到撤回批次
        store.find("subscription_plan", sub["id"])["status"] = "生效中"
        result2 = submit_fetch_request(sub["id"], 100)
        assert result2["status"] == "blocked"
        assert "无有效发布批次" in result2["reason"]
        assert query_fetch_records_by_release(rel["id"]) == []

        # 直接尝试把取数记录挂到已撤回批次也必须被拒绝
        service = SubscriptionPlanService()
        forced = service.record_fetch(str(sub["id"]), 10, release_id=rel["id"])
        assert forced["status"] == "error"
        assert "已撤回" in forced["message"]

    def test_suspended_subscription_fetch_returns_waiting_reason(self):
        """暂停订阅取数返回明确等候原因，订阅列表与可取批次不再错位。"""
        rel = _make_release(701, "dataset_Y", "v2", "APP-Y")
        sub = _make_subscription(801, "APP-Y", "v2", backing_id=701)
        withdraw_release(rel["id"])

        result = submit_fetch_request(sub["id"], 50)
        assert result["status"] == "blocked"
        assert result["waiting_reason"]
        assert "已撤回" in result["waiting_reason"]


class TestWithdrawRetry:
    """撤回重试不得覆盖已凭独立有效发布恢复的订阅。"""

    def test_retry_does_not_overwrite_restored_subscription(self, conflict_scene):
        rel_a = conflict_scene["rel_a"]
        sub_a_id = conflict_scene["sub_a"]["id"]
        replacement = conflict_scene["rel_a_replacement"]

        # 第一次撤回：存在替代发布，A 已改绑恢复为生效
        first = withdraw_release(rel_a["id"])
        assert first["rebound_subscriptions"] == 1
        sub_a = store.find("subscription_plan", sub_a_id)
        assert sub_a["_backing_release_id"] == replacement["id"]

        # 模拟撤回重试（再次调用撤回入口）
        retry = withdraw_release(rel_a["id"])
        assert retry["retried"] is True
        sub_a_after = store.find("subscription_plan", sub_a_id)
        assert sub_a_after["status"] == "生效中"
        assert sub_a_after["_backing_release_id"] == replacement["id"]
        assert retry["suspended_subscriptions"] == 0

    def test_explicit_restore_then_retry_keeps_restored_state(self):
        """先撤回暂停、再凭替代发布显式恢复，之后重试撤回不能再暂停它。"""
        rel = _make_release(901, "dataset_Z", "v2", "APP-Z")
        sub = _make_subscription(951, "APP-Z", "v2", backing_id=901)
        # 撤回时还没有替代发布 → 暂停
        withdraw_release(rel["id"])
        assert store.find("subscription_plan", sub["id"])["status"] == "已暂停"

        # 之后发布人员补发同版本独立有效发布并恢复订阅
        replacement = _make_release(902, "dataset_Z_fix", "v2", "APP-Z")
        restore_result = restore_subscription_with_release(sub["id"], replacement["id"])
        assert restore_result["status"] == "restored"
        restored = store.find("subscription_plan", sub["id"])
        assert restored["status"] == "生效中"
        assert restored["_backing_release_id"] == replacement["id"]

        # 撤回重试不得覆盖恢复结果
        retry = withdraw_release(rel["id"])
        again = store.find("subscription_plan", sub["id"])
        assert again["status"] == "生效中"
        assert again["_backing_release_id"] == replacement["id"]
        assert retry["suspended_subscriptions"] == 0

        # 恢复后取数走的是替代发布
        fetch = submit_fetch_request(sub["id"], 88)
        assert fetch["status"] == "fetched"
        assert fetch["release"]["id"] == replacement["id"]

    def test_restore_rejects_wrong_version_release(self):
        """替代发布版本与订阅版本不一致时拒绝恢复。"""
        rel = _make_release(1001, "dataset_W", "v2", "APP-W")
        sub = _make_subscription(1051, "APP-W", "v2", backing_id=1001)
        withdraw_release(rel["id"])
        wrong = _make_release(1002, "dataset_W_v3", "v3", "APP-W")

        result = restore_subscription_with_release(sub["id"], wrong["id"])
        assert result["status"] == "error"
        assert store.find("subscription_plan", sub["id"])["status"] == "已暂停"


class TestLegacyAndActionEntry:
    """历史订阅兼容与资源动作入口的交接行为。"""

    def test_legacy_subscription_without_binding_uses_scope_not_version_only(self):
        """未显式绑定发布的历史订阅，版本+范围同时命中才算依赖。"""
        rel_a = _make_release(1101, "dataset_A", "v2", "APP-A")
        rel_b = _make_release(1102, "dataset_B", "v2", "APP-B")
        # 历史订阅没有 _backing_release_id
        store.rows("subscription_plan").append({
            "id": 1201, "订阅编号": "SUB-LEG-A", "消费方应用": "APP-A",
            "所属契约": "CTR-LA", "订阅版本": "v2", "取数频率": "实时",
            "配额上限": "100", "订阅起日": "2026-11-01", "最近取数": "",
            "status": "生效中", "pending": True, "abnormal": False,
        })
        store.rows("subscription_plan").append({
            "id": 1202, "订阅编号": "SUB-LEG-B", "消费方应用": "APP-B",
            "所属契约": "CTR-LB", "订阅版本": "v2", "取数频率": "实时",
            "配额上限": "100", "订阅起日": "2026-11-01", "最近取数": "",
            "status": "生效中", "pending": True, "abnormal": False,
        })

        result = withdraw_release(rel_a["id"])
        # 只有 APP-A 的历史订阅被暂停，APP-B 同版本但范围不命中
        assert "SUB-LEG-A" in result["suspended"]
        assert "SUB-LEG-B" in result["untouched_subscriptions"]
        assert store.find("subscription_plan", 1202)["status"] == "生效中"

    def test_run_action_withdraw_goes_through_handover(self, conflict_scene):
        """资源动作入口的「撤回发布」必须走完整订阅交接而非只改状态。"""
        service = DatasetReleaseService()
        entry, message = service.run_action(conflict_scene["rel_a"]["id"], "撤回发布")
        assert entry["status"] == "已撤回"
        assert "交接" in message
        sub_b = store.find("subscription_plan", conflict_scene["sub_b"]["id"])
        assert sub_b["status"] == "生效中"

    def test_published_release_query_excludes_withdrawn(self, conflict_scene):
        """有效发布查询不返回已撤回批次，取数侧拿不到撤回数据。"""
        service = DatasetReleaseService()
        before = service.find_published_releases(version_id="v2")
        assert {r["id"] for r in before} == {
            conflict_scene["rel_a"]["id"],
            conflict_scene["rel_b"]["id"],
            conflict_scene["rel_a_replacement"]["id"],
        }
        withdraw_release(conflict_scene["rel_a"]["id"])
        after = service.find_published_releases(version_id="v2")
        assert conflict_scene["rel_a"]["id"] not in {r["id"] for r in after}
