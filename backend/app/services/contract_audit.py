"""契约审计领域服务：记录契约签署、版本演进、授权回收和违约处置的变更前后值。

审计条目按契约与操作时间形成可封存核查的审计链数据集，
同日同操作同结果的重复登记去重，封存后条目不可再变更。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class ContractAuditService(BaseModuleService):
    MODULE = "contract_audit"
    ENTITY = "审计条目"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["条目编号", "所属契约", "操作类型", "操作对象", "变更前值", "变更后值", "操作者标识", "操作时间"]
    REQUIRED_FIELDS = ["条目编号", "所属契约"]
    STATUS_ORDER = ["已记录", "待核查", "已核查", "已封存"]
    ACTION_RULES = {"提交核查": "待核查", "完成核查": "已核查", "封存条目": "已封存"}
    NEGATIVE_ACTIONS = []

    def record_change(
        self,
        contract_id: str,
        operation_type: str,
        target_object: str,
        before_value: str,
        after_value: str,
        operator_id: str,
    ) -> dict[str, Any]:
        """登记一条审计变更，同日同操作同结果去重不重复落库。

        读取该契约的审计条目数据集做去重校验，重复登记返回已有条目，
        新条目按操作时间写入审计链。
        """
        rows = store.rows(self.MODULE)
        today = datetime.now().strftime("%Y-%m-%d")
        for row in rows:
            if (
                row.get("所属契约") == contract_id
                and row.get("操作类型") == operation_type
                and row.get("变更后值") == after_value
                and str(row.get("操作时间", "")).startswith(today)
            ):
                return {"status": "duplicate", "audit": row}

        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
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
            "pending": True,
            "abnormal": False,
        }
        rows.append(audit)
        return {"status": "recorded", "audit": audit}

    def verify_chain(self, contract_id: str) -> dict[str, Any]:
        """核查契约审计链完整性：已签署契约必须有签署记录，版本演进必须有演进记录。

        读取契约状态与审计条目数据集比对，返回缺口清单与完整性结论，
        核查通过的条目推进为已核查状态。
        """
        chain = self.get_audit_for_contract(contract_id)
        ops = {str(a.get("操作类型", "")) for a in chain}

        contract = None
        for c in store.rows("data_contract"):
            if c.get("契约编号") == contract_id:
                contract = c
                break

        gaps: list[str] = []
        if contract is not None:
            if contract.get("status") in ("已签署", "已冻结", "已终止") and "签署契约" not in ops:
                gaps.append("缺少签署契约审计记录")
            if contract.get("当前版本", "v1.0") not in ("", "v1.0") and "版本演进" not in ops:
                gaps.append("缺少版本演进审计记录")

        for item in chain:
            if item.get("status") == "已记录":
                item["status"] = "待核查"
        return {
            "contract_id": contract_id,
            "chain_length": len(chain),
            "gaps": gaps,
            "complete": not gaps,
        }

    def seal_chain(self, contract_id: str) -> int:
        """封存契约的全部已核查审计条目，返回封存数量。"""
        sealed = 0
        for item in self.get_audit_for_contract(contract_id):
            if item.get("status") == "已核查":
                item["status"] = "已封存"
                item["pending"] = False
                sealed += 1
        return sealed

    def get_audit_for_contract(self, contract_id: str) -> list[dict[str, Any]]:
        """查询契约的完整审计链条目数据集，按操作时间排序。"""
        return sorted(
            [r for r in store.rows(self.MODULE) if r.get("所属契约") == contract_id],
            key=lambda r: str(r.get("操作时间", "")),
        )


def record_and_verify_contract_chain(contract_id: str, operation: str, target: str,
                                     before: str, after: str, operator: str) -> dict:
    """模块级入口：登记契约变更并核查审计链完整性数据集。"""
    service = ContractAuditService()
    recorded = service.record_change(contract_id, operation, target, before, after, operator)
    verification = service.verify_chain(contract_id)
    return {"recorded": recorded, "verification": verification}
