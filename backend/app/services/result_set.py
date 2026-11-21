"""结果集快照领域服务：把查询结果冻结成带列摘要值的快照数据集。

同一订阅在有效期内重复读取必须命中同一份快照；快照绑定契约版本，
版本切换或新鲜度滞后时缩短有效期，过期快照标记为已过期不可读。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class ResultSetService(BaseModuleService):
    MODULE = "result_set"
    ENTITY = "结果集快照"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["快照编号", "所属计划", "绑定版本", "快照行数", "列摘要值", "有效期", "引用次数", "生成时间"]
    REQUIRED_FIELDS = ["快照编号", "所属计划"]
    STATUS_ORDER = ["生成中", "可读", "已过期", "已失效"]
    ACTION_RULES = {"标记可读": "可读", "标记过期": "已过期", "强制失效": "已失效"}
    NEGATIVE_ACTIONS = []

    def compute_column_digest(self, rows: list[dict[str, Any]]) -> str:
        """计算结果集数据集的列摘要值，用于快照一致性比对。"""
        if not rows:
            return "empty"
        columns = sorted(rows[0].keys())
        sample = {c: str(rows[0].get(c, ""))[:32] for c in columns[:6]}
        payload = "|".join(f"{k}={v}" for k, v in sorted(sample.items()))
        digest = hashlib.md5(payload.encode("utf-8")).hexdigest()[:16]
        return f"{len(columns)}cols:{digest}"

    def freeze_snapshot(
        self,
        plan_id: int,
        bound_version: str,
        rows: list[dict[str, Any]],
        ttl_seconds: int = 3600,
    ) -> dict[str, Any]:
        """冻结一次查询的结果集为快照数据集并落库。

        写入快照行数与列摘要值，按存活秒数设定有效期水位，
        新生成的快照状态为可读，供同一订阅在有效期内重复命中。
        """
        snap_rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in snap_rows), default=0) + 1
        now = datetime.now()
        snapshot = {
            "id": new_id,
            "快照编号": f"SNAP-{new_id:04d}",
            "所属计划": str(plan_id),
            "绑定版本": bound_version,
            "快照行数": str(len(rows)),
            "列摘要值": self.compute_column_digest(rows),
            "有效期": (now + timedelta(seconds=ttl_seconds)).strftime("%Y-%m-%dT%H:%M:%S"),
            "引用次数": "1",
            "生成时间": now.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "可读",
            "pending": False,
            "abnormal": False,
        }
        snap_rows.append(snapshot)
        return snapshot

    def hit_snapshot(self, plan_id: int, digest: str) -> dict[str, Any] | None:
        """命中同一计划同一摘要的可读快照，命中后引用次数累加。

        有效期内重复读取相同结果集必须返回同一份快照数据集，
        保证消费方读到的明细前后一致。
        """
        for row in store.rows(self.MODULE):
            if (
                row.get("所属计划") == str(plan_id)
                and row.get("列摘要值") == digest
                and row.get("status") == "可读"
                and not self._is_expired(row)
            ):
                row["引用次数"] = str(int(row.get("引用次数", "0") or "0") + 1)
                return row
        return None

    def shorten_validity(self, contract_id: str, lag_minutes: int) -> int:
        """新鲜度滞后时缩短绑定该契约版本的快照有效期，返回受影响数量。"""
        new_expiry = (
            datetime.now() + timedelta(minutes=max(5, 60 - lag_minutes))
        ).strftime("%Y-%m-%dT%H:%M:%S")
        affected = 0
        for row in store.rows(self.MODULE):
            if contract_id in str(row.get("绑定版本", "")) and row.get("status") == "可读":
                row["有效期"] = new_expiry
                affected += 1
        return affected

    def expire_outdated(self) -> int:
        """扫描全部快照，把超过有效期水位的可读快照标记为已过期。"""
        expired = 0
        for row in store.rows(self.MODULE):
            if row.get("status") == "可读" and self._is_expired(row):
                row["status"] = "已过期"
                row["abnormal"] = True
                expired += 1
        return expired

    def _is_expired(self, snapshot: dict[str, Any]) -> bool:
        expiry = str(snapshot.get("有效期", ""))
        if not expiry:
            return False
        return expiry < datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    def get_readable_snapshots(self) -> list[dict[str, Any]]:
        """查询全部可读的快照数据集。"""
        return [r for r in store.rows(self.MODULE) if r.get("status") == "可读"]


def freeze_or_hit_snapshot(plan_id: int, bound_version: str, rows: list[dict], ttl: int = 3600) -> dict:
    """模块级入口：命中已有可读快照或冻结新的结果集快照数据集。"""
    service = ResultSetService()
    digest = service.compute_column_digest(rows)
    hit = service.hit_snapshot(plan_id, digest)
    if hit is not None:
        return {"hit": True, "snapshot": hit}
    return {"hit": False, "snapshot": service.freeze_snapshot(plan_id, bound_version, rows, ttl)}
