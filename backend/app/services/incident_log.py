"""服务事件领域服务：记录端点异常、超时和错误返回等服务事件。

事件与违约目标互相关联，恢复后自动关闭关联违约事件。事件持续时长影响SLA结算。
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

    def get_incidents_for_endpoint(self, endpoint_id: str) -> list[dict[str, Any]]:
        """获取端点关联的全部服务事件列表。"""
        return [r for r in store.rows(self.MODULE) if r.get("所属端点") == endpoint_id]

    def link_to_breach(self, incident_id: str, breach_id: str) -> None:
        """关联服务事件与违约事件。"""
        for r in store.rows(self.MODULE):
            if r.get("事件编号") == incident_id:
                r["关联违约"] = breach_id
