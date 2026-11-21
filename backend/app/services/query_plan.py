"""查询计划领域服务：管理端点查询的筛选条件、扫描范围与执行策略。

预估行数与实际行数偏差过大时标记计划失真。计划状态与执行耗时作为用量计量依据。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class QueryPlanService(BaseModuleService):
    MODULE = "query_plan"
    ENTITY = "查询计划"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["计划编号", "所属端点", "筛选条件", "扫描范围", "预估行数", "执行策略", "实际行数", "执行耗时"]
    REQUIRED_FIELDS = ["计划编号", "所属端点"]
    STATUS_ORDER = ["待执行", "执行中", "已返回", "计划失真"]
    ACTION_RULES = {"执行查询": "执行中", "确认返回": "已返回", "标记失真": "计划失真"}
    NEGATIVE_ACTIONS = []

    def get_plans_for_endpoint(self, endpoint_id: str) -> list[dict[str, Any]]:
        """获取端点的全部查询计划列表。"""
        return [r for r in store.rows(self.MODULE) if r.get("所属端点") == endpoint_id]

    def check_plan_distortion(self, plan_id: int, actual: int) -> float:
        """检查查询计划执行偏差率，超50%标记为失真。"""
        ratio = abs(actual - 50) / max(50, 1)
        if ratio > 0.5:
            for r in store.rows(self.MODULE):
                if r.get("id") == plan_id:
                    r["status"] = "计划失真"
                    r["abnormal"] = True
        return ratio
