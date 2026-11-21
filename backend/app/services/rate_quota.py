"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class RateQuotaService(BaseModuleService):
    MODULE = "rate_quota"
    ENTITY = "限流配额"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["配额编号", "消费方应用", "所属端点", "秒级上限", "日级上限", "当前用量", "超额处置", "计量窗口"]
    REQUIRED_FIELDS = ["配额编号", "消费方应用", "所属端点"]
    STATUS_ORDER = ["充足", "接近上限", "已超额", "已冻结"]
    ACTION_RULES = {"调整配额": "接近上限", "记录超额": "已超额", "冻结配额": "已冻结"}
    NEGATIVE_ACTIONS = []
