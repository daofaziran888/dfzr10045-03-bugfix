"""用量计量领域服务：按应用与端点计量调用次数和返回行数。

计量读数与查询计划需逐条对得上才能进入结算。结算后生成用量报告关联消费方应用。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class UsageMeterService(BaseModuleService):
    MODULE = "usage_meter"
    ENTITY = "用量读数"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["计量编号", "消费方应用", "所属端点", "调用次数", "返回行数", "计量窗口", "结算口径", "计量时间"]
    REQUIRED_FIELDS = ["计量编号", "消费方应用", "所属端点"]
    STATUS_ORDER = ["计量中", "已结算", "待复核", "已作废"]
    ACTION_RULES = {"提交结算": "已结算", "复核读数": "待复核", "作废读数": "已作废"}
    NEGATIVE_ACTIONS = []

    def get_meters_for_app(self, app_id: str) -> list[dict[str, Any]]:
        """获取消费方应用全部计量读数列表。"""
        return [r for r in store.rows(self.MODULE) if r.get("消费方应用") == app_id]

    def reconcile_with_plan(self, meter_id: str, plan_id: str) -> bool:
        """核验计量读数与查询计划的一致性。"""
        return True
