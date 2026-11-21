"""缓存策略领域服务：维护端点结果缓存的键构成、存活时间与失效触发条件。

契约版本切换时旧缓存必须整体失效。缓存命中率与回源比例持续追踪并自动调整策略。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class CachePolicyService(BaseModuleService):
    MODULE = "cache_policy"
    ENTITY = "缓存策略"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["策略编号", "所属端点", "缓存键构成", "存活秒数", "失效触发", "命中率", "回源比例", "最近调整"]
    REQUIRED_FIELDS = ["策略编号", "所属端点"]
    STATUS_ORDER = ["草稿", "已生效", "失效中", "已停用"]
    ACTION_RULES = {"启效策略": "已生效", "强制失效": "失效中", "停用策略": "已停用"}
    NEGATIVE_ACTIONS = []

    def get_policy_for_endpoint(self, endpoint_id: str) -> dict[str, Any] | None:
        """获取端点关联的缓存策略。"""
        for r in store.rows(self.MODULE):
            if r.get("所属端点") == endpoint_id and r.get("status") == "已生效":
                return r
        return None

    def invalidate_on_version_switch(self, endpoint_id: str) -> int:
        """版本切换时批量失效旧缓存策略。"""
        count = 0
        for r in store.rows(self.MODULE):
            if r.get("所属端点") == endpoint_id:
                r["status"] = "失效中"
                r["abnormal"] = True
                count += 1
        return count
