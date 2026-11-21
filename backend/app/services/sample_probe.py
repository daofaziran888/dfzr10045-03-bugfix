"""抽样探查领域服务：对已发布数据集做全字段完整率与异常值探查。

字段完整率与异常值条数不达标时阻断订阅生效。探查结论写入关联数据集。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class SampleProbeService(BaseModuleService):
    MODULE = "sample_probe"
    ENTITY = "探查样本"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["样本编号", "所属数据集", "抽样比例", "抽样行数", "字段完整率", "异常值条数", "探查结论", "探查时间"]
    REQUIRED_FIELDS = ["样本编号", "所属数据集"]
    STATUS_ORDER = ["待探查", "探查中", "已通过", "已驳回"]
    ACTION_RULES = {"启动探查": "探查中", "通过样本": "已通过", "驳回样本": "已驳回"}
    NEGATIVE_ACTIONS = []

    def get_probes_for_dataset(self, dataset_name: str) -> list[dict[str, Any]]:
        """获取数据集关联的全部探查样本列表。"""
        return [r for r in store.rows(self.MODULE) if r.get("所属数据集") == dataset_name]

    def evaluate_pass_criteria(self, completeness: float, anomaly: int) -> bool:
        """评估抽样探查通过标准。"""
        return completeness >= 95.0 and anomaly <= 5
