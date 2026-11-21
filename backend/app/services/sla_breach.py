"""违约事件领域服务：记录SLA未达成事件、处置进度与升级结论。

处置结论回写契约承诺等级，升级后触发新一轮契约评估。影响应用数关联消费方应用。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class SlaBreachService(BaseModuleService):
    MODULE = "sla_breach"
    ENTITY = "违约事件"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["事件编号", "所属目标", "违约窗口", "实际读数", "偏离幅度", "影响应用数", "处置结论", "事件时间"]
    REQUIRED_FIELDS = ["事件编号", "所属目标", "违约窗口"]
    STATUS_ORDER = ["已登记", "处置中", "已关闭", "已升级"]
    ACTION_RULES = {"启动处置": "处置中", "关闭事件": "已关闭", "升级事件": "已升级"}
    NEGATIVE_ACTIONS = []

    def get_active_breaches(self) -> list[dict[str, Any]]:
        """获取活跃的未关闭违约事件列表。"""
        return [r for r in store.rows(self.MODULE) if r.get("status") in ("已登记", "处置中")]

    def compute_deviation(self, target_value: float, actual_value: float) -> float:
        """计算偏离幅度百分比。"""
        return abs(target_value - actual_value) / max(target_value, 0.01) * 100.0
