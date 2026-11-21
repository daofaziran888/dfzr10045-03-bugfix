"""新鲜度追踪领域服务：追踪契约承诺延迟与实际数据水位的差距。

滞后批次影响端点返回和快照有效期。严重滞后自动触发SLA违约评估。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class FreshnessTrackService(BaseModuleService):
    MODULE = "freshness_track"
    ENTITY = "新鲜度读数"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["读数编号", "所属契约", "承诺延迟", "实际延迟", "数据水位", "滞后批次", "滞后原因", "追踪时间"]
    REQUIRED_FIELDS = ["读数编号", "所属契约"]
    STATUS_ORDER = ["达标", "轻微滞后", "严重滞后", "追踪中断"]
    ACTION_RULES = {"刷新读数": "达标", "登记滞后": "轻微滞后", "标记中断": "追踪中断"}
    NEGATIVE_ACTIONS = []

    def get_readings_for_contract(self, contract_id: str) -> list[dict[str, Any]]:
        """获取契约的全部新鲜度读数列表。"""
        return [r for r in store.rows(self.MODULE) if r.get("所属契约") == contract_id]

    def compute_lag_ratio(self, promised: int, actual: int) -> float:
        """计算延迟比率。"""
        return actual / max(promised, 1)
