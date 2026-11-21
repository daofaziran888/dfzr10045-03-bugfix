"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ReconcileTaskService(BaseModuleService):
    MODULE = "reconcile_task"
    ENTITY = "对账任务"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["对账编号", "对账口径", "左侧来源", "右侧来源", "对账窗口", "匹配行数", "差异行数", "对账耗时"]
    REQUIRED_FIELDS = ["对账编号", "对账口径", "左侧来源"]
    STATUS_ORDER = ["待对账", "对账中", "已平账", "存在差异"]
    ACTION_RULES = {"启动对账": "对账中", "确认平账": "已平账", "登记差异": "存在差异"}
    NEGATIVE_ACTIONS = []
