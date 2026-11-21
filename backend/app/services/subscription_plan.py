"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class SubscriptionPlanService(BaseModuleService):
    MODULE = "subscription_plan"
    ENTITY = "订阅计划"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["订阅编号", "消费方应用", "所属契约", "订阅版本", "取数频率", "配额上限", "订阅起日", "最近取数"]
    REQUIRED_FIELDS = ["订阅编号", "消费方应用", "所属契约"]
    STATUS_ORDER = ["待生效", "生效中", "已暂停", "已到期"]
    ACTION_RULES = {"启效订阅": "生效中", "暂停订阅": "已暂停", "终止订阅": "已到期"}
    NEGATIVE_ACTIONS = []
