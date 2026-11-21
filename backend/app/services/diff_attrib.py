"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class DiffAttribService(BaseModuleService):
    MODULE = "diff_attrib"
    ENTITY = "归因条目"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["归因编号", "关联比对", "差异字段", "归因类别", "根因说明", "影响行数", "修正方案", "归因人标识"]
    REQUIRED_FIELDS = ["归因编号", "关联比对", "差异字段"]
    STATUS_ORDER = ["待归因", "归因中", "已修正", "无法归因"]
    ACTION_RULES = {"启动归因": "归因中", "确认修正": "已修正", "登记无法归因": "无法归因"}
    NEGATIVE_ACTIONS = []
