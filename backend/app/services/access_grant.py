"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class AccessGrantService(BaseModuleService):
    MODULE = "access_grant"
    ENTITY = "授权记录"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["授权编号", "消费方应用", "所属端点", "可见列范围", "行级过滤条件", "授权起日", "授权止日", "最近核验"]
    REQUIRED_FIELDS = ["授权编号", "消费方应用", "所属端点"]
    STATUS_ORDER = ["待核验", "已授权", "已收窄", "已回收"]
    ACTION_RULES = {"核验授权": "已授权", "收窄范围": "已收窄", "回收授权": "已回收"}
    NEGATIVE_ACTIONS = []
