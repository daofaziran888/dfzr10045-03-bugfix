"""结果集快照领域服务：冻结查询结果成快照，维护有效期与引用次数。

有效期内重复读取命中同一份快照。契约版本切换或新鲜度滞后时缩短快照有效期。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class ResultSetService(BaseModuleService):
    MODULE = "result_set"
    ENTITY = "结果集快照"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["快照编号", "所属计划", "绑定版本", "快照行数", "列摘要值", "有效期", "引用次数", "生成时间"]
    REQUIRED_FIELDS = ["快照编号", "所属计划"]
    STATUS_ORDER = ["生成中", "可读", "已过期", "已失效"]
    ACTION_RULES = {"标记可读": "可读", "标记过期": "已过期", "强制失效": "已失效"}
    NEGATIVE_ACTIONS = []

    def get_readable_snapshots(self) -> list[dict[str, Any]]:
        """获取全部可读的有效期快照列表。"""
        return [r for r in store.rows(self.MODULE) if r.get("status") == "可读"]

    def check_expiry(self) -> int:
        """检查并标记已过期快照，返回过期数量。"""
        now = datetime.now()
        expired = 0
        for r in store.rows(self.MODULE):
            expiry = r.get("有效期", "")
            if expiry and expiry < now.strftime("%Y-%m-%dT%H:%M:%S") and r.get("status") == "可读":
                r["status"] = "已过期"
                r["abnormal"] = True
                expired += 1
        return expired
