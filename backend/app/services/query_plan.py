"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class QueryPlanService(BaseModuleService):
    MODULE = "query_plan"
    ENTITY = "查询计划"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["计划编号", "所属端点", "筛选条件", "扫描范围", "预估行数", "执行策略", "实际行数", "执行耗时"]
    REQUIRED_FIELDS = ["计划编号", "所属端点", "筛选条件"]
    STATUS_ORDER = ["待执行", "执行中", "已返回", "计划失真"]
    ACTION_RULES = {"执行查询": "执行中", "确认返回": "已返回", "标记失真": "计划失真"}
    NEGATIVE_ACTIONS = []
