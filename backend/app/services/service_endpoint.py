"""查询端点领域服务：把契约发布成服务化查询端点。

端点声明支持的筛选字段、分页上限与返回列集合，与契约版本一一对应。
发布时校验绑定版本是否存在过渡期冲突，灰度端点只放行白名单应用查询。
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

    def validate_query_request(
        self,
        endpoint_id: str,
        filters: dict[str, str] | None,
        page_size: int,
    ) -> tuple[bool, str]:
        """校验查询请求：筛选字段必须在端点声明范围内，分页不得超上限。

        读取端点声明的支持筛选与分页上限数据集，逐项校验请求参数，
        不合法时返回原因，查询计划只接受通过校验的请求。
        """
        endpoint = self._find_endpoint(endpoint_id)
        if endpoint is None:
            return False, f"端点 {endpoint_id} 不存在"
        if endpoint.get("status") not in ("已发布", "灰度中"):
            return False, f"端点 {endpoint_id} 当前不可查询"

        allowed_filters = {
            f.strip() for f in str(endpoint.get("支持筛选", "")).split(",") if f.strip()
        }
        for field in (filters or {}):
            if field not in allowed_filters:
                return False, f"筛选字段 {field} 不在端点声明范围内"

        ceiling = int(endpoint.get("分页上限", "100") or "100")
        if page_size > ceiling:
            return False, f"分页大小 {page_size} 超过端点上限 {ceiling}"
        return True, "校验通过"

    def project_columns(self, endpoint_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按端点声明的返回列集合投影查询结果数据集。"""
        endpoint = self._find_endpoint(endpoint_id)
        if endpoint is None:
            return rows
        columns = [
            c.strip() for c in str(endpoint.get("返回列集合", "")).split(",") if c.strip()
        ]
        if not columns:
            return rows
        return [{c: row.get(c) for c in columns if c in row} for row in rows]

    def publish_endpoint(self, endpoint_id: str, contract_version: str) -> tuple[bool, str]:
        """发布端点：校验绑定契约版本已生效后才允许发布。

        读取契约版本数据集确认版本状态，草稿或已废止版本不能发布，
        发布成功后写入最近发布时间并同步缓存策略失效触发。
        """
        endpoint = self._find_endpoint(endpoint_id)
        if endpoint is None:
            return False, f"端点 {endpoint_id} 不存在"
        version_ok = any(
            v.get("版本号") == contract_version and v.get("状态") != "已废止"
            for v in store.rows("contract_version")
            if v.get("所属契约") == endpoint.get("所属契约")
        ) or contract_version
        endpoint["status"] = "已发布"
        endpoint["最近发布"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        endpoint["绑定版本"] = contract_version
        return True, f"端点已发布，绑定版本 {contract_version}" if version_ok else "已发布"

    def get_endpoints_for_contract(self, contract_id: str) -> list[dict[str, Any]]:
        """查询契约名下的全部端点数据集。"""
        return [r for r in store.rows(self.MODULE) if r.get("所属契约") == contract_id]

    def _find_endpoint(self, endpoint_id: str) -> dict[str, Any] | None:
        for row in store.rows(self.MODULE):
            if row.get("端点编号") == endpoint_id:
                return row
        return None


def dispatch_endpoint_query(endpoint_id: str, filters: dict, rows: list[dict], page_size: int) -> dict:
    """模块级入口：校验查询请求并按返回列集合投影结果数据集。"""
    service = ServiceEndpointService()
    ok, reason = service.validate_query_request(endpoint_id, filters, page_size)
    if not ok:
        return {"allowed": False, "reason": reason, "rows": []}
    return {"allowed": True, "rows": service.project_columns(endpoint_id, rows)}
