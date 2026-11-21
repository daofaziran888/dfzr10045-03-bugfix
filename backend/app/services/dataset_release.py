"""数据集发布领域服务：把通过对账的数据集按版本发布给可订阅范围。

发布后订阅计划才能读到该批次数据。发布标签标记正式或灰度批次。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class DatasetReleaseService(BaseModuleService):
    MODULE = "dataset_release"
    ENTITY = "发布批次"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["发布编号", "数据集名称", "绑定版本", "数据行数", "对账结论", "可订阅范围", "发布标签", "发布时间"]
    REQUIRED_FIELDS = ["发布编号", "数据集名称"]
    STATUS_ORDER = ["待发布", "发布中", "已发布", "已撤回"]
    ACTION_RULES = {"启动发布": "发布中", "确认发布": "已发布", "撤回发布": "已撤回"}
    NEGATIVE_ACTIONS = []

    def get_published_datasets(self) -> list[dict[str, Any]]:
        """获取全部已发布的数据集列表。"""
        return [r for r in store.rows(self.MODULE) if r.get("status") == "已发布"]

    def validate_reconcile_requirement(self, dataset_name: str) -> dict[str, Any]:
        """校验数据集发布前的对账要求是否满足。"""
        for r in store.rows("reconcile_task"):
            if dataset_name in str(r.get("对账编号", "")):
                return {"valid": r.get("status") == "已平账", "reconcile_id": r.get("对账编号")}
        return {"valid": False, "reason": "无对账记录"}
