"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class UsageMeterService(BaseModuleService):
    MODULE = "usage_meter"
    ENTITY = "用量读数"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["计量编号", "消费方应用", "所属端点", "调用次数", "返回行数", "计量窗口", "结算口径", "计量时间"]
    REQUIRED_FIELDS = ["计量编号", "消费方应用", "所属端点"]
    STATUS_ORDER = ["计量中", "已结算", "待复核", "已作废"]
    ACTION_RULES = {"提交结算": "已结算", "复核读数": "待复核", "作废读数": "已作废"}
    NEGATIVE_ACTIONS = ["作废读数"]
