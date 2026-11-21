"""数据集发布领域服务：把通过对账的数据集按版本发布给可订阅范围。

发布前校验对账结论必须平账、抽样探查必须通过，发布后订阅计划才能
读到该批次数据集；撤回发布时联动暂停相关订阅并记录发布水位。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class DatasetReleaseService(BaseModuleService):
    MODULE = "dataset_release"
    ENTITY = "发布批次"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["发布编号", "数据集名称", "绑定版本", "数据行数", "对账结论", "可订阅范围", "发布标签", "发布时间"]
    REQUIRED_FIELDS = ["发布编号", "数据集名称"]
    STATUS_ORDER = ["待发布", "发布中", "已发布", "已撤回"]
    ACTION_RULES = {"启动发布": "发布中", "确认发布": "已发布", "撤回发布": "已撤回"}
    NEGATIVE_ACTIONS = []

    def check_release_precondition(self, dataset_name: str) -> dict[str, Any]:
        """发布准入校验：对账平账 + 抽样探查通过缺一不可。

        读取对账任务与探查样本数据集，任一不满足返回阻断原因，
        准入结论决定发布批次能否进入发布中状态。
        """
        reconcile_ok = False
        for r in store.rows("reconcile_task"):
            if dataset_name in str(r.get("对账编号", "")):
                reconcile_ok = r.get("status") == "已平账"
                break
        probe_ok = False
        for p in store.rows("sample_probe"):
            if p.get("所属数据集") == dataset_name:
                probe_ok = p.get("status") == "已通过"
                break
        blocked: list[str] = []
        if not reconcile_ok:
            blocked.append("对账未平账")
        if not probe_ok:
            blocked.append("抽样探查未通过")
        return {"allowed": not blocked, "blocked_reasons": blocked}

    def publish(
        self,
        dataset_name: str,
        version_id: str,
        row_count: int,
        subscribe_scope: str,
        release_tag: str,
    ) -> dict[str, Any]:
        """执行发布：先做准入校验，通过后落库发布批次数据集。"""
        precondition = self.check_release_precondition(dataset_name)
        if not precondition["allowed"]:
            return {"status": "blocked", "reasons": precondition["blocked_reasons"]}

        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        release = {
            "id": new_id,
            "发布编号": f"REL-{new_id:04d}",
            "数据集名称": dataset_name,
            "绑定版本": version_id,
            "数据行数": str(row_count),
            "对账结论": "已平账",
            "可订阅范围": subscribe_scope,
            "发布标签": release_tag,
            "发布时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已发布",
            "pending": False,
            "abnormal": False,
        }
        rows.append(release)
        return {"status": "released", "release": release}

    def withdraw(self, release_id: int) -> dict[str, Any]:
        """撤回发布批次并联动暂停可订阅范围内的生效订阅。"""
        release = store.find(self.MODULE, release_id)
        if release is None:
            return {"status": "error", "message": "发布批次不存在"}
        release["status"] = "已撤回"
        release["abnormal"] = True
        suspended = 0
        for sub in store.rows("subscription_plan"):
            if sub.get("订阅版本") == release.get("绑定版本") and sub.get("status") == "生效中":
                sub["status"] = "已暂停"
                sub["abnormal"] = True
                suspended += 1
        return {"status": "withdrawn", "suspended_subscriptions": suspended}

    def get_published_datasets(self) -> list[dict[str, Any]]:
        """查询全部已发布的批次数据集，供订阅取数消费。"""
        return [r for r in store.rows(self.MODULE) if r.get("status") == "已发布"]

    def find_latest_release(self, dataset_name: str) -> dict[str, Any] | None:
        """按发布时间水位查询数据集的最新发布批次。"""
        candidates = [
            r for r in store.rows(self.MODULE)
            if r.get("数据集名称") == dataset_name and r.get("status") == "已发布"
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: str(r.get("发布时间", "")))
