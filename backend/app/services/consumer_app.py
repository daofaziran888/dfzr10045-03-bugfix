"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ConsumerAppService(BaseModuleService):
    MODULE = "consumer_app"
    ENTITY = "消费方应用"
    OPERATION_TERM = "接入"
    LIST_FIELDS = ["应用编号", "应用名称", "所属团队", "接入方式", "调用峰值", "绑定契约数", "接入时间", "最近调用"]
    REQUIRED_FIELDS = ["应用编号", "应用名称", "所属团队"]
    STATUS_ORDER = ["待接入", "已接入", "已限流", "已下线"]
    ACTION_RULES = {"确认接入": "已接入", "限流应用": "已限流", "下线应用": "已下线"}
    NEGATIVE_ACTIONS = ["下线应用"]
