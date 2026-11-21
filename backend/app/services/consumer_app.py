"""消费方应用领域服务：登记接入数据服务的消费方应用及其调用峰值。

一个应用可绑定多份契约，订阅与授权均以应用为主体。超过峰值时自动限流并回写限流配额。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class ConsumerAppService(BaseModuleService):
    MODULE = "consumer_app"
    ENTITY = "消费方应用"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["应用编号", "应用名称", "所属团队", "接入方式", "调用峰值", "绑定契约数", "接入时间", "最近调用"]
    REQUIRED_FIELDS = ["应用编号", "应用名称", "所属团队"]
    STATUS_ORDER = ["待接入", "已接入", "已限流", "已下线"]
    ACTION_RULES = {"确认接入": "已接入", "限流应用": "已限流", "下线应用": "已下线"}
    NEGATIVE_ACTIONS = []

    def get_active_apps(self) -> list[dict[str, Any]]:
        """获取所有已接入的活跃应用列表。"""
        return [r for r in store.rows(self.MODULE) if r.get("status") == "已接入"]

    def check_rate_limit(self, app_id: str) -> dict[str, Any]:
        """检查消费方应用是否被限流并返回配额状态。"""
        for q in store.rows("rate_quota"):
            if q.get("消费方应用") == app_id:
                return {"status": q.get("status"), "current": q.get("当前用量")}
        return {"status": "无配额"}
