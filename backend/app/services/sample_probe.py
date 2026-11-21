"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class SampleProbeService(BaseModuleService):
    MODULE = "sample_probe"
    ENTITY = "探查样本"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["样本编号", "所属数据集", "抽样比例", "抽样行数", "字段完整率", "异常值条数", "探查结论", "探查时间"]
    REQUIRED_FIELDS = ["样本编号", "所属数据集", "抽样比例"]
    STATUS_ORDER = ["待探查", "探查中", "已通过", "已驳回"]
    ACTION_RULES = {"启动探查": "探查中", "通过样本": "已通过", "驳回样本": "已驳回"}
    NEGATIVE_ACTIONS = ["驳回样本"]
