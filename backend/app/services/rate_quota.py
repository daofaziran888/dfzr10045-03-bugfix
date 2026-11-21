"""限流配额领域服务：按应用与端点维护秒级和日级调用配额。

超额时按处置结论降级返回部分数据集而不是丢弃已在执行的查询，
用量达到日级上限八成进入接近上限预警，计量窗口按月滚动重置。
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

    WARN_RATIO = 0.8

    def consume_quota(self, app_id: str, endpoint_id: str) -> dict[str, Any]:
        """消费一次配额：返回是否放行与降级标记。

        读取该应用与端点的配额条目，已超额时按超额处置结论降级，
        冻结配额直接拒绝；正常放行时累加当前用量并推进预警水位。
        """
        quota = self._find_quota(app_id, endpoint_id)
        if quota is None:
            quota = self._create_default_quota(app_id, endpoint_id)
        if quota.get("status") == "已冻结":
            return {"allowed": False, "degraded": False, "reason": "配额已冻结", "quota": quota}

        current = int(quota.get("当前用量", "0") or "0")
        daily = int(quota.get("日级上限", "1000") or "1000")
        if current >= daily:
            quota["status"] = "已超额"
            quota["abnormal"] = True
            return {
                "allowed": True,
                "degraded": True,
                "reason": quota.get("超额处置", "降级返回部分数据"),
                "quota": quota,
            }
        quota["当前用量"] = str(current + 1)
        if current + 1 >= daily * self.WARN_RATIO:
            quota["status"] = "接近上限"
            quota["abnormal"] = True
        return {"allowed": True, "degraded": False, "quota": quota}

    def reset_window(self, app_id: str, endpoint_id: str, window: str) -> bool:
        """计量窗口滚动时重置用量，窗口不一致才重置避免重复清零。"""
        quota = self._find_quota(app_id, endpoint_id)
        if quota is None:
            return False
        if quota.get("计量窗口") == window:
            return False
        quota["计量窗口"] = window
        quota["当前用量"] = "0"
        quota["status"] = "充足"
        quota["abnormal"] = False
        return True

    def adjust_quota(self, app_id: str, endpoint_id: str, new_daily: int) -> dict[str, Any]:
        """调整配额上限并写审计水位，调整后重新判定状态。"""
        quota = self._find_quota(app_id, endpoint_id)
        if quota is None:
            return {"status": "error", "message": "配额条目不存在"}
        quota["日级上限"] = str(new_daily)
        current = int(quota.get("当前用量", "0") or "0")
        if current >= new_daily:
            quota["status"] = "已超额"
        elif current >= new_daily * self.WARN_RATIO:
            quota["status"] = "接近上限"
        else:
            quota["status"] = "充足"
            quota["abnormal"] = False
        return {"status": "adjusted", "quota": quota}

    def _find_quota(self, app_id: str, endpoint_id: str) -> dict[str, Any] | None:
        for row in store.rows(self.MODULE):
            if row.get("消费方应用") == app_id and row.get("所属端点") == endpoint_id:
                return row
        return None

    def _create_default_quota(self, app_id: str, endpoint_id: str) -> dict[str, Any]:
        """无配额记录的应用接入端点时创建默认配额条目数据集。"""
        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        quota = {
            "id": new_id,
            "配额编号": f"QUOTA-{new_id:04d}",
            "消费方应用": app_id,
            "所属端点": endpoint_id,
            "秒级上限": "100",
            "日级上限": "1000",
            "当前用量": "0",
            "超额处置": "降级返回部分数据",
            "计量窗口": datetime.now().strftime("%Y-%m"),
            "status": "充足",
            "pending": True,
            "abnormal": False,
        }
        rows.append(quota)
        return quota

    def get_quota_for_app(self, app_id: str) -> list[dict[str, Any]]:
        """查询应用名下的全部配额条目数据集。"""
        return [r for r in store.rows(self.MODULE) if r.get("消费方应用") == app_id]
