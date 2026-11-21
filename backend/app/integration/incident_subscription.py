"""事件与订阅管理链路：服务事件记录→事件恢复→关联违约→订阅生命周期管理。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store


def create_incident(
    endpoint_id: str,
    incident_category: str,
    affected_apps: int,
    duration_minutes: int,
    breach_event_id: str | None = None,
) -> dict[str, Any]:
    """记录服务事件——端点异常/超时/错误返回的服务事件。"""
    incident_rows = store.rows("incident_log")
    new_id = max((int(r.get("id", 0)) for r in incident_rows), default=0) + 1

    incident = {
        "id": new_id,
        "事件编号": f"INCI-{new_id:04d}",
        "所属端点": endpoint_id,
        "事件类别": incident_category,
        "影响应用数": str(affected_apps),
        "持续分钟": str(duration_minutes),
        "恢复方式": "",
        "关联违约": breach_event_id or "",
        "事件时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "已发生",
        "pending": True,
        "abnormal": True,
    }
    incident_rows.append(incident)
    return {"status": "created", "incident": incident}


def recover_incident(
    incident_id: str,
    recovery_method: str,
) -> dict[str, Any]:
    """恢复服务事件——记录恢复方式并关闭事件。"""
    for incident in store.rows("incident_log"):
        if incident.get("事件编号") == incident_id:
            if incident.get("status") == "已恢复":
                return {"status": "error", "message": "事件已恢复"}
            incident["status"] = "已恢复"
            incident["恢复方式"] = recovery_method
            incident["abnormal"] = False
            incident["pending"] = False
            return {"status": "recovered", "incident": incident}
    return {"status": "error", "message": f"事件 {incident_id} 不存在"}


def create_subscription(
    consumer_app_id: str,
    contract_id: str,
    sub_version: str,
    fetch_frequency: str,
    quota_upper_limit: str,
) -> dict[str, Any]:
    """创建订阅计划——消费方对契约版本建立订阅关系。"""
    sub_rows = store.rows("subscription_plan")
    new_id = max((int(r.get("id", 0)) for r in sub_rows), default=0) + 1

    subscription = {
        "id": new_id,
        "订阅编号": f"SUBS-{new_id:04d}",
        "消费方应用": consumer_app_id,
        "所属契约": contract_id,
        "订阅版本": sub_version,
        "取数频率": fetch_frequency,
        "配额上限": quota_upper_limit,
        "订阅起日": datetime.now().strftime("%Y-%m-%d"),
        "最近取数": "",
        "status": "生效中",
        "pending": True,
        "abnormal": False,
    }
    sub_rows.append(subscription)
    return {"status": "created", "subscription": subscription}