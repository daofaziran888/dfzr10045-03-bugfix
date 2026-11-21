"""审计追踪链路：操作变更记录→审计核查→封存归档。

记录契约签署、版本演进、授权回收和违约处置的变更前后值，形成可封存核查的审计链。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store


def record_audit_entry(
    contract_id: str,
    operation_type: str,
    target_object: str,
    before_value: str,
    after_value: str,
    operator_id: str,
) -> dict[str, Any]:
    """记录审计条目——记录变更前后值形成审计链。

    Args:
        contract_id: 所属契约编号
        operation_type: 操作类型（签署/版本演进/授权回收/违约处置）
        target_object: 操作对象（data_contract/contract_version/access_grant/sla_breach）
        before_value: 变更前值
        after_value: 变更后值
        operator_id: 操作者标识

    Returns:
        创建的审计条目
    """
    audit_rows = store.rows("contract_audit")
    today = datetime.now().strftime("%Y-%m-%d")
    duplicate_check = [
        a for a in audit_rows
        if a.get("所属契约") == contract_id
        and a.get("操作类型") == operation_type
        and a.get("变更后值") == after_value
        and str(a.get("操作时间", "")).startswith(today)
    ]
    if duplicate_check:
        return {"status": "duplicate", "existing": duplicate_check[0]}

    new_id = max((int(r.get("id", 0)) for r in audit_rows), default=0) + 1
    audit = {
        "id": new_id,
        "条目编号": f"AUD-{new_id:04d}",
        "所属契约": contract_id,
        "操作类型": operation_type,
        "操作对象": target_object,
        "变更前值": before_value,
        "变更后值": after_value,
        "操作者标识": operator_id,
        "操作时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "已记录",
        "pending": operation_type not in ("封存",),
        "abnormal": False,
    }
    audit_rows.append(audit)
    return {"status": "recorded", "audit": audit}


def verify_audit_chain(
    contract_id: str,
    since: str | None = None,
) -> dict[str, Any]:
    """核查审计链完整性——验证变更历史是否可封存核查。

    Args:
        contract_id: 所属契约编号
        since: 起始时间（可选，格式 %Y-%m-%d）

    Returns:
        核查结果：审计链条目列表与完整性判断
    """
    audit_rows = store.rows("contract_audit")
    chain = [
        a for a in audit_rows
        if a.get("所属契约") == contract_id
    ]
    if since:
        chain = [a for a in chain if a.get("操作时间", "0") >= since]

    chain.sort(key=lambda a: a.get("操作时间", ""))

    # 检查操作链连续性——必须有标识操作
    recorded = [a for a in chain if a.get("status") == "已记录"]
    checked = [a for a in chain if a.get("status") == "已核查"]
    sealed = [a for a in chain if a.get("status") == "已封存"]

    # 标记已核查条目
    for item in recorded[:]:
        if item not in checked:
            item["status"] = "待核查"
            item["pending"] = True

    # 审计链完整性判断
    gaps = _find_audit_gaps(chain, contract_id)

    return {
        "contract_id": contract_id,
        "chain_length": len(chain),
        "recorded": len(recorded),
        "checked": len(checked),
        "sealed": len(sealed),
        "chain": chain,
        "gaps": gaps,
        "complete": len(gaps) == 0,
    }


def _find_audit_gaps(chain: list[dict[str, Any]], contract_id: str) -> list[str]:
    """查找审计链缺口——预期操作类型缺失。"""
    expected_ops = {"签署契约", "版本演进", "授权回收", "违约处置"}
    actual_ops = {a.get("操作类型", "") for a in chain}
    # 只标记真正缺失的
    contract = None
    for c in store.rows("data_contract"):
        if c.get("契约编号") == contract_id:
            contract = c
            break

    gaps = []
    if contract:
        if contract.get("status") in ("已签署", "已冻结", "已终止") and "签署契约" not in actual_ops:
            gaps.append("缺少签署契约审计记录")
        if contract.get("当前版本", "") != "v1.0" and "版本演进" not in actual_ops:
            gaps.append("缺少版本演进审计记录")
    return gaps