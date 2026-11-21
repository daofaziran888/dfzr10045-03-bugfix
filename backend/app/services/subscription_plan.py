"""订阅计划领域服务：维护消费方对契约版本的订阅关系与取数配额。

订阅版本决定消费方能读到哪一份契约数据，取数频率驱动查询调度，
配额上限约束单次取数的数据集规模。订阅是查询端点取数的准入前提。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class SubscriptionPlanService(BaseModuleService):
    MODULE = "subscription_plan"
    ENTITY = "订阅计划"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["订阅编号", "消费方应用", "所属契约", "订阅版本", "取数频率", "配额上限", "订阅起日", "最近取数"]
    REQUIRED_FIELDS = ["订阅编号", "消费方应用", "所属契约"]
    STATUS_ORDER = ["待生效", "生效中", "已暂停", "已到期"]
    ACTION_RULES = {"启效订阅": "生效中", "暂停订阅": "已暂停", "终止订阅": "已到期"}
    NEGATIVE_ACTIONS = []

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
        record = store.find(self.MODULE, subscription_id)
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

    def record_fetch(self, subscription_id: str, fetched_rows: int) -> dict[str, Any]:
        """记录一次取数，推进最近取数水位并累计取数批次。"""
        record = store.find(self.MODULE, subscription_id)
        if record is None:
            return {"status": "error", "message": "订阅不存在"}
        record["最近取数"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record.setdefault("_fetch_batches", 0)
        record["_fetch_batches"] = int(record["_fetch_batches"]) + 1
        record.setdefault("_fetched_rows", 0)
        record["_fetched_rows"] = int(record["_fetched_rows"]) + int(fetched_rows)
        return {
            "status": "recorded",
            "fetched_rows": fetched_rows,
            "total_rows": record["_fetched_rows"],
            "batches": record["_fetch_batches"],
        }

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
    """模块级入口：解析订阅可读版本数据集并校验取数配额上限。"""
    service = SubscriptionPlanService()
    version = service.resolve_readable_version(app_id, contract_id)
    subs = service.get_subs_for_app(app_id)
    sub_id = next((str(s["id"]) for s in subs if s.get("订阅版本") == version), "")
    return {
        "readable_version": version,
        "quota": service.check_quota_ceiling(sub_id, requested_rows) if sub_id else {},
    }
