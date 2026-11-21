"""双跑比对领域服务：新旧口径并行运行期间比对样本输出。

一致与偏离行数构成契约版本切换依据。偏离超限时自动触发差异归因分析。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class DualRunService(BaseModuleService):
    MODULE = "dual_run"
    ENTITY = "双跑记录"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["双跑编号", "关联对账", "旧口径版本", "新口径版本", "比对样本数", "一致行数", "偏离行数", "双跑结论"]
    REQUIRED_FIELDS = ["双跑编号", "关联对账"]
    STATUS_ORDER = ["并行中", "比对中", "已收敛", "偏离超限"]
    ACTION_RULES = {"启动比对": "比对中", "确认收敛": "已收敛", "标记超限": "偏离超限"}
    NEGATIVE_ACTIONS = []

    def get_dual_runs_for_reconcile(self, reconcile_id: str) -> list[dict[str, Any]]:
        """获取对账任务关联的全部双跑比对记录。"""
        return [r for r in store.rows(self.MODULE) if r.get("关联对账") == reconcile_id]

    def compute_convergence_rate(self, consistent: int, divergent: int) -> float:
        """计算双跑比对收敛率。"""
        total = consistent + divergent
        return consistent / max(total, 1) * 100.0
