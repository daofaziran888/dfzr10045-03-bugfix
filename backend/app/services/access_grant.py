"""访问授权领域服务：维护应用对端点的可见列范围与行级过滤条件。

授权到期或契约冻结时端点必须立即拒绝该应用取数，回收授权联动暂停
订阅计划；核验时校验授权窗口与行级过滤条件的有效性。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class AccessGrantService(BaseModuleService):
    MODULE = "access_grant"
    ENTITY = "授权记录"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["授权编号", "消费方应用", "所属端点", "可见列范围", "行级过滤条件", "授权起日", "授权止日", "最近核验"]
    REQUIRED_FIELDS = ["授权编号", "消费方应用", "所属端点"]
    STATUS_ORDER = ["待核验", "已授权", "已收窄", "已回收"]
    ACTION_RULES = {"核验授权": "已授权", "收窄范围": "已收窄", "回收授权": "已回收"}
    NEGATIVE_ACTIONS = []

    def authorize(
        self,
        app_id: str,
        endpoint_id: str,
        visible_columns: list[str],
        row_filter: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        """创建访问授权记录，写入可见列范围与行级过滤条件数据集。"""
        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        grant = {
            "id": new_id,
            "授权编号": f"GRANT-{new_id:04d}",
            "消费方应用": app_id,
            "所属端点": endpoint_id,
            "可见列范围": ",".join(visible_columns),
            "行级过滤条件": row_filter,
            "授权起日": start_date,
            "授权止日": end_date,
            "最近核验": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已授权",
            "pending": True,
            "abnormal": False,
        }
        rows.append(grant)
        return grant

    def check_access(self, app_id: str, endpoint_id: str, today: str | None = None) -> dict[str, Any]:
        """核验应用对端点的取数权限：授权过期或契约冻结立即拒绝。

        读取授权记录数据集校验授权窗口，再联查端点绑定契约的状态，
        冻结契约的授权即使未到期也拒绝取数。
        """
        today = today or datetime.now().strftime("%Y-%m-%d")
        grant = None
        for row in store.rows(self.MODULE):
            if (
                row.get("消费方应用") == app_id
                and row.get("所属端点") == endpoint_id
                and row.get("status") in ("已授权", "已收窄")
            ):
                grant = row
                break
        if grant is None:
            return {"allowed": False, "reason": "无有效授权"}
        if not (str(grant.get("授权起日", "")) <= today <= str(grant.get("授权止日", ""))):
            return {"allowed": False, "reason": "授权不在有效窗口内"}
        if self._is_contract_frozen(endpoint_id):
            return {"allowed": False, "reason": "关联契约已冻结"}
        return {"allowed": True, "grant": grant}

    def apply_column_scope(self, grant: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按授权的可见列范围投影数据集，越界列全部剔除。"""
        columns = [c.strip() for c in str(grant.get("可见列范围", "")).split(",") if c.strip()]
        if not columns:
            return rows
        return [{c: r.get(c) for c in columns if c in r} for r in rows]

    def revoke_expired(self, today: str | None = None) -> list[dict[str, Any]]:
        """批量回收到期授权，联动暂停对应订阅，返回回收明细数据集。"""
        today = today or datetime.now().strftime("%Y-%m-%d")
        revoked: list[dict[str, Any]] = []
        for grant in store.rows(self.MODULE):
            if grant.get("status") not in ("已授权", "已收窄"):
                continue
            expired = str(grant.get("授权止日", "2099-12-31")) < today
            frozen = self._is_contract_frozen(str(grant.get("所属端点", "")))
            if expired or frozen:
                grant["status"] = "已回收"
                grant["abnormal"] = True
                revoked.append({
                    "授权编号": grant.get("授权编号"),
                    "消费方应用": grant.get("消费方应用"),
                    "reason": "授权已过期" if expired else "关联契约已冻结",
                })
                self._suspend_related_subscriptions(
                    str(grant.get("消费方应用", "")), str(grant.get("所属端点", ""))
                )
        return revoked

    def _suspend_related_subscriptions(self, app_id: str, endpoint_id: str) -> None:
        """授权回收后暂停该应用通过此端点绑定契约的生效订阅。"""
        contract_id = ""
        for ep in store.rows("service_endpoint"):
            if ep.get("端点编号") == endpoint_id:
                contract_id = str(ep.get("所属契约", ""))
                break
        if not contract_id:
            return
        for sub in store.rows("subscription_plan"):
            if (
                sub.get("消费方应用") == app_id
                and sub.get("所属契约") == contract_id
                and sub.get("status") == "生效中"
            ):
                sub["status"] = "已暂停"
                sub["abnormal"] = True

    def _is_contract_frozen(self, endpoint_id: str) -> bool:
        for ep in store.rows("service_endpoint"):
            if ep.get("端点编号") == endpoint_id:
                contract_id = ep.get("所属契约", "")
                for contract in store.rows("data_contract"):
                    if contract.get("契约编号") == contract_id:
                        return contract.get("status") == "已冻结"
        return False

    def get_grants_for_app(self, app_id: str) -> list[dict[str, Any]]:
        """查询应用名下的全部授权记录数据集。"""
        return [r for r in store.rows(self.MODULE) if r.get("消费方应用") == app_id]
