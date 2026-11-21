"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ServiceEndpointService(BaseModuleService):
    MODULE = "service_endpoint"
    ENTITY = "查询端点"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["端点编号", "所属契约", "端点路径", "支持筛选", "分页上限", "返回列集合", "缓存开关", "最近发布"]
    REQUIRED_FIELDS = ["端点编号", "所属契约", "端点路径"]
    STATUS_ORDER = ["草稿", "已发布", "灰度中", "已下线"]
    ACTION_RULES = {"发布端点": "已发布", "启动灰度": "灰度中", "下线端点": "已下线"}
    NEGATIVE_ACTIONS = ["下线端点"]
