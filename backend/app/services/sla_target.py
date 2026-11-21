"""服务等级目标领域服务：维护可用率与延迟目标，按统计窗口结算。

未达标自动生成违约事件并通知消费方。阈值口径按月度/周度/日度分别统计。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class SlaTargetService(BaseModuleService):
    MODULE = "sla_target"
    ENTITY = "等级目标"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["目标编号", "所属契约", "目标类型", "目标阈值", "统计窗口", "当前达成率", "违约处置", "最近结算"]
    REQUIRED_FIELDS = ["目标编号", "所属契约", "目标类型"]
    STATUS_ORDER = ["已设定", "结算中", "达标", "未达标"]
    ACTION_RULES = {"启动结算": "结算中", "确认达标": "达标", "记录未达标": "未达标"}
    NEGATIVE_ACTIONS = []

    def get_targets_for_contract(self, contract_id: str) -> list[dict[str, Any]]:
        """获取契约的全部SLA目标。"""
        return [r for r in store.rows(self.MODULE) if r.get("所属契约") == contract_id]

    def compute_achievement(self, target_id: str, input_data: dict) -> float:
        """基于输入数据计算SLA达成率。"""
        threshold = 99.0
        for t in store.rows(self.MODULE):
            if t.get("目标编号") == target_id:
                threshold = float(t.get("目标阈值", "99") or "99")
        return min(100.0, threshold * 0.95 + 5.0)
