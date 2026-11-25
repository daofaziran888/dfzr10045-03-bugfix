"""数据集发布领域服务：把通过对账的数据集按版本发布给可订阅范围。

发布前校验对账结论必须平账、抽样探查必须通过，发布后订阅计划才能
读到该批次数据集；撤回发布时按“订阅实际依赖的发布批次”做消费交接，
只暂停真正失去取数依据的订阅，并记录发布水位。

状态流转约定：
- 订阅通过 ``_backing_release_id`` 显式绑定当前供数的发布批次，撤回判断
  不再只按版本号一刀切，避免误伤同版本的其他数据集订阅；
- 撤回后存在同版本独立有效发布可交接时，订阅直接改绑新批次、保持生效；
- 撤回重试只处理仍依赖该撤回批次的订阅，已凭独立发布恢复的订阅不受影响。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

# 视为全员可订阅的范围标识
_WIDE_SCOPES = {"全部", "ALL", "*", ""}


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

    # ------------------------------------------------------------------
    # 发布批次查询：取数与撤回交接都必须落到“实际发布批次”上
    # ------------------------------------------------------------------
    def get_release(self, release_id: int) -> dict[str, Any] | None:
        """按发布批次主键查询实际发布记录。"""
        return store.find(self.MODULE, int(release_id))

    def find_published_releases(
        self,
        *,
        version_id: str | None = None,
        dataset_name: str | None = None,
        consumer_app_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """按版本/数据集/消费方范围查询当前仍有效的发布批次。

        已撤回批次永远不会出现在结果里，因此任何新取数都无法再交付
        已撤回批次的数据。
        """
        candidates = [r for r in store.rows(self.MODULE) if r.get("status") == "已发布"]
        if version_id is not None:
            candidates = [r for r in candidates if r.get("绑定版本") == version_id]
        if dataset_name is not None:
            candidates = [r for r in candidates if r.get("数据集名称") == dataset_name]
        if consumer_app_id is not None:
            candidates = [
                r for r in candidates
                if self._scope_covers(r.get("可订阅范围", ""), consumer_app_id)
            ]
        return candidates

    def find_published_release(
        self,
        *,
        version_id: str,
        dataset_name: str | None = None,
        consumer_app_id: str | None = None,
    ) -> dict[str, Any] | None:
        """查询单个有效发布批次：优先同数据集，再按发布时间水位取最新。"""
        candidates = self.find_published_releases(
            version_id=version_id, dataset_name=dataset_name, consumer_app_id=consumer_app_id,
        )
        if not candidates:
            return None
        return self._latest_release(candidates, prefer_dataset=dataset_name)

    def find_replacement_for_subscription(
        self,
        subscription: dict[str, Any],
        withdrawn_release: dict[str, Any],
    ) -> dict[str, Any] | None:
        """为失去发布依据的订阅寻找可交接的独立有效发布。

        必须是不同于撤回批次的另一条已发布记录，版本与订阅版本一致且
        可订阅范围覆盖该消费方；优先同一数据集的替代发布。
        """
        candidates = [
            r for r in self.find_published_releases(
                version_id=subscription.get("订阅版本"),
                consumer_app_id=subscription.get("消费方应用"),
            )
            if int(r.get("id", 0)) != int(withdrawn_release.get("id", 0))
        ]
        if not candidates:
            return None
        return self._latest_release(
            candidates, prefer_dataset=withdrawn_release.get("数据集名称"),
        )

    # ------------------------------------------------------------------
    # 撤回入口：发布撤回 → 订阅消费交接的完整状态流转
    # ------------------------------------------------------------------
    def withdraw(self, release_id: int) -> dict[str, Any]:
        """撤回发布批次并按订阅实际依赖的批次做消费交接。

        只有当前仍以该发布批次为取数依据的生效订阅才会被处理：
        能改绑同版本独立有效发布的保持生效，其余暂停并记录等候原因；
        依赖其他发布批次（如同版本的别的数据集）的订阅不受影响。
        撤回重试具有幂等性，不会覆盖已凭独立有效发布恢复的订阅。
        """
        release = store.find(self.MODULE, int(release_id))
        if release is None:
            return {"status": "error", "message": "发布批次不存在"}

        if release.get("status") == "已撤回":
            return self._retry_withdraw(release)

        release["status"] = "已撤回"
        release["abnormal"] = True
        return self._handoff_after_withdraw(release, retried=False)

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """资源动作入口：撤回发布必须走订阅消费交接，而非只改批次状态。"""
        if action == "撤回发布":
            result = self.withdraw(entry_id)
            if result.get("status") == "error":
                return None, result["message"]
            entry = store.find(self.MODULE, int(entry_id))
            message = "发布批次已撤回，订阅消费交接完成"
            if result.get("retried"):
                message = "发布批次已处于撤回态，重试未覆盖已恢复的订阅"
            return entry, message
        return super().run_action(entry_id, action)

    def _retry_withdraw(self, release: dict[str, Any]) -> dict[str, Any]:
        """撤回重试：只对仍依赖该撤回批次的生效订阅做防御性交接。

        已通过替代发布恢复的订阅其 ``_backing_release_id`` 已指向独立
        有效发布，不会再被这里识别为依赖方，因此状态不会被覆盖。
        """
        result = self._handoff_after_withdraw(release, retried=True)
        result["retried"] = True
        return result

    def _handoff_after_withdraw(
        self, release: dict[str, Any], *, retried: bool,
    ) -> dict[str, Any]:
        from app.services.subscription_plan import SubscriptionPlanService

        sub_service = SubscriptionPlanService()
        suspended: list[str] = []
        rebound: list[str] = []
        untouched: list[str] = []

        for sub in store.rows("subscription_plan"):
            if not self._depends_on_release(sub, release):
                continue

            replacement = self.find_replacement_for_subscription(sub, release)
            if replacement is not None:
                # 同一批次消费交接冲突时，独立有效发布直接接管，订阅不中断
                sub_service.bind_release(sub, replacement, source="撤回批次替代交接")
                rebound.append(str(sub.get("订阅编号")))
                continue

            sub_service.suspend_for_withdraw(sub, release)
            suspended.append(str(sub.get("订阅编号")))

        # 同版本但依赖其他发布批次的订阅仅做核验留痕，状态一律不动
        for sub in store.rows("subscription_plan"):
            if (
                sub.get("订阅版本") == release.get("绑定版本")
                and str(sub.get("订阅编号")) not in suspended + rebound
            ):
                untouched.append(str(sub.get("订阅编号")))

        return {
            "status": "withdrawn",
            "retried": retried,
            "release_id": release.get("id"),
            "release_no": release.get("发布编号"),
            "suspended_subscriptions": len(suspended),
            "suspended": suspended,
            "rebound_subscriptions": len(rebound),
            "rebound": rebound,
            "untouched_subscriptions": untouched,
        }

    def _depends_on_release(
        self, sub: dict[str, Any], release: dict[str, Any],
    ) -> bool:
        """判断订阅当前是否真正依赖该发布批次供数。"""
        if sub.get("status") != "生效中":
            return False
        backing_id = sub.get("_backing_release_id")
        if backing_id not in (None, ""):
            return int(backing_id) == int(release.get("id", 0))
        # 历史订阅没有显式绑定时，版本与可订阅范围同时命中才算依赖，
        # 不能再仅凭同版本号暂停别的数据集订阅
        return (
            sub.get("订阅版本") == release.get("绑定版本")
            and self._scope_covers(
                release.get("可订阅范围", ""), sub.get("消费方应用", ""),
            )
        )

    @staticmethod
    def _scope_covers(scope: str, consumer_app_id: str) -> bool:
        """校验发布批次的可订阅范围是否覆盖该消费方应用。"""
        scope = str(scope or "").strip()
        if scope in _WIDE_SCOPES:
            return True
        scoped = {item.strip() for item in scope.split(",") if item.strip()}
        return consumer_app_id in scoped

    @staticmethod
    def _latest_release(
        candidates: list[dict[str, Any]], *, prefer_dataset: str | None,
    ) -> dict[str, Any]:
        return max(
            candidates,
            key=lambda r: (
                1 if prefer_dataset and r.get("数据集名称") == prefer_dataset else 0,
                str(r.get("发布时间", "")),
                int(r.get("id", 0)),
            ),
        )

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


def publish_after_precheck(dataset_name: str, version_id: str, row_count: int,
                           scope: str, tag: str) -> dict:
    """模块级入口：发布准入校验后落库发布批次数据集。"""
    service = DatasetReleaseService()
    precondition = service.check_release_precondition(dataset_name)
    if not precondition["allowed"]:
        return {"status": "blocked", "reasons": precondition["blocked_reasons"]}
    result = service.publish(dataset_name, version_id, row_count, scope, tag)
    result["latest"] = service.find_latest_release(dataset_name)
    return result
