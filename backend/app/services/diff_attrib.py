"""差异归因领域服务：把双跑对账差异逐条归因到字段与根因类别。

修正方案落地后需重新比对确认收敛。归因结果关联比对编号和差异字段。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class DiffAttribService(BaseModuleService):
    MODULE = "diff_attrib"
    ENTITY = "归因条目"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["归因编号", "关联比对", "差异字段", "归因类别", "根因说明", "影响行数", "修正方案", "归因人标识"]
    REQUIRED_FIELDS = ["归因编号", "关联比对"]
    STATUS_ORDER = ["待归因", "归因中", "已修正", "无法归因"]
    ACTION_RULES = {"启动归因": "归因中", "确认修正": "已修正", "登记无法归因": "无法归因"}
    NEGATIVE_ACTIONS = []

    def get_attribs_for_dual_run(self, dual_run_id: str) -> list[dict[str, Any]]:
        """获取双跑比对关联的全部归因条目列表。"""
        return [r for r in store.rows(self.MODULE) if r.get("关联比对") == dual_run_id]

    def categorize_attribution(self, field_name: str, old_val: Any, new_val: Any) -> str:
        """按字段差异自动分类归因类别。"""
        if old_val is None or new_val is None:
            return "口径差异"
        return "数据类型转换"
