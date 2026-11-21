"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ResultSetService(BaseModuleService):
    MODULE = "result_set"
    ENTITY = "结果集快照"
    OPERATION_TERM = "读取"
    LIST_FIELDS = ["快照编号", "所属计划", "绑定版本", "快照行数", "列摘要值", "有效期", "引用次数", "生成时间"]
    REQUIRED_FIELDS = ["快照编号", "所属计划", "绑定版本"]
    STATUS_ORDER = ["生成中", "可读", "已过期", "已失效"]
    ACTION_RULES = {"标记可读": "可读", "标记过期": "已过期", "强制失效": "已失效"}
    NEGATIVE_ACTIONS = []
