"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class SlaTargetService(BaseModuleService):
    MODULE = "sla_target"
    ENTITY = "等级目标"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["目标编号", "所属契约", "目标类型", "目标阈值", "统计窗口", "当前达成率", "违约处置", "最近结算"]
    REQUIRED_FIELDS = ["目标编号", "所属契约", "目标类型"]
    STATUS_ORDER = ["已设定", "结算中", "达标", "未达标"]
    ACTION_RULES = {"启动结算": "结算中", "确认达标": "达标", "记录未达标": "未达标"}
    NEGATIVE_ACTIONS = []
