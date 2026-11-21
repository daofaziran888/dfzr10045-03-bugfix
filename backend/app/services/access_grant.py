"""访问授权领域服务：维护应用对端点的可见列与行级过滤条件。

授权到期或契约冻结时端点必须立即拒绝该应用取数。收窄或回收授权影响订阅状态。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class AccessGrantService(BaseModuleService):
    MODULE = "access_grant"
    ENTITY = "授权记录"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["授权编号", "消费方应用", "所属端点", "可见列范围", "行级过滤条件", "授权起日", "授权止日", "最近核验"]
    REQUIRED_FIELDS = ["授权编号", "消费方应用", "所属端点"]
    STATUS_ORDER = ["待核验", "已授权", "已收窄", "已回收"]
    ACTION_RULES = {"核验授权": "已授权", "收窄范围": "已收窄", "回收授权": "已回收"}
    NEGATIVE_ACTIONS = []

    def get_grants_for_app(self, app_id: str) -> list[dict[str, Any]]:
        """获取消费方应用的全部授权记录列表。"""
        return [r for r in store.rows(self.MODULE) if r.get("消费方应用") == app_id]

    def check_grant_expiry(self) -> list[str]:
        """检查并返回已过期授权的编号列表。"""
        today = datetime.now().strftime("%Y-%m-%d")
        return [r.get("授权编号", "") for r in store.rows(self.MODULE)
                if r.get("授权止日", "2099-12-31") <= today and r.get("status") == "已授权"]
