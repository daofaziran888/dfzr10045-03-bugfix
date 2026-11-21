"""查询端点领域服务：把契约发布成服务化查询端点。

支持声明筛选条件、分页上限与返回列集合。端点与契约版本一一对应，灰度与正式发布分离。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class ServiceEndpointService(BaseModuleService):
    MODULE = "service_endpoint"
    ENTITY = "查询端点"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["端点编号", "所属契约", "端点路径", "支持筛选", "分页上限", "返回列集合", "缓存开关", "最近发布"]
    REQUIRED_FIELDS = ["端点编号", "所属契约", "端点路径"]
    STATUS_ORDER = ["草稿", "已发布", "灰度中", "已下线"]
    ACTION_RULES = {"发布端点": "已发布", "启动灰度": "灰度中", "下线端点": "已下线"}
    NEGATIVE_ACTIONS = []

    def get_endpoints_for_contract(self, contract_id: str) -> list[dict[str, Any]]:
        """获取契约的全部查询端点。"""
        return [r for r in store.rows(self.MODULE) if r.get("所属契约") == contract_id]

    def validate_cache_config(self, endpoint_id: str) -> dict[str, Any]:
        """校验端点缓存配置与缓存策略一致性。"""
        for cp in store.rows("cache_policy"):
            if cp.get("所属端点") == endpoint_id:
                return {"valid": True, "ttl": cp.get("存活秒数", "3600")}
        return {"valid": False, "reason": "未关联缓存策略"}
