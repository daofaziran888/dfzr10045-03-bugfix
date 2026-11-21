"""契约版本领域服务：版本演进、过渡期管理、兼容判定与废止处理。

过渡期内新旧版本的契约数据集并存，消费方按绑定版本读取对应批次明细；
过渡期满后自动生效新版本、废止旧版本，版本水位单向推进不回退。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class ContractVersionService(BaseModuleService):
    MODULE = "contract_version"
    ENTITY = "契约版本"
    OPERATION_TERM = "读取"
    LIST_FIELDS = ["版本编号", "所属契约", "版本号", "变更摘要", "兼容判定", "父版本号", "过渡期天数", "生效时间"]
    REQUIRED_FIELDS = ["版本编号", "所属契约", "版本号"]
    STATUS_ORDER = ["草稿", "过渡中", "已生效", "已废止"]
    ACTION_RULES = {"启动过渡": "过渡中", "生效版本": "已生效", "废止版本": "已废止"}
    NEGATIVE_ACTIONS = []

    def start_transition(self, entry_id: int, transition_days: int) -> tuple[dict[str, Any] | None, str]:
        """启动版本过渡期：写入过渡天数水位并标记过渡中。

        过渡期内该契约版本的批次数据集与旧版本并存，消费方仍按
        绑定版本读取对应明细，不被强制切换。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"版本 {entry_id} 不存在"
        if entry.get("status") != "草稿":
            return None, "仅草稿版本可以启动过渡"
        entry["过渡期天数"] = str(transition_days)
        entry["status"] = "过渡中"
        entry["pending"] = True
        entry["abnormal"] = False
        return entry, f"版本已进入过渡期，过渡{transition_days}天"

    def check_transition_expiry(self, today: datetime | None = None) -> list[dict[str, Any]]:
        """扫描过渡期水位，到期版本自动生效并废止同契约旧版本数据集。"""
        expired: list[dict[str, Any]] = []
        now = today or datetime.now()
        for version in store.rows(self.MODULE):
            if version.get("status") != "过渡中":
                continue
            transit_days = int(version.get("过渡期天数", "0") or "0")
            eff_time_str = str(version.get("生效时间", ""))
            if not eff_time_str:
                continue
            try:
                eff_time = datetime.strptime(eff_time_str[:10], "%Y-%m-%d")
            except ValueError:
                continue
            if now >= eff_time + timedelta(days=transit_days):
                version["status"] = "已生效"
                version["pending"] = False
                expired.append(version)
                self._retire_older_versions(version)
        return expired

    def _retire_older_versions(self, new_version: dict[str, Any]) -> None:
        """新版本生效时把同契约旧生效版本的批次数据集标记为已废止。"""
        contract_id = new_version.get("所属契约", "")
        new_ver = new_version.get("版本号", "")
        for version in store.rows(self.MODULE):
            if (
                version.get("所属契约") == contract_id
                and version.get("版本号") != new_ver
                and version.get("status") == "已生效"
            ):
                version["status"] = "已废止"
                version["pending"] = False
                version["abnormal"] = True

    def readable_versions(self, contract_id: str) -> list[dict[str, Any]]:
        """读取契约当前可被消费方取数的版本数据集（含过渡中版本）。

        过渡期内新旧版本并存，两份版本明细都可读；已废止版本不再返回。
        """
        return [
            v for v in store.rows(self.MODULE)
            if v.get("所属契约") == contract_id
            and v.get("status") in ("已生效", "过渡中")
        ]

    def resolve_bound_version(self, contract_id: str, bound_version: str) -> dict[str, Any] | None:
        """按消费方绑定版本解析其可读的版本明细数据集。"""
        for version in store.rows(self.MODULE):
            if (
                version.get("所属契约") == contract_id
                and version.get("版本号") == bound_version
                and version.get("status") in ("已生效", "过渡中")
            ):
                return version
        return None

    def get_active_versions_for(self, contract_id: str) -> list[dict[str, Any]]:
        """获取契约的活跃版本列表（含过渡中版本）。"""
        return self.readable_versions(contract_id)
