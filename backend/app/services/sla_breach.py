"""违约事件领域服务：记录服务等级目标未达成产生的违约事件数据集。

违约事件按处置状态机单向推进（已登记→处置中→已关闭/已升级），
升级事件的处置结论回写契约承诺等级，影响应用数从订阅计划聚合。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class SlaBreachService(BaseModuleService):
    MODULE = "sla_breach"
    ENTITY = "违约事件"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["事件编号", "所属目标", "违约窗口", "实际读数", "偏离幅度", "影响应用数", "处置结论", "事件时间"]
    STATUS_ORDER = ["已登记", "处置中", "已关闭", "已升级"]
    REQUIRED_FIELDS = ["事件编号", "所属目标", "违约窗口"]
    ACTION_RULES = {"启动处置": "处置中", "关闭事件": "已关闭", "升级事件": "已升级"}
    NEGATIVE_ACTIONS = []

    def create_from_settlement(
        self,
        target_id: str,
        threshold: float,
        achievement: float,
        window: str,
    ) -> dict[str, Any]:
        """从SLA结算结果生成违约事件：计算偏离幅度并聚合影响应用数。

        读取等级目标关联的契约与订阅计划数据集，统计生效订阅的
        消费方应用数量作为影响应用数，事件初始状态为已登记。
        """
        target = None
        for t in store.rows("sla_target"):
            if t.get("目标编号") == target_id:
                target = t
                break
        contract_id = target.get("所属契约", "") if target else ""
        affected = len({
            s.get("消费方应用") for s in store.rows("subscription_plan")
            if s.get("所属契约") == contract_id and s.get("status") == "生效中"
        })
        deviation = round(max(0.0, threshold - achievement), 2)
        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        breach = {
            "id": new_id,
            "事件编号": f"BRCH-{new_id:04d}",
            "所属目标": target_id,
            "违约窗口": window,
            "实际读数": f"{achievement}%",
            "偏离幅度": f"{deviation}%",
            "影响应用数": str(max(affected, 1)),
            "处置结论": "",
            "事件时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已登记",
            "pending": True,
            "abnormal": True,
        }
        rows.append(breach)
        return breach

    def escalate(self, breach_id: str, reason: str) -> dict[str, Any]:
        """升级违约事件并把处置结论回写契约承诺等级。

        已关闭的事件不能升级；升级后读取目标关联契约，把承诺等级
        降一档并标记异常，变更同时写入契约审计条目数据集。
        """
        breach = self._find_by_breach_id(breach_id)
        if breach is None:
            return {"status": "error", "message": f"违约事件 {breach_id} 不存在"}
        if breach.get("status") == "已关闭":
            return {"status": "error", "message": "已关闭的事件不能升级"}
        if breach.get("status") == "已升级":
            return {"status": "error", "message": "事件已升级，不能重复升级"}

        breach["status"] = "已升级"
        breach["处置结论"] = f"升级：{reason}"
        breach["abnormal"] = True

        contract_id = self._resolve_contract(breach.get("所属目标", ""))
        downgraded = ""
        if contract_id:
            for contract in store.rows("data_contract"):
                if contract.get("契约编号") == contract_id:
                    old_level = str(contract.get("承诺等级", ""))
                    downgraded = self._downgrade_level(old_level)
                    contract["承诺等级"] = downgraded
                    contract["abnormal"] = True
                    audit_rows = store.rows("contract_audit")
                    audit_id = max((int(r.get("id", 0)) for r in audit_rows), default=0) + 1
                    audit_rows.append({
                        "id": audit_id,
                        "条目编号": f"AUD-{audit_id:04d}",
                        "所属契约": contract_id,
                        "操作类型": "违约处置",
                        "操作对象": "sla_breach",
                        "变更前值": old_level,
                        "变更后值": downgraded,
                        "操作者标识": "sla-engine",
                        "操作时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "已记录",
                        "pending": True,
                        "abnormal": False,
                    })
        return {
            "status": "escalated",
            "breach_id": breach_id,
            "contract_id": contract_id,
            "downgraded_level": downgraded,
        }

    def _downgrade_level(self, level: str) -> str:
        """承诺等级降一档：金级→银级→铜级，铜级维持并追加违约标记。"""
        base = level.split("(")[0]
        mapping = {"金级": "银级", "银级": "铜级", "铜级": "铜级"}
        new_level = mapping.get(base, base)
        suffix = "(违约降级)" if new_level != base else "(违约待观察)"
        return new_level + suffix

    def _resolve_contract(self, target_id: str) -> str:
        for t in store.rows("sla_target"):
            if t.get("目标编号") == target_id:
                return str(t.get("所属契约", ""))
        return ""

    def _find_by_breach_id(self, breach_id: str) -> dict[str, Any] | None:
        for row in store.rows(self.MODULE):
            if row.get("事件编号") == breach_id:
                return row
        return None

    def get_active_breaches(self) -> list[dict[str, Any]]:
        """查询全部未关闭的违约事件数据集。"""
        return [
            r for r in store.rows(self.MODULE)
            if r.get("status") in ("已登记", "处置中", "已升级")
        ]
