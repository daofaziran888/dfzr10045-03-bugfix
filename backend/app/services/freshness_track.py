"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class FreshnessTrackService(BaseModuleService):
    MODULE = "freshness_track"
    ENTITY = "新鲜度读数"
    OPERATION_TERM = "水位"
    LIST_FIELDS = ["读数编号", "所属契约", "承诺延迟", "实际延迟", "数据水位", "滞后批次", "滞后原因", "追踪时间"]
    REQUIRED_FIELDS = ["读数编号", "所属契约", "承诺延迟"]
    STATUS_ORDER = ["达标", "轻微滞后", "严重滞后", "追踪中断"]
    ACTION_RULES = {"刷新读数": "轻微滞后", "登记滞后": "严重滞后", "标记中断": "追踪中断"}
    NEGATIVE_ACTIONS = []
