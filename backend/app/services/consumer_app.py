"""消费方应用领域服务：登记接入数据服务的消费方应用及其调用峰值。

应用接入时同步创建限流配额条目，调用峰值超限自动限流并刷新最近调用水位。
订阅与授权均以消费方应用为主体，一个应用可绑定多份契约的数据集。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class ConsumerAppService(BaseModuleService):
    MODULE = "consumer_app"
    ENTITY = "消费方应用"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["应用编号", "应用名称", "所属团队", "接入方式", "调用峰值", "绑定契约数", "接入时间", "最近调用"]
    REQUIRED_FIELDS = ["应用编号", "应用名称", "所属团队"]
    STATUS_ORDER = ["待接入", "已接入", "已限流", "已下线"]
    ACTION_RULES = {"确认接入": "已接入", "限流应用": "已限流", "下线应用": "已下线"}
    NEGATIVE_ACTIONS = []

    def register_app_with_quota(
        self,
        app_id: str,
        app_name: str,
        team: str,
        access_mode: str,
        peak_calls: int,
    ) -> dict[str, Any]:
        """接入消费方应用并同步写入限流配额条目。

        读取应用登记数据集去重校验，新应用落库后按调用峰值
        初始化该应用的日级配额记录，供查询链路消费。
        """
        rows = store.rows(self.MODULE)
        for row in rows:
            if row.get("应用编号") == app_id:
                return {"status": "duplicate", "app": row}

        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        app = {
            "id": new_id,
            "应用编号": app_id,
            "应用名称": app_name,
            "所属团队": team,
            "接入方式": access_mode,
            "调用峰值": str(peak_calls),
            "绑定契约数": "0",
            "接入时间": datetime.now().strftime("%Y-%m-%d"),
            "最近调用": "",
            "status": "已接入",
            "pending": True,
            "abnormal": False,
        }
        rows.append(app)

        quota_rows = store.rows("rate_quota")
        quota_id = max((int(r.get("id", 0)) for r in quota_rows), default=0) + 1
        quota_rows.append({
            "id": quota_id,
            "配额编号": f"QUOTA-{quota_id:04d}",
            "消费方应用": app_id,
            "所属端点": "",
            "秒级上限": str(max(10, peak_calls // 100)),
            "日级上限": str(peak_calls * 10),
            "当前用量": "0",
            "超额处置": "降级返回部分数据",
            "计量窗口": datetime.now().strftime("%Y-%m"),
            "status": "充足",
            "pending": True,
            "abnormal": False,
        })
        return {"status": "registered", "app": app, "quota_id": quota_id}

    def check_peak_and_limit(self, app_id: str, current_calls: int) -> dict[str, Any]:
        """校验当前调用量是否超过峰值，超限把应用标记为已限流。"""
        app = self._find_by_app_id(app_id)
        if app is None:
            return {"status": "error", "message": f"应用 {app_id} 不存在"}
        peak = int(app.get("调用峰值", "0") or "0")
        if peak and current_calls > peak:
            app["status"] = "已限流"
            app["abnormal"] = True
            return {"status": "limited", "peak": peak, "current": current_calls}
        return {"status": "normal", "peak": peak, "current": current_calls}

    def refresh_call_watermark(self, app_id: str) -> None:
        """刷新应用最近调用水位时间。"""
        app = self._find_by_app_id(app_id)
        if app is not None:
            app["最近调用"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def count_bound_contracts(self, app_id: str) -> int:
        """聚合统计应用绑定的生效订阅契约数量并回写。"""
        count = len({
            s.get("所属契约") for s in store.rows("subscription_plan")
            if s.get("消费方应用") == app_id and s.get("status") == "生效中"
        })
        app = self._find_by_app_id(app_id)
        if app is not None:
            app["绑定契约数"] = str(count)
        return count

    def get_active_apps(self) -> list[dict[str, Any]]:
        """查询全部已接入的应用数据集。"""
        return [r for r in store.rows(self.MODULE) if r.get("status") == "已接入"]

    def _find_by_app_id(self, app_id: str) -> dict[str, Any] | None:
        for row in store.rows(self.MODULE):
            if row.get("应用编号") == app_id:
                return row
        return None
