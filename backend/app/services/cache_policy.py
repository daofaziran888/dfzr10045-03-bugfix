"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class CachePolicyService(BaseModuleService):
    MODULE = "cache_policy"
    ENTITY = "缓存策略"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["策略编号", "所属端点", "缓存键构成", "存活秒数", "失效触发", "命中率", "回源比例", "最近调整"]
    REQUIRED_FIELDS = ["策略编号", "所属端点", "缓存键构成"]
    STATUS_ORDER = ["草稿", "已生效", "失效中", "已停用"]
    ACTION_RULES = {"启效策略": "已生效", "强制失效": "失效中", "停用策略": "已停用"}
    NEGATIVE_ACTIONS = ["停用策略"]
