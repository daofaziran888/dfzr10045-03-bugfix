"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ContractVersionService(BaseModuleService):
    MODULE = "contract_version"
    ENTITY = "契约版本"
    OPERATION_TERM = "读取"
    LIST_FIELDS = ["版本编号", "所属契约", "版本号", "变更摘要", "兼容判定", "父版本号", "过渡期天数", "生效时间"]
    REQUIRED_FIELDS = ["版本编号", "所属契约", "版本号"]
    STATUS_ORDER = ["草稿", "过渡中", "已生效", "已废止"]
    ACTION_RULES = {"启动过渡": "过渡中", "生效版本": "已生效", "废止版本": "已废止"}
    NEGATIVE_ACTIONS = []
