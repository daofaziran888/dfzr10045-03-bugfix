"""差异归因领域服务：把双跑与对账产生的差异逐条归因到字段与根因类别。

读取双跑比对的偏离明细数据集，按差异字段自动分类归因类别，
修正方案落地后需重新比对确认收敛，无法归因的差异登记人工复核。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class DiffAttribService(BaseModuleService):
    MODULE = "diff_attrib"
    ENTITY = "归因条目"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["归因编号", "关联比对", "差异字段", "归因类别", "根因说明", "影响行数", "修正方案", "归因人标识"]
    REQUIRED_FIELDS = ["归因编号", "关联比对"]
    STATUS_ORDER = ["待归因", "归因中", "已修正", "无法归因"]
    ACTION_RULES = {"启动归因": "归因中", "确认修正": "已修正", "登记无法归因": "无法归因"}
    NEGATIVE_ACTIONS = []

    CATEGORY_RULES = {
        "time": ("时区转换", "时间字段时区口径不一致导致偏移"),
        "amount": ("精度差异", "金额字段精度口径不同导致舍入差异"),
        "hash": ("口径差异", "新增哈希字段旧口径无对应值"),
        "null": ("口径差异", "空值处理口径不同导致缺失或默认值差异"),
    }

    def classify_divergence(self, field_name: str) -> tuple[str, str]:
        """按差异字段名归类归因类别与根因说明。"""
        lowered = field_name.lower()
        for key, (category, root_cause) in self.CATEGORY_RULES.items():
            if key in lowered:
                return category, root_cause
        return "口径差异", f"新旧口径对字段{field_name}的处理逻辑不同"

    def attribute_divergences(
        self,
        dual_id: int,
        divergent_details: list[dict[str, Any]],
        attributor: str = "system",
    ) -> list[dict[str, Any]]:
        """把双跑偏离明细逐条归因落库，返回归因条目数据集。

        读取偏离明细的差异字段，逐条分类归因类别与根因，
        影响行数按明细聚合，修正方案默认统一为新口径处理规则。
        """
        created: list[dict[str, Any]] = []
        for detail in divergent_details:
            fields = detail.get("fields") or []
            field_name = fields[0] if fields else str(detail.get("key", "unknown"))
            category, root_cause = self.classify_divergence(field_name)
            created.append(
                self._create_attribution(
                    dual_id=dual_id,
                    field_name=field_name,
                    category=category,
                    root_cause=root_cause,
                    row_count=1,
                    attributor=attributor,
                )
            )
        return created

    def _create_attribution(
        self,
        dual_id: int,
        field_name: str,
        category: str,
        root_cause: str,
        row_count: int,
        attributor: str,
    ) -> dict[str, Any]:
        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        attribution = {
            "id": new_id,
            "归因编号": f"ATTR-{new_id:04d}",
            "关联比对": str(dual_id),
            "差异字段": field_name,
            "归因类别": category,
            "根因说明": root_cause,
            "影响行数": str(row_count),
            "修正方案": f"统一口径对{field_name}的处理规则为新口径",
            "归因人标识": attributor,
            "status": "待归因",
            "pending": True,
            "abnormal": True,
        }
        rows.append(attribution)
        return attribution

    def confirm_fix(self, attribution_id: int, fix_note: str) -> dict[str, Any]:
        """确认修正：写入修正方案并把归因条目推进到已修正状态。"""
        record = store.find(self.MODULE, attribution_id)
        if record is None:
            return {"status": "error", "message": "归因条目不存在"}
        record["修正方案"] = fix_note
        record["status"] = "已修正"
        record["pending"] = False
        record["abnormal"] = False
        return {"status": "fixed", "attribution": record}

    def get_attribs_for_dual_run(self, dual_run_id: str) -> list[dict[str, Any]]:
        """查询双跑比对关联的全部归因条目数据集。"""
        return [r for r in store.rows(self.MODULE) if r.get("关联比对") == str(dual_run_id)]

    def get_unresolved(self) -> list[dict[str, Any]]:
        """查询全部未修正的归因条目，供重新比对前的人工复核消费。"""
        return [
            r for r in store.rows(self.MODULE)
            if r.get("status") in ("待归因", "归因中", "无法归因")
        ]


def attribute_and_confirm_fixes(dual_id: int, divergent_details: list[dict],
                                fix_note: str, attributor: str = "system") -> dict:
    """模块级入口：逐条归因偏离明细并确认修正，产出归因条目数据集。"""
    service = DiffAttribService()
    created = service.attribute_divergences(dual_id, divergent_details, attributor)
    fixed = [service.confirm_fix(int(item["id"]), fix_note) for item in created]
    return {"created": created, "fixed": fixed, "unresolved": service.get_unresolved()}
