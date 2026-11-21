"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class DatasetReleaseService(BaseModuleService):
    MODULE = "dataset_release"
    ENTITY = "发布批次"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["发布编号", "数据集名称", "绑定版本", "数据行数", "对账结论", "可订阅范围", "发布标签", "发布时间"]
    REQUIRED_FIELDS = ["发布编号", "数据集名称", "绑定版本"]
    STATUS_ORDER = ["待发布", "发布中", "已发布", "已撤回"]
    ACTION_RULES = {"启动发布": "发布中", "确认发布": "已发布", "撤回发布": "已撤回"}
    NEGATIVE_ACTIONS = []
