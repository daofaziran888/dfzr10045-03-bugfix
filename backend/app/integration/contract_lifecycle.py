"""契约生命周期链路：登记→版本演进→字段承诺校验→消费方订阅→审计记录。

支持版本过渡期新旧并存、迟到数据、承诺校验回写与审计链完整性。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store


def register_contract_chain(
    contract_id: str,
    contract_name: str,
    data_topic: str,
    provider_id: str,
    commitment_level: str,
    effective_start: str,
    effective_end: str,
) -> dict[str, Any]:
    """链路1：登记数据契约并自动创建初始版本与审计记录。

    输入：契约基础信息 → 处理：契约登记、初始版本创建、审计记录 → 产物：已签署契约+草稿版本+审计条目。
    """
    rows = store.rows("data_contract")
    # 去重：同一 contract_id 已存在则返回现有契约
    for row in rows:
        if row.get("契约编号") == contract_id:
            return {"status": "duplicate", "contract": row}
    new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
    contract = {
        "id": new_id,
        "契约编号": contract_id,
        "契约名称": contract_name,
        "数据主题": data_topic,
        "供给方标识": provider_id,
        "承诺等级": commitment_level,
        "生效起日": effective_start,
        "生效止日": effective_end,
        "当前版本": "v1.0",
        "status": "已签署",
        "pending": True,
        "abnormal": False,
    }
    rows.append(contract)

    # 创建初始版本
    ver_rows = store.rows("contract_version")
    ver_id = max((int(r.get("id", 0)) for r in ver_rows), default=0) + 1
    version = {
        "id": ver_id,
        "版本编号": f"VER-{contract_id}",
        "所属契约": contract_id,
        "版本号": "v1.0",
        "变更摘要": "初始版本：契约首次签署登记",
        "兼容判定": "初始版本",
        "父版本号": "",
        "过渡期天数": "0",
        "生效时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "已生效",
        "pending": False,
        "abnormal": False,
    }
    ver_rows.append(version)

    # 审计记录
    _write_audit(contract_id, "签署契约", "", contract_name, "system")
    return {"status": "created", "contract": contract, "version": version}


def evolve_contract_version(
    contract_id: str,
    new_version: str,
    change_summary: str,
    compatibility: str,
    transition_days: int,
) -> dict[str, Any]:
    """链路2：契约版本演进，支持过渡期内新旧版本并存。

    输入：契约标识+新版本号+变更摘要+兼容判定 → 处理：版本创建、过渡期标记、旧版本共存管理 → 产物：新版本记录+过渡状态。
    """
    # 查找契约
    contract = _find_by_field("data_contract", "契约编号", contract_id)
    if not contract:
        return {"status": "error", "message": f"契约 {contract_id} 不存在"}

    # 检查已有版本是否有过渡中的
    ver_rows = store.rows("contract_version")
    active_trans = [
        v for v in ver_rows
        if v.get("所属契约") == contract_id and v.get("status") == "过渡中"
    ]
    if len(active_trans) >= 2:
        return {"status": "error", "message": "已有两个版本处于过渡中，不允许新增版本演进"}

    # 获取父版本号
    existing_vers = [
        v for v in ver_rows
        if v.get("所属契约") == contract_id and v.get("status") == "已生效"
    ]
    parent_ver = existing_vers[-1]["版本号"] if existing_vers else "v1.0"

    new_id = max((int(r.get("id", 0)) for r in ver_rows), default=0) + 1
    version = {
        "id": new_id,
        "版本编号": f"VER-{contract_id}-{new_version}",
        "所属契约": contract_id,
        "版本号": new_version,
        "变更摘要": change_summary,
        "兼容判定": compatibility,
        "父版本号": parent_ver,
        "过渡期天数": str(transition_days),
        "生效时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "过渡中" if transition_days > 0 else "已生效",
        "pending": transition_days > 0,
        "abnormal": False,
    }
    ver_rows.append(version)

    # 更新契约当前版本
    contract["当前版本"] = new_version
    _write_audit(contract_id, "版本演进", parent_ver, new_version, "system")
    return {"status": "evolved", "version": version, "transition_days": transition_days}


def validate_field_promises(
    version_id: str,
    field_values: dict[str, Any],
) -> dict[str, Any]:
    """链路3：字段承诺校验——按契约版本拆成逐字段校验，违约回写。

    输入：版本标识+字段值字典 → 处理：逐字段类型/空值/取值域校验 → 产物：校验结果+违约记录。
    """
    # 查找该版本下的所有字段承诺
    promise_rows = store.rows("field_promise")
    version_promises = [
        p for p in promise_rows
        if p.get("所属版本") == version_id
    ]
    results = []
    breach_count = 0
    for promise in version_promises:
        field_name = promise.get("字段名称", "")
        expected_type = promise.get("类型声明", "")
        allows_null = promise.get("空值承诺", "") == "允许为空"
        value_domain = promise.get("取值域", "")

        actual_value = field_values.get(field_name)
        passed = True
        failure_reason = ""

        # 空值校验
        if actual_value is None and not allows_null:
            passed = False
            failure_reason = "字段不允许为空但实际值为空"

        # 类型校验
        if passed and expected_type and actual_value is not None:
            type_map = {"int": int, "float": float, "str": str, "bool": bool}
            expected_py = type_map.get(expected_type)
            if expected_py and not isinstance(actual_value, expected_py):
                passed = False
                failure_reason = f"期望类型{expected_type}，实际类型{type(actual_value).__name__}"

        # 取值域校验
        if passed and value_domain and actual_value is not None:
            allowed = [v.strip() for v in value_domain.split(",") if v.strip()]
            if allowed and str(actual_value) not in allowed:
                passed = False
                failure_reason = f"取值{actual_value}不在允许域{value_domain}中"

        if not passed:
            promise["status"] = "违约中"
            promise["abnormal"] = True
            breach_count += 1
            current_breach = int(promise.get("违约次数", "0") or "0")
            promise["违约次数"] = str(current_breach + 1)
        else:
            promise["status"] = "已达标"
            promise["abnormal"] = False

        results.append({
            "field": field_name,
            "passed": passed,
            "failure_reason": failure_reason,
        })

    return {
        "version_id": version_id,
        "total_promises": len(version_promises),
        "breach_count": breach_count,
        "results": results,
    }


def _find_by_field(module: str, field: str, value: str) -> dict[str, Any] | None:
    for row in store.rows(module):
        if row.get(field) == value:
            return row
    return None


def _write_audit(
    contract_id: str,
    operation: str,
    before: str,
    after: str,
    operator: str,
) -> None:
    audit_rows = store.rows("contract_audit")
    new_id = max((int(r.get("id", 0)) for r in audit_rows), default=0) + 1
    audit_rows.append({
        "id": new_id,
        "条目编号": f"AUD-{new_id:04d}",
        "所属契约": contract_id,
        "操作类型": operation,
        "操作对象": "data_contract",
        "变更前值": before,
        "变更后值": after,
        "操作者标识": operator,
        "操作时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "已记录",
        "pending": True,
        "abnormal": False,
    })