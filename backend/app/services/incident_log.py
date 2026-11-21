"""服务事件领域服务：记录端点异常、超时和错误返回等服务事件数据集。

事件持续时长影响SLA结算样本，恢复时写入恢复方式并联动关闭关联违约，
归档复盘后事件不可再变更，事件与违约目标互相关联。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class IncidentLogService(BaseModuleService):
    MODULE = "incident_log"
    ENTITY = "服务事件"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["事件编号", "所属端点", "事件类别", "影响应用数", "持续分钟", "恢复方式", "关联违约", "事件时间"]
    REQUIRED_FIELDS = ["事件编号", "所属端点"]
    STATUS_ORDER = ["已发生", "处理中", "已恢复", "已复盘"]
    ACTION_RULES = {"启动处理": "处理中", "确认恢复": "已恢复", "归档复盘": "已复盘"}
    NEGATIVE_ACTIONS = []

    def open_incident(
        self,
        endpoint_id: str,
        category: str,
        affected_apps: int,
        breach_event_id: str = "",
    ) -> dict[str, Any]:
        """登记服务事件：写入事件类别与影响应用数，状态为已发生。"""
        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        incident = {
            "id": new_id,
            "事件编号": f"INCI-{new_id:04d}",
            "所属端点": endpoint_id,
            "事件类别": category,
            "影响应用数": str(affected_apps),
            "持续分钟": "0",
            "恢复方式": "",
            "关联违约": breach_event_id,
            "事件时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已发生",
            "pending": True,
            "abnormal": True,
        }
        rows.append(incident)
        return incident

    def recover(self, incident_id: str, recovery_method: str, duration_minutes: int) -> dict[str, Any]:
        """确认恢复：写入恢复方式与持续分钟，联动关闭关联违约事件。

        已复盘的事件不能重复恢复；恢复后读取关联违约事件数据集，
        未升级的违约事件同步关闭。
        """
        incident = self._find_by_incident_id(incident_id)
        if incident is None:
            return {"status": "error", "message": f"事件 {incident_id} 不存在"}
        if incident.get("status") == "已复盘":
            return {"status": "error", "message": "已复盘事件不能变更"}
        incident["status"] = "已恢复"
        incident["恢复方式"] = recovery_method
        incident["持续分钟"] = str(duration_minutes)
        incident["abnormal"] = False
        incident["pending"] = False

        closed_breach = ""
        breach_id = str(incident.get("关联违约", ""))
        if breach_id:
            for breach in store.rows("sla_breach"):
                if breach.get("事件编号") == breach_id and breach.get("status") != "已升级":
                    breach["status"] = "已关闭"
                    breach["pending"] = False
                    closed_breach = breach_id
        return {"status": "recovered", "incident": incident, "closed_breach": closed_breach}

    def build_sla_samples(self, endpoint_id: str, window_start: str) -> list[dict[str, Any]]:
        """把窗口内的服务事件转换为SLA结算样本数据集。

        读取事件记录，窗口内发生过事件的时段样本标记 success=False，
        供等级目标结算计算可用率达成率。
        """
        samples: list[dict[str, Any]] = []
        for incident in store.rows(self.MODULE):
            if incident.get("所属端点") != endpoint_id:
                continue
            if str(incident.get("事件时间", "")) >= window_start:
                samples.append({
                    "success": incident.get("status") in ("已恢复", "已复盘"),
                    "lagging": False,
                    "incident_id": incident.get("事件编号"),
                })
        return samples

    def _find_by_incident_id(self, incident_id: str) -> dict[str, Any] | None:
        for row in store.rows(self.MODULE):
            if row.get("事件编号") == incident_id:
                return row
        return None

    def get_incidents_for_endpoint(self, endpoint_id: str) -> list[dict[str, Any]]:
        """查询端点名下的全部服务事件数据集。"""
        return [r for r in store.rows(self.MODULE) if r.get("所属端点") == endpoint_id]
