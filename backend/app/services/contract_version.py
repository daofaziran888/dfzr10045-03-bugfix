"""契约版本领域服务：版本演进、过渡期管理、兼容判定与废止处理。

在过渡期内新旧版本并存，消费方按绑定版本读取。过渡期满后自动生效新版本并废止旧版本。
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
        """启动版本过渡期：设置过渡天数并标记过渡中。"""
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

    def check_transition_expiry(self) -> list[dict[str, Any]]:
        """检查过渡期是否到期并自动生效/废止版本。"""
        expired = []
        now = datetime.now()
        for v in store.rows(self.MODULE):
            if v.get("status") == "过渡中":
                transit_days = int(v.get("过渡期天数", "0") or "0")
                eff_time_str = v.get("生效时间", "")
                if eff_time_str:
                    try:
                        eff_time = datetime.strptime(eff_time_str[:10], "%Y-%m-%d")
                        if now >= eff_time + timedelta(days=transit_days):
                            v["status"] = "已生效"
                            v["pending"] = False
                            expired.append(v)
                            self._retire_older_versions(v)
                    except ValueError:
                        pass
        return expired

    def _retire_older_versions(self, new_version: dict[str, Any]) -> None:
        """新版本生效时废止旧的已生效版本。"""
        contract_id = new_version.get("所属契约", "")
        new_ver = new_version.get("版本号", "")
        for v in store.rows(self.MODULE):
            if v.get("所属契约") == contract_id and v.get("版本号") != new_ver and v.get("status") == "已生效":
                v["status"] = "已废止"
                v["pending"] = False
                v["abnormal"] = True

    def get_active_versions_for(self, contract_id: str) -> list[dict[str, Any]]:
        """获取契约的活跃版本列表（含过渡中版本）。"""
        return [
            v for v in store.rows(self.MODULE)
            if v.get("所属契约") == contract_id
            and v.get("status") in ("已生效", "过渡中")
        ]