"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class SlaBreachService(BaseModuleService):
    MODULE = "sla_breach"
    ENTITY = "违约事件"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["事件编号", "所属目标", "违约窗口", "实际读数", "偏离幅度", "影响应用数", "处置结论", "事件时间"]
    REQUIRED_FIELDS = ["事件编号", "所属目标", "违约窗口"]
    STATUS_ORDER = ["已登记", "处置中", "已关闭", "已升级"]
    ACTION_RULES = {"启动处置": "处置中", "关闭事件": "已关闭", "升级事件": "已升级"}
    NEGATIVE_ACTIONS = []
