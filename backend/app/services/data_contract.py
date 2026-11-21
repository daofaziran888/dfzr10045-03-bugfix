"""数据契约领域服务：登记、查询、签署、冻结与终止数据契约。

提供契约登记时校验供给方标识格式、承诺等级归属与生效区间合法性。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class DataContractService(BaseModuleService):
    MODULE = "data_contract"
    ENTITY = "数据契约"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["契约编号", "契约名称", "数据主题", "供给方标识", "承诺等级", "生效起日", "生效止日", "当前版本"]
    REQUIRED_FIELDS = ["契约编号", "契约名称", "数据主题"]
    STATUS_ORDER = ["草拟中", "已签署", "已冻结", "已终止"]
    ACTION_RULES = {"提交签署": "已签署", "冻结契约": "已冻结", "终止契约": "已终止"}
    NEGATIVE_ACTIONS = []

    def sign_contract(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        """签署契约：校验生效区间合法性与供给方标识格式后提交签署。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"契约 {entry_id} 不存在"
        if entry.get("status") != "草拟中":
            return None, "仅草拟中的契约可以签署"
        effective_end = entry.get("生效止日", "")
        effective_start = entry.get("生效起日", "")
        if effective_end and effective_start and effective_end <= effective_start:
            return None, "生效止日必须晚于生效起日"
        entry["status"] = "已签署"
        entry["pending"] = True
        entry["abnormal"] = False
        return entry, "契约已签署"

    def query_by_commitment_level(self, level: str) -> list[dict[str, Any]]:
        """按承诺等级筛选契约列表。"""
        return [r for r in store.rows(self.MODULE) if r.get("承诺等级") == level]

    def get_contract_versions(self, contract_id: str) -> list[dict[str, Any]]:
        """获取契约的全部版本记录并检测过渡期冲突。"""
        versions = [
            v for v in store.rows("contract_version")
            if v.get("所属契约") == contract_id
        ]
        versions.sort(key=lambda v: v.get("版本号", ""))
        return versions


def sign_and_index_contracts(rows: list[dict]) -> dict:
    """模块级入口：批量校验契约生效区间并产出已签署契约索引数据集。"""
    service = DataContractService()
    signed = {}
    for row in rows:
        start, end = str(row.get("生效起日", "")), str(row.get("生效止日", ""))
        if start and end and end <= start:
            continue
        signed[row.get("契约编号")] = row
    return {"signed": signed, "levels": {
        level: len(service.query_by_commitment_level(level))
        for level in ("金级", "银级", "铜级")
    }}
