"""限流配额领域服务：按应用与端点维护秒级和日级调用配额。

超额时按处置结论降级返回而不是丢弃已在执行的查询。配额状态自动流转。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class RateQuotaService(BaseModuleService):
    MODULE = "rate_quota"
    ENTITY = "限流配额"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["配额编号", "消费方应用", "所属端点", "秒级上限", "日级上限", "当前用量", "超额处置", "计量窗口"]
    REQUIRED_FIELDS = ["配额编号", "消费方应用", "所属端点"]
    STATUS_ORDER = ["充足", "接近上限", "已超额", "已冻结"]
    ACTION_RULES = {"调整配额": "充足", "记录超额": "已超额", "冻结配额": "已冻结"}
    NEGATIVE_ACTIONS = []

    def get_quota_for_app(self, app_id: str) -> list[dict[str, Any]]:
        """获取指定应用的全部配额条目。"""
        return [r for r in store.rows(self.MODULE) if r.get("消费方应用") == app_id]

    def check_threshold(self, sec_limit: int, daily_limit: int, current: int) -> str:
        """判定配额阈值：充足、接近上限或已超额。"""
        if current >= daily_limit:
            return "已超额"
        if current >= daily_limit * 0.8:
            return "接近上限"
        return "充足"
