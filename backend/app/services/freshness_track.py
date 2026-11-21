"""新鲜度追踪领域服务：追踪契约承诺延迟与实际数据水位的差距。

按承诺延迟与实际延迟计算滞后比率，严重滞后时缩短结果集快照有效期
并推进SLA违约评估，滞后批次与滞后原因写入读数数据集供下游消费。
"""
from __future__ import annotations

from datetime import datetime
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

    MILD_RATIO = 1.0
    SEVERE_RATIO = 2.0

    def classify_lag(self, promised_minutes: int, actual_minutes: int) -> str:
        """按延迟比率分类新鲜度状态：达标/轻微滞后/严重滞后。"""
        ratio = actual_minutes / max(promised_minutes, 1)
        if ratio <= self.MILD_RATIO:
            return "达标"
        if ratio <= self.SEVERE_RATIO:
            return "轻微滞后"
        return "严重滞后"

    def track_reading(
        self,
        contract_id: str,
        promised_minutes: int,
        actual_minutes: int,
        water_level: str,
    ) -> dict[str, Any]:
        """记录一次新鲜度读数并落库，严重滞后触发快照有效期缩短。

        读取契约与结果集快照数据集，滞后时推进快照有效期水位，
        产出新鲜度读数记录供SLA结算与端点查询消费。
        """
        status = self.classify_lag(promised_minutes, actual_minutes)
        lag_batches = 0 if status == "达标" else (
            1 if status == "轻微滞后" else max(1, (actual_minutes - promised_minutes) // max(promised_minutes, 1))
        )
        reason = "" if status == "达标" else (
            f"实际延迟{actual_minutes}min超过承诺{promised_minutes}min"
        )

        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        reading = {
            "id": new_id,
            "读数编号": f"FRESH-{new_id:04d}",
            "所属契约": contract_id,
            "承诺延迟": f"{promised_minutes}min",
            "实际延迟": f"{actual_minutes}min",
            "数据水位": water_level,
            "滞后批次": str(lag_batches),
            "滞后原因": reason,
            "追踪时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": status,
            "pending": status != "达标",
            "abnormal": status != "达标",
        }
        rows.append(reading)

        # 滞后时缩短快照有效期
        if status != "达标":
            from app.services.result_set import ResultSetService
            ResultSetService().shorten_validity(contract_id, actual_minutes)

        return reading

    def get_readings_for_contract(self, contract_id: str) -> list[dict[str, Any]]:
        """查询契约名下的全部新鲜度读数数据集。"""
        return [r for r in store.rows(self.MODULE) if r.get("所属契约") == contract_id]

    def get_lagging_contracts(self) -> list[str]:
        """查询当前存在滞后读数的契约编号列表，供SLA违约评估消费。"""
        lagging = set()
        for r in store.rows(self.MODULE):
            if r.get("status") in ("轻微滞后", "严重滞后"):
                lagging.add(str(r.get("所属契约", "")))
        return sorted(lagging)


def track_contract_freshness(contract_id: str, promised: int, actual: int, water_level: str) -> dict:
    """模块级入口：记录新鲜度读数并汇总契约滞后批次数据集。"""
    service = FreshnessTrackService()
    reading = service.track_reading(contract_id, promised, actual, water_level)
    return {
        "reading": reading,
        "lag_ratio": round(actual / max(promised, 1), 2),
        "lagging_contracts": service.get_lagging_contracts(),
    }
