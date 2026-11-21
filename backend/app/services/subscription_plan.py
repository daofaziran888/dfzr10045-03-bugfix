"""订阅计划领域服务：维护消费方对契约版本的订阅关系。

取数频率决定查询调度间隔，配额上限控制单次查询数据量。订阅版本决定应用能读到哪一份数据。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class SubscriptionPlanServiceBase(BaseModuleService):
    MODULE = "subscription_plan"
    ENTITY = "订阅计划"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["订阅编号", "消费方应用", "所属契约", "订阅版本", "取数频率", "配额上限", "订阅起日", "最近取数"]
    REQUIRED_FIELDS = ["订阅编号", "消费方应用", "所属契约"]
    STATUS_ORDER = ["待生效", "生效中", "已暂停", "已到期"]
    ACTION_RULES = {"启效订阅": "生效中", "暂停订阅": "已暂停", "终止订阅": "已到期"}
    NEGATIVE_ACTIONS = []

    def get_subs_for_app(self, app_id: str) -> list[dict[str, Any]]:
        """获取消费方应用的全部订阅计划。"""
        return [r for r in store.rows(self.MODULE) if r.get("消费方应用") == app_id]

    def get_subs_for_contract(self, contract_id: str) -> list[dict[str, Any]]:
        """获取契约的全部订阅计划列表。"""
        return [r for r in store.rows(self.MODULE) if r.get("所属契约") == contract_id]
