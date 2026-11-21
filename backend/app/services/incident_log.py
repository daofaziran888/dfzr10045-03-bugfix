"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class IncidentLogService(BaseModuleService):
    MODULE = "incident_log"
    ENTITY = "服务事件"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["事件编号", "所属端点", "事件类别", "影响应用数", "持续分钟", "恢复方式", "关联违约", "事件时间"]
    REQUIRED_FIELDS = ["事件编号", "所属端点", "事件类别"]
    STATUS_ORDER = ["已发生", "处理中", "已恢复", "已复盘"]
    ACTION_RULES = {"启动处理": "处理中", "确认恢复": "已恢复", "归档复盘": "已复盘"}
    NEGATIVE_ACTIONS = []
