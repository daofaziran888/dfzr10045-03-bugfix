"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class FieldPromiseService(BaseModuleService):
    MODULE = "field_promise"
    ENTITY = "字段承诺"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["承诺编号", "所属版本", "字段名称", "类型声明", "空值承诺", "取值域", "校验方式", "违约次数"]
    REQUIRED_FIELDS = ["承诺编号", "所属版本", "字段名称"]
    STATUS_ORDER = ["待校验", "已达标", "违约中", "已豁免"]
    ACTION_RULES = {"发起校验": "已达标", "记录违约": "违约中", "申请豁免": "已豁免"}
    NEGATIVE_ACTIONS = []
