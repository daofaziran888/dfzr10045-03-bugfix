"""订阅计划领域服务：维护消费方对契约版本的订阅关系与取数配额。

订阅版本决定消费方能读到哪一份契约数据，取数频率驱动查询调度，
配额上限约束单次取数的数据集规模。订阅是查询端点取数的准入前提。

关键约定：
- 每份生效订阅通过 ``_backing_release_id`` 绑定当前实际供数的发布批次，
  取数记录（``fetch_record`` 表）同样关联实际使用的发布，撤回后无法
  再凭旧批次取数；
- 发布撤回只通过 :meth:`suspend_for_withdraw` 暂停失去依据的订阅，
  替代发布通过 :meth:`restore_with_replacement` 显式恢复，撤回重试
  不得覆盖已经凭独立有效发布恢复的订阅状态。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

# 取数记录落库的内存表名
FETCH_RECORD_TABLE = "fetch_record"


class SubscriptionPlanService(BaseModuleService):
    MODULE = "subscription_plan"
    ENTITY = "订阅计划"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["订阅编号", "消费方应用", "所属契约", "订阅版本", "取数频率", "配额上限", "订阅起日", "最近取数"]
    REQUIRED_FIELDS = ["订阅编号", "消费方应用", "所属契约"]
    STATUS_ORDER = ["待生效", "生效中", "已暂停", "已到期"]
    ACTION_RULES = {"启效订阅": "生效中", "暂停订阅": "已暂停", "终止订阅": "已到期"}
    NEGATIVE_ACTIONS = []

    # ------------------------------------------------------------------
    # 订阅与实际发布批次的绑定 / 交接
    # ------------------------------------------------------------------
    def bind_release(
        self,
        subscription: dict[str, Any],
        release: dict[str, Any],
        *,
        source: str = "取数绑定",
    ) -> dict[str, Any]:
        """把订阅的取数依据绑定到一条实际有效的发布批次。"""
        subscription["_backing_release_id"] = int(release.get("id", 0))
        subscription["_backing_release_no"] = release.get("发布编号", "")
        subscription["_backing_dataset"] = release.get("数据集名称", "")
        subscription["_release_bind_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subscription["_release_bind_source"] = source
        # 改绑到独立有效发布即恢复供数
        if subscription.get("status") != "生效中":
            subscription["status"] = "生效中"
        subscription["abnormal"] = False
        subscription.pop("_waiting_reason", None)
        return subscription

    def suspend_for_withdraw(
        self,
        subscription: dict[str, Any],
        withdrawn_release: dict[str, Any],
    ) -> dict[str, Any]:
        """发布撤回且无替代批次时暂停订阅，记录失去取数依据的等候原因。"""
        subscription["status"] = "已暂停"
        subscription["abnormal"] = True
        subscription["_withdrawn_release_id"] = int(withdrawn_release.get("id", 0))
        subscription["_withdrawn_release_no"] = withdrawn_release.get("发布编号", "")
        subscription["_waiting_reason"] = (
            f"依赖的发布批次{withdrawn_release.get('发布编号', '')}已撤回，"
            f"暂无同版本有效发布可交接"
        )
        subscription.pop("_backing_release_id", None)
        subscription.pop("_backing_release_no", None)
        subscription.pop("_backing_dataset", None)
        return subscription

    def restore_with_replacement(
        self,
        subscription_id: int,
        replacement_release: dict[str, Any],
    ) -> dict[str, Any]:
        """凭独立有效发布恢复已暂停订阅，返回恢复结果。

        恢复后订阅改绑替代发布；撤回重试只处理仍依赖撤回批次的订阅，
        因此这里恢复的状态不会被后续重试覆盖。
        """
        from app.services.dataset_release import DatasetReleaseService

        sub = store.find(self.MODULE, int(subscription_id))
        if sub is None:
            return {"status": "error", "message": "订阅不存在"}
        release_service = DatasetReleaseService()
        if release_service.get_release(int(replacement_release.get("id", 0))) is None:
            return {"status": "error", "message": "替代发布不存在"}
        if replacement_release.get("status") != "已发布":
            return {"status": "error", "message": "替代发布不是有效发布状态，不能恢复供数"}
        if replacement_release.get("绑定版本") != sub.get("订阅版本"):
            return {"status": "error", "message": "替代发布版本与订阅版本不一致"}

        self.bind_release(sub, replacement_release, source="替代发布恢复")
        return {"status": "restored", "subscription": sub, "release": replacement_release}

    def resolve_backing_release(
        self, subscription: dict[str, Any], *, consumer_app_id: str | None = None,
    ) -> dict[str, Any] | None:
        """解析订阅当前实际供数的发布批次（按实际批次查询，而非按版本猜测）。

        已显式绑定的按批次主键回查；历史订阅未绑定时按版本+可订阅范围
        匹配有效发布，并在命中后补绑，保证后续撤回交接有明确依据。
        已撤回批次永远解析不出来。
        """
        from app.services.dataset_release import DatasetReleaseService

        release_service = DatasetReleaseService()
        backing_id = subscription.get("_backing_release_id")
        if backing_id not in (None, ""):
            release = release_service.get_release(int(backing_id))
            if release is not None and release.get("status") == "已发布":
                return release
            return None

        app_id = consumer_app_id or subscription.get("消费方应用", "")
        release = release_service.find_published_release(
            version_id=subscription.get("订阅版本", ""),
            consumer_app_id=app_id,
        )
        if release is not None:
            self.bind_release(subscription, release, source="首次取数补绑")
        return release

    def get_active_subscriptions(self) -> list[dict[str, Any]]:
        """查询全部生效中的订阅。"""
        return [r for r in store.rows(self.MODULE) if r.get("status") == "生效中"]

    # ------------------------------------------------------------------
    # 取数：准入 → 配额 → 按实际发布取数 → 取数记录关联实际发布
    # ------------------------------------------------------------------
    def request_fetch(
        self,
        subscription_id: int,
        requested_rows: int,
    ) -> dict[str, Any]:
        """一次取数请求的完整状态流转。

        只有生效订阅且存在有效发布批次时才能取数；配额超额按降级处理；
        取数记录关联本次实际使用的发布批次，已撤回批次无法交付数据。
        """
        sub = store.find(self.MODULE, int(subscription_id))
        if sub is None:
            return {"status": "error", "message": "订阅不存在"}
        if sub.get("status") != "生效中":
            return {
                "status": "blocked",
                "reason": f"订阅当前状态为{sub.get('status')}，不允许取数",
                "waiting_reason": sub.get("_waiting_reason", ""),
            }

        quota = self.check_quota_ceiling(str(sub.get("id")), requested_rows)
        release = self.resolve_backing_release(sub)
        if release is None:
            return {
                "status": "blocked",
                "reason": "订阅版本当前无有效发布批次可供数（依赖批次可能已撤回）",
                "waiting_reason": sub.get("_waiting_reason", ""),
            }

        delivered_rows = requested_rows
        if quota.get("degrade"):
            delivered_rows = min(requested_rows, int(quota.get("ceiling", 0)))

        record = self.record_fetch(
            str(sub.get("id")),
            delivered_rows,
            release_id=int(release.get("id", 0)),
            requested_rows=requested_rows,
            degraded=bool(quota.get("degrade")),
        )
        return {
            "status": "fetched",
            "subscription": sub,
            "release": release,
            "quota": quota,
            "degraded": bool(quota.get("degrade")),
            "fetch_record": record,
        }

    def resolve_readable_version(self, app_id: str, contract_id: str) -> str | None:
        """解析消费方对某契约当前可读的订阅版本数据集。

        只有生效中的订阅才能读取数据；过渡期内新旧版本并存时，
        以订阅绑定的版本为准返回该应用能读到的契约版本。
        """
        for row in store.rows(self.MODULE):
            if (
                row.get("消费方应用") == app_id
                and row.get("所属契约") == contract_id
                and row.get("status") == "生效中"
            ):
                return row.get("订阅版本")
        return None

    def check_quota_ceiling(self, subscription_id: str, requested_rows: int) -> dict[str, Any]:
        """校验单次取数请求是否超出订阅配额上限。

        返回是否放行与配额余量，超额时按降级返回部分数据集处理，
        不直接丢弃已在执行的查询计划。
        """
        record = store.find(self.MODULE, int(subscription_id))
        if record is None:
            return {"allowed": False, "reason": "订阅不存在"}
        ceiling = int(record.get("配额上限", "0") or "0")
        allowed = requested_rows <= ceiling
        return {
            "allowed": allowed,
            "ceiling": ceiling,
            "requested": requested_rows,
            "remaining": max(0, ceiling - requested_rows),
            "degrade": not allowed,
        }

    def record_fetch(
        self,
        subscription_id: str,
        fetched_rows: int,
        *,
        release_id: int | None = None,
        requested_rows: int | None = None,
        degraded: bool = False,
    ) -> dict[str, Any]:
        """记录一次取数，推进最近取数水位并落库关联实际发布的取数记录。

        ``release_id`` 必须是本次实际交付数据的发布批次；取数记录与
        发布批次一一关联，撤回批次的数据不可能再进入新取数记录。
        """
        record = store.find(self.MODULE, int(subscription_id))
        if record is None:
            return {"status": "error", "message": "订阅不存在"}
        if release_id is None:
            release_id = record.get("_backing_release_id")
        if release_id is None:
            return {"status": "error", "message": "取数记录必须关联实际使用的发布批次"}

        release = store.find("dataset_release", int(release_id))
        if release is None:
            return {"status": "error", "message": "关联的发布批次不存在"}
        if release.get("status") != "已发布":
            return {"status": "error", "message": "关联的发布批次已撤回，不能再交付其数据"}

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record["最近取数"] = now
        record.setdefault("_fetch_batches", 0)
        record["_fetch_batches"] = int(record["_fetch_batches"]) + 1
        record.setdefault("_fetched_rows", 0)
        record["_fetched_rows"] = int(record["_fetched_rows"]) + int(fetched_rows)
        # 确保订阅绑定的就是本次实际发布
        if record.get("_backing_release_id") != int(release_id):
            self.bind_release(record, release, source="取数记录回绑")

        fetch_rows = store.rows(FETCH_RECORD_TABLE)
        record_id = max((int(r.get("id", 0)) for r in fetch_rows), default=0) + 1
        fetch_record = {
            "id": record_id,
            "取数记录编号": f"FETCH-{record_id:04d}",
            "订阅编号": record.get("订阅编号"),
            "订阅id": int(record.get("id", 0)),
            "消费方应用": record.get("消费方应用"),
            "所属契约": record.get("所属契约"),
            "订阅版本": record.get("订阅版本"),
            "关联发布id": int(release_id),
            "关联发布编号": release.get("发布编号"),
            "关联数据集": release.get("数据集名称"),
            "请求行数": int(requested_rows if requested_rows is not None else fetched_rows),
            "交付行数": int(fetched_rows),
            "是否降级": "是" if degraded else "否",
            "取数时间": now,
            "status": "已交付",
            "pending": False,
            "abnormal": False,
        }
        fetch_rows.append(fetch_record)
        return fetch_record

    def list_fetch_records(
        self,
        *,
        release_id: int | None = None,
        subscription_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """按实际发布批次（或订阅）查询本次/历次取数记录。"""
        rows = list(store.rows(FETCH_RECORD_TABLE))
        if release_id is not None:
            rows = [r for r in rows if r.get("关联发布id") == int(release_id)]
        if subscription_id is not None:
            rows = [r for r in rows if r.get("订阅id") == int(subscription_id)]
        return rows

    def get_subs_for_app(self, app_id: str) -> list[dict[str, Any]]:
        """查询消费方应用名下的全部订阅计划数据集。"""
        return [r for r in store.rows(self.MODULE) if r.get("消费方应用") == app_id]

    def get_subs_for_contract(self, contract_id: str) -> list[dict[str, Any]]:
        """查询契约名下的全部订阅计划数据集。"""
        return [r for r in store.rows(self.MODULE) if r.get("所属契约") == contract_id]

    def suspend_on_grant_revoke(self, app_id: str, contract_id: str) -> int:
        """授权回收时暂停关联订阅，返回被暂停的订阅数量。"""
        suspended = 0
        for row in store.rows(self.MODULE):
            if (
                row.get("消费方应用") == app_id
                and row.get("所属契约") == contract_id
                and row.get("status") == "生效中"
            ):
                row["status"] = "已暂停"
                row["abnormal"] = True
                suspended += 1
        return suspended


def resolve_subscription_read_scope(app_id: str, contract_id: str, requested_rows: int) -> dict:
    """模块级入口：解析订阅可读版本数据集并校验取数配额上限。

    同时返回当前实际供数的发布批次，调用方应按该批次发起取数，
    不能仅凭订阅版本自行猜测发布批次。
    """
    service = SubscriptionPlanService()
    version = service.resolve_readable_version(app_id, contract_id)
    subs = service.get_subs_for_app(app_id)
    sub = next(
        (s for s in subs if s.get("订阅版本") == version and s.get("status") == "生效中"),
        None,
    )
    quota: dict[str, Any] = {}
    backing_release = None
    if sub is not None:
        quota = service.check_quota_ceiling(str(sub.get("id")), requested_rows)
        backing_release = service.resolve_backing_release(sub, consumer_app_id=app_id)
    return {
        "readable_version": version,
        "quota": quota,
        "backing_release": backing_release,
    }
