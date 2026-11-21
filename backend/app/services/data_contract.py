"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class DataContractService(BaseModuleService):
    MODULE = "data_contract"
    ENTITY = "数据契约"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["契约编号", "契约名称", "数据主题", "供给方标识", "承诺等级", "生效起日", "生效止日", "当前版本"]
    REQUIRED_FIELDS = ["契约编号", "契约名称", "数据主题"]
    STATUS_ORDER = ["草拟中", "已签署", "已冻结", "已终止"]
    ACTION_RULES = {"提交签署": "已签署", "冻结契约": "已冻结", "终止契约": "已终止"}
    NEGATIVE_ACTIONS = []
