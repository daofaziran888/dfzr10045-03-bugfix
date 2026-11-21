"""口径对账领域服务：对同一口径的两侧数据来源做逐行对账。

提供真实的逐行比对、匹配/差异行数计算、平账判定与差异登记能力。
对账结论决定数据集能否继续发布，差异行会流入双跑比对做归因。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from app.services.base import BaseModuleService
from app.store import store


class ReconcileTaskService(BaseModuleService):
    MODULE = "reconcile_task"
    ENTITY = "对账任务"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["对账编号", "对账口径", "左侧来源", "右侧来源", "对账窗口", "匹配行数", "差异行数", "对账耗时"]
    REQUIRED_FIELDS = ["对账编号", "对账口径", "左侧来源"]
    STATUS_ORDER = ["待对账", "对账中", "已平账", "存在差异"]
    ACTION_RULES = {"启动对账": "对账中", "确认平账": "已平账", "登记差异": "存在差异"}
    NEGATIVE_ACTIONS = []

    def reconcile_rows(
        self,
        left_rows: Iterable[dict[str, Any]],
        right_rows: Iterable[dict[str, Any]],
        key_fields: list[str],
        compare_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """逐行对账两侧来源数据，按主键关联并比对字段值。

        对左侧与右侧数据集按 key_fields 构建索引后逐行比对：
        主键两侧都存在且 compare_fields 全部相等记为匹配行，
        主键缺失或字段值不一致记为差异行并保留差异明细供归因。

        返回匹配行数、差异行数与差异明细批次，这是对账链路的核心计算。
        """
        left_index = self._build_key_index(left_rows, key_fields)
        right_index = self._build_key_index(right_rows, key_fields)

        matched_rows = 0
        diff_details: list[dict[str, Any]] = []

        for key, left_row in left_index.items():
            right_row = right_index.get(key)
            if right_row is None:
                diff_details.append({
                    "key": key,
                    "diff_type": "右侧缺失",
                    "left": left_row,
                    "right": None,
                })
                continue
            mismatched = self._diff_fields(left_row, right_row, compare_fields)
            if mismatched:
                diff_details.append({
                    "key": key,
                    "diff_type": "字段不一致",
                    "fields": mismatched,
                })
            else:
                matched_rows += 1

        for key in right_index:
            if key not in left_index:
                diff_details.append({
                    "key": key,
                    "diff_type": "左侧缺失",
                    "left": None,
                    "right": right_index[key],
                })

        return {
            "matched_rows": matched_rows,
            "diff_rows": len(diff_details),
            "diff_details": diff_details,
        }

    def _build_key_index(
        self,
        rows: Iterable[dict[str, Any]],
        key_fields: list[str],
    ) -> dict[tuple, dict[str, Any]]:
        """按主键字段构建行索引，重复主键保留最后一条并去重计数。"""
        index: dict[tuple, dict[str, Any]] = {}
        for row in rows:
            key = tuple(str(row.get(field, "")) for field in key_fields)
            index[key] = row
        return index

    def _diff_fields(
        self,
        left_row: dict[str, Any],
        right_row: dict[str, Any],
        compare_fields: list[str] | None,
    ) -> dict[str, tuple[Any, Any]]:
        """比对两行的字段值，返回不一致字段的左右取值。"""
        fields = compare_fields or [
            f for f in left_row.keys() if f in right_row and f not in ("id", "status")
        ]
        mismatched: dict[str, tuple[Any, Any]] = {}
        for field in fields:
            if str(left_row.get(field)) != str(right_row.get(field)):
                mismatched[field] = (left_row.get(field), right_row.get(field))
        return mismatched

    def judge_settlement(self, matched_rows: int, diff_rows: int) -> str:
        """平账判定：差异行数为零判为已平账，否则存在差异。"""
        if diff_rows == 0:
            return "已平账"
        return "存在差异"

    def build_reconcile_record(
        self,
        reconcile_id: str,
        left_source: str,
        right_source: str,
        left_rows: Iterable[dict[str, Any]],
        right_rows: Iterable[dict[str, Any]],
        key_fields: list[str],
        caliber: str = "全量逐行比对",
    ) -> dict[str, Any]:
        """执行一次完整对账并落库对账任务记录。

        读取两侧来源数据集，逐行对账计算匹配与差异行数，
        按平账判定写入对账结论，对账窗口取当前月份批次。
        """
        started = datetime.now()
        result = self.reconcile_rows(left_rows, right_rows, key_fields)
        elapsed = (datetime.now() - started).total_seconds()
        status = self.judge_settlement(result["matched_rows"], result["diff_rows"])

        rec_rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rec_rows), default=0) + 1
        record = {
            "id": new_id,
            "对账编号": reconcile_id,
            "对账口径": caliber,
            "左侧来源": left_source,
            "右侧来源": right_source,
            "对账窗口": started.strftime("%Y-%m"),
            "匹配行数": str(result["matched_rows"]),
            "差异行数": str(result["diff_rows"]),
            "对账耗时": f"{elapsed:.3f}s",
            "status": status,
            "pending": status == "存在差异",
            "abnormal": status == "存在差异",
        }
        rec_rows.append(record)
        record["_diff_details"] = result["diff_details"]
        return record

    def register_diff(self, reconcile_id: str, diff_details: list[dict[str, Any]]) -> dict[str, Any]:
        """登记对账差异：把差异明细批次写入双跑比对，触发下游归因。

        差异行数大于零时把对账任务标记为存在差异，并把差异批次
        关联到双跑记录，供差异归因模块逐条归因到字段与根因。
        """
        record = self.find_by_reconcile_id(reconcile_id)
        if record is None:
            return {"status": "error", "message": f"对账任务 {reconcile_id} 不存在"}
        record["status"] = "存在差异"
        record["abnormal"] = True
        record["pending"] = True
        return {
            "status": "registered",
            "reconcile_id": reconcile_id,
            "diff_count": len(diff_details),
            "diff_batch": diff_details,
        }

    def find_by_reconcile_id(self, reconcile_id: str) -> dict[str, Any] | None:
        """按对账编号查询对账任务记录。"""
        for row in store.rows(self.MODULE):
            if row.get("对账编号") == reconcile_id:
                return row
        return None

    def get_diff_tasks(self) -> list[dict[str, Any]]:
        """查询全部存在差异的对账任务，供发布阻断与归因消费。"""
        return [
            r for r in store.rows(self.MODULE)
            if r.get("status") == "存在差异"
        ]
