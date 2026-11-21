"""契约审计领域服务：记录契约签署、版本演进、授权回收和违约处置的变更前后值。

形成可封存核查的审计链，支持按操作类型、时间范围与操作者筛选查询。
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

    def get_audit_for_contract(self, contract_id: str) -> list[dict[str, Any]]:
        """获取契约的完整审计链条目列表。"""
        return sorted(
            [r for r in store.rows(self.MODULE) if r.get("所属契约") == contract_id],
            key=lambda r: r.get("操作时间", "")
        )

    def verify_chain_integrity(self, contract_id: str) -> dict[str, Any]:
        """验证审计链完整性并标记缺失操作。"""
        chain = self.get_audit_for_contract(contract_id)
        ops = {r.get("操作类型") for r in chain}
        missing = [op for op in ("签署契约", "版本演进") if op not in ops]
        return {"complete": len(missing) == 0, "chain_length": len(chain), "missing": missing}
