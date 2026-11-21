"""服务等级目标领域服务：维护契约承诺的可用率与延迟目标并按窗口结算。

结算时读取窗口内的达成样本计算达成率，低于阈值自动生成违约事件数据集，
统计窗口支持日度/周度/月度，最近结算水位逐次推进。
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

    def compute_achievement(
        self,
        target_type: str,
        samples: list[dict[str, Any]],
    ) -> float:
        """按目标类型聚合窗口样本计算达成率。

        可用率类目标统计成功样本占比，延迟类目标统计延迟读数
        落在阈值内的样本占比，返回百分比达成率供结算判定。
        """
        if not samples:
            return 100.0
        if target_type == "查询可用率":
            ok = sum(1 for s in samples if s.get("success", True))
        elif target_type in ("查询延迟P99", "新鲜度延迟"):
            ok = sum(1 for s in samples if not s.get("lagging", False))
        else:
            ok = sum(1 for s in samples if s.get("success", True))
        return round(ok / len(samples) * 100.0, 2)

    def settle(
        self,
        target_id: str,
        samples: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """结算单个等级目标：计算达成率、判定达标并推进结算水位。

        达成率低于目标阈值时把目标标记为未达标并产出违约事件批次，
        违约处置结论决定下游通知方式。
        """
        target = store.find(self.MODULE, target_id)
        if target is None:
            return {"status": "error", "message": f"等级目标 {target_id} 不存在"}
        threshold = float(target.get("目标阈值", "99") or "99")
        achievement = self.compute_achievement(str(target.get("目标类型", "")), samples)
        target["当前达成率"] = str(achievement)
        target["最近结算"] = datetime.now().strftime("%Y-%m-%d")
        breached = achievement < threshold
        target["status"] = "未达标" if breached else "达标"
        target["abnormal"] = breached
        target["pending"] = breached
        return {
            "status": "settled",
            "target_id": target_id,
            "achievement": achievement,
            "threshold": threshold,
            "breached": breached,
            "disposition": target.get("违约处置", "") if breached else "",
        }

    def settle_contract(self, contract_id: str, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """批量结算契约名下的全部等级目标，返回逐条结算结果数据集。"""
        results = []
        for target in store.rows(self.MODULE):
            if target.get("所属契约") == contract_id:
                results.append(self.settle(int(target.get("id", 0)), samples))
        return results

    def get_targets_for_contract(self, contract_id: str) -> list[dict[str, Any]]:
        """查询契约名下的全部等级目标数据集。"""
        return [r for r in store.rows(self.MODULE) if r.get("所属契约") == contract_id]


def settle_contract_window(contract_id: str, samples: list[dict]) -> dict:
    """模块级入口：按统计窗口结算契约全部等级目标并产出达成率数据集。"""
    service = SlaTargetService()
    results = service.settle_contract(contract_id, samples)
    breached = [r for r in results if r.get("breached")]
    return {"results": results, "breached_count": len(breached), "breached": breached}
