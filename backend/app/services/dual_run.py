"""双跑比对领域服务：新旧口径并行运行期间比对同一批样本的输出。

读取对账任务关联的两侧口径样本数据集逐行比对，一致与偏离行数构成
契约版本切换依据，偏离超限时产出差异批次供差异归因模块逐条归因。
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

    CONVERGENCE_THRESHOLD = 0.2

    def compare_samples(
        self,
        old_rows: list[dict[str, Any]],
        new_rows: list[dict[str, Any]],
        key_fields: list[str],
        compare_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """逐行比对新旧口径样本数据集，统计一致与偏离行数。

        按主键关联两侧样本，比对字段全部相等记为一致行，
        否则记为偏离行并保留偏离字段明细供归因消费。
        """
        old_index = {
            tuple(str(r.get(f, "")) for f in key_fields): r for r in old_rows
        }
        new_index = {
            tuple(str(r.get(f, "")) for f in key_fields): r for r in new_rows
        }
        consistent = 0
        divergent_rows: list[dict[str, Any]] = []
        for key, old_row in old_index.items():
            new_row = new_index.get(key)
            if new_row is None:
                divergent_rows.append({"key": key, "reason": "新口径缺失样本"})
                continue
            fields = compare_fields or [
                f for f in old_row if f in new_row and f not in ("id", "status")
            ]
            mismatched = [
                f for f in fields if str(old_row.get(f)) != str(new_row.get(f))
            ]
            if mismatched:
                divergent_rows.append({"key": key, "reason": "字段值偏离", "fields": mismatched})
            else:
                consistent += 1
        return {
            "consistent_rows": consistent,
            "divergent_rows": len(divergent_rows),
            "divergent_details": divergent_rows,
            "sample_size": len(old_rows),
        }

    def judge_convergence(self, consistent: int, divergent: int) -> str:
        """收敛判定：偏离行数占比不超过阈值判为已收敛，否则偏离超限。"""
        total = consistent + divergent
        ratio = divergent / max(total, 1)
        return "已收敛" if ratio <= self.CONVERGENCE_THRESHOLD else "偏离超限"

    def build_dual_run(
        self,
        reconcile_id: str,
        old_version: str,
        new_version: str,
        comparison: dict[str, Any],
    ) -> dict[str, Any]:
        """落库双跑比对记录，写入一致/偏离行数与双跑结论。"""
        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        conclusion = self.judge_convergence(
            comparison["consistent_rows"], comparison["divergent_rows"]
        )
        dual = {
            "id": new_id,
            "双跑编号": f"DUAL-{new_id:04d}",
            "关联对账": reconcile_id,
            "旧口径版本": old_version,
            "新口径版本": new_version,
            "比对样本数": str(comparison["sample_size"]),
            "一致行数": str(comparison["consistent_rows"]),
            "偏离行数": str(comparison["divergent_rows"]),
            "双跑结论": conclusion,
            "status": "比对中",
            "pending": True,
            "abnormal": comparison["divergent_rows"] > 0,
        }
        rows.append(dual)
        dual["_divergent_details"] = comparison["divergent_details"]
        return dual

    def finalize(self, dual_id: int) -> dict[str, Any]:
        """按双跑结论推进状态：已收敛清除待处理，偏离超限保留异常标记。"""
        dual = store.find(self.MODULE, dual_id)
        if dual is None:
            return {"status": "error", "message": "双跑记录不存在"}
        if dual.get("双跑结论") == "已收敛":
            dual["status"] = "已收敛"
            dual["pending"] = False
            dual["abnormal"] = False
        else:
            dual["status"] = "偏离超限"
            dual["abnormal"] = True
        return {"status": dual["status"], "dual": dual}

    def get_dual_runs_for_reconcile(self, reconcile_id: str) -> list[dict[str, Any]]:
        """查询对账任务关联的全部双跑比对记录数据集。"""
        return [r for r in store.rows(self.MODULE) if r.get("关联对账") == reconcile_id]

    def compute_convergence_rate(self, consistent: int, divergent: int) -> float:
        """计算双跑比对收敛率百分比。"""
        total = consistent + divergent
        return consistent / max(total, 1) * 100.0
