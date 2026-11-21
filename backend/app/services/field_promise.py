"""字段承诺领域服务：逐字段类型/空值/取值域校验，违约计数回写契约。

查询端点返回前必须按承诺逐字段校验，违约次数累积回写至契约的承诺等级评估。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class FieldPromiseService(BaseModuleService):
    MODULE = "field_promise"
    ENTITY = "字段承诺"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["承诺编号", "所属版本", "字段名称", "类型声明", "空值承诺", "取值域", "校验方式", "违约次数"]
    REQUIRED_FIELDS = ["承诺编号", "所属版本", "字段名称"]
    STATUS_ORDER = ["待校验", "已达标", "违约中", "已豁免"]
    ACTION_RULES = {"发起校验": "已达标", "记录违约": "违约中", "申请豁免": "已豁免"}
    NEGATIVE_ACTIONS = []

    def validate_field(self, promise_id: int, actual_value: Any) -> tuple[bool, str]:
        """对单个字段承诺执行校验：类型、空值、取值域。

        校验失败自动计数违约并回写承诺状态。
        """
        promise = store.find(self.MODULE, promise_id)
        if promise is None:
            return False, f"承诺 {promise_id} 不存在"

        field_name = promise.get("字段名称", "")
        expected_type = promise.get("类型声明", "")
        allows_null = promise.get("空值承诺", "不允许为空") == "允许为空"
        value_domain = promise.get("取值域", "")

        # 空值校验
        if actual_value is None and not allows_null:
            self._record_breach(promise, f"字段{field_name}不允许为空但实际值为空")
            return False, f"字段{field_name}不允许为空"

        if actual_value is None and allows_null:
            promise["status"] = "已达标"
            promise["abnormal"] = False
            return True, "字段允许为空，校验通过"

        # 类型校验
        if expected_type and actual_value is not None:
            type_map = {"int": int, "float": float, "str": str, "bool": bool}
            expected_py = type_map.get(expected_type)
            if expected_py and not isinstance(actual_value, expected_py):
                self._record_breach(promise, f"字段{field_name}类型不匹配")
                return False, f"期望类型{expected_type}，实际{type(actual_value).__name__}"

        # 取值域校验
        if value_domain and actual_value is not None:
            allowed = [v.strip() for v in value_domain.split(",") if v.strip()]
            if allowed and str(actual_value) not in allowed:
                self._record_breach(promise, f"字段{field_name}取值{actual_value}不在域{value_domain}")
                return False, f"取值{actual_value}不在允许域中"

        promise["status"] = "已达标"
        promise["abnormal"] = False
        return True, "校验通过"

    def _record_breach(self, promise: dict[str, Any], reason: str) -> None:
        """记录违约并累加计数。"""
        promise["status"] = "违约中"
        promise["abnormal"] = True
        current = int(promise.get("违约次数", "0") or "0")
        promise["违约次数"] = str(current + 1)

    def get_promises_by_version(self, version_id: str) -> list[dict[str, Any]]:
        """按版本获取全部字段承诺。"""
        return [
            p for p in store.rows(self.MODULE)
            if p.get("所属版本") == version_id
        ]

    def get_breach_summary(self, contract_id: str) -> dict[str, Any]:
        """获取契约下全部字段承诺的违约摘要。"""
        all_promises = [
            p for p in store.rows(self.MODULE)
            if p.get("所属版本", "").startswith(f"VER-{contract_id}")
        ]
        breached = [p for p in all_promises if p.get("status") == "违约中"]
        return {
            "total_promises": len(all_promises),
            "breached": len(breached),
            "breach_rate": f"{len(breached)/max(len(all_promises),1)*100:.1f}%",
            "breach_fields": [p.get("字段名称") for p in breached],
        }