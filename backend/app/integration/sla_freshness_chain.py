"""SLA 与新鲜度追踪链路：新鲜度追踪→SLA结算→违约处置→事件升级。

支持新鲜度与快照有效期联动、SLA 未达标自动生成违约事件、违约升级回写契约承诺等级。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store


def track_freshness_and_settle_sla(
    contract_id: str,
    promised_delay_minutes: int,
    actual_delay_minutes: int,
    water_level: str,
) -> dict[str, Any]:
    """链路7：新鲜度追踪与SLA结算——追踪承诺延迟与实际延迟差距并结算SLA。

    输入：契约标识+承诺延迟+实际延迟+数据水位 → 处理：新鲜度读数记录、SLA目标结算 → 产物：新鲜度读数+SLA结算结果。
    滞后批次同时影响端点返回和结果集快照有效期。
    """
    # 记录新鲜度读数
    fresh_rows = store.rows("freshness_track")
    fresh_id = max((int(r.get("id", 0)) for r in fresh_rows), default=0) + 1
    lag_ratio = actual_delay_minutes / max(promised_delay_minutes, 1)
    if lag_ratio <= 1.0:
        freshness_status = "达标"
    elif lag_ratio <= 2.0:
        freshness_status = "轻微滞后"
    else:
        freshness_status = "严重滞后"

    # 滞后批次影响结果集快照有效期
    if freshness_status != "达标":
        _shorten_snapshots_for_contract(contract_id, actual_delay_minutes)

    freshness = {
        "id": fresh_id,
        "读数编号": f"FRESH-{fresh_id:04d}",
        "所属契约": contract_id,
        "承诺延迟": f"{promised_delay_minutes}min",
        "实际延迟": f"{actual_delay_minutes}min",
        "数据水位": water_level,
        "滞后批次": "1" if freshness_status != "达标" else "0",
        "滞后原因": f"实际延迟{actual_delay_minutes}min超过承诺{promised_delay_minutes}min" if freshness_status != "达标" else "",
        "追踪时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": freshness_status,
        "pending": freshness_status != "达标",
        "abnormal": freshness_status != "达标",
    }
    fresh_rows.append(freshness)

    # SLA 结算
    sla_result = _settle_sla_targets(contract_id, freshness_status, actual_delay_minutes)
    return {
        "freshness": freshness,
        "sla_settlement": sla_result,
        "lag_ratio": round(lag_ratio, 2),
    }


def escalate_breach(
    breach_event_id: str,
    reason: str,
) -> dict[str, Any]:
    """链路8：违约事件升级——SLA违约从处置中升级到已升级并回写契约承诺等级。

    输入：违约事件标识+升级原因 → 处理：事件状态升级、契约承诺等级回写 → 产物：已升级事件+更新后契约。
    处置结论回写契约承诺等级，触发口径调整。
    """
    breach_rows = store.rows("sla_breach")
    breach = None
    for br in breach_rows:
        if br.get("事件编号") == breach_event_id:
            breach = br
            break
    if not breach:
        return {"status": "error", "message": f"违约事件 {breach_event_id} 不存在"}

    current_status = breach.get("status")
    if current_status == "已升级":
        return {"status": "error", "message": "事件已升级，不能重复升级"}
    if current_status not in ("处置中", "已登记"):
        return {"status": "error", "message": f"当前状态{current_status}不允许升级"}

    breach["status"] = "已升级"
    breach["abnormal"] = True
    breach["处置结论"] = f"升级：{reason}"

    # 回写契约承诺等级
    target_id = breach.get("所属目标", "")
    contract_id = _resolve_contract_from_sla(target_id)
    if contract_id:
        contract = _find_by_field("data_contract", "契约编号", contract_id)
        if contract:
            old_level = contract.get("承诺等级", "")
            contract["承诺等级"] = f"{old_level}(降级-{reason[:10]})"
            contract["abnormal"] = True

    return {
        "status": "escalated",
        "breach_id": breach_event_id,
        "reason": reason,
        "affected_contract": contract_id,
    }


def _settle_sla_targets(
    contract_id: str,
    freshness_status: str,
    actual_delay: int,
) -> dict[str, Any]:
    """结算 SLA 目标——未达标自动生成违约事件。"""
    sla_rows = store.rows("sla_target")
    settlement_results = []
    for sla in sla_rows:
        if sla.get("所属契约") == contract_id:
            achievement = 95.0 if freshness_status == "达标" else (
                75.0 if freshness_status == "轻微滞后" else 50.0
            )
            sla["当前达成率"] = f"{achievement}%"
            sla["最近结算"] = datetime.now().strftime("%Y-%m-%d")

            if achievement < 99.0:
                sla["status"] = "未达标"
                sla["abnormal"] = True
                # 自动生成违约事件
                breach_event = _create_breach_event(sla, achievement, actual_delay)
                settlement_results.append({
                    "sla_target": sla.get("目标编号"),
                    "achievement": achievement,
                    "breach_event": breach_event,
                })
            else:
                sla["status"] = "达标"
                sla["abnormal"] = False
                settlement_results.append({
                    "sla_target": sla.get("目标编号"),
                    "achievement": achievement,
                    "breach_event": None,
                })
    return {"contract_id": contract_id, "results": settlement_results}


def _create_breach_event(
    sla: dict[str, Any],
    achievement: float,
    actual_delay: int,
) -> dict[str, Any]:
    breach_rows = store.rows("sla_breach")
    new_id = max((int(r.get("id", 0)) for r in breach_rows), default=0) + 1
    threshold = float(sla.get("目标阈值", "99") or "99")
    deviation = round(threshold - achievement, 1)
    breach = {
        "id": new_id,
        "事件编号": f"BRCH-{new_id:04d}",
        "所属目标": sla.get("目标编号", ""),
        "违约窗口": datetime.now().strftime("%Y-%m"),
        "实际读数": f"{achievement}%",
        "偏离幅度": f"{deviation}%",
        "影响应用数": "1",
        "处置结论": f"新鲜度不达标，实际延迟{actual_delay}min",
        "事件时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "已登记",
        "pending": True,
        "abnormal": True,
    }
    breach_rows.append(breach)
    return breach


def _shorten_snapshots_for_contract(contract_id: str, lag_minutes: int) -> None:
    """滞后时缩短结果集快照有效期。"""
    snap_rows = store.rows("result_set")
    new_expiry = (datetime.now() + timedelta(minutes=max(5, 60 - lag_minutes))).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    for snap in snap_rows:
        if contract_id in str(snap.get("绑定版本", "")):
            if snap.get("status") == "可读":
                snap["有效期"] = new_expiry


def _resolve_contract_from_sla(sla_target_id: str) -> str | None:
    for sla in store.rows("sla_target"):
        if sla.get("目标编号") == sla_target_id:
            return sla.get("所属契约")
    return None


def _find_by_field(module: str, field: str, value: str) -> dict[str, Any] | None:
    for row in store.rows(module):
        if row.get(field) == value:
            return row
    return None