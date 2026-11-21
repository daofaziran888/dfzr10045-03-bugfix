"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class DualRunService(BaseModuleService):
    MODULE = "dual_run"
    ENTITY = "双跑记录"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["双跑编号", "关联对账", "旧口径版本", "新口径版本", "比对样本数", "一致行数", "偏离行数", "双跑结论"]
    REQUIRED_FIELDS = ["双跑编号", "关联对账", "旧口径版本"]
    STATUS_ORDER = ["并行中", "比对中", "已收敛", "偏离超限"]
    ACTION_RULES = {"启动比对": "比对中", "确认收敛": "已收敛", "标记超限": "偏离超限"}
    NEGATIVE_ACTIONS = []
