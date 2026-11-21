"""抽样探查领域服务：对已发布数据集做抽样探查并计算字段完整率。

读取发布批次的数据集行数按比例抽样，逐字段统计空值率与异常值条数，
字段完整率或异常值不达标时驳回探查，阻断订阅生效。
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

    COMPLETENESS_FLOOR = 95.0
    ANOMALY_CEILING = 5

    def probe_rows(
        self,
        dataset_name: str,
        rows: list[dict[str, Any]],
        sample_ratio: float,
        required_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """对数据集行样本逐字段探查，计算字段完整率与异常值条数。

        按比例抽取样本行，统计必填字段的空值缺失率得出完整率，
        统计取值异常的条数，产出探查结论数据集。
        """
        sample_size = max(1, int(len(rows) * sample_ratio)) if rows else 0
        sample = rows[:sample_size]
        fields = required_fields or (sorted(sample[0].keys()) if sample else [])

        missing = 0
        anomaly = 0
        for row in sample:
            for field in fields:
                value = row.get(field)
                if value is None or str(value).strip() == "":
                    missing += 1
                elif isinstance(value, str) and value.startswith("ERR"):
                    anomaly += 1
        total_cells = max(1, len(sample) * max(len(fields), 1))
        completeness = round((total_cells - missing) / total_cells * 100.0, 2)
        return {
            "sample_size": len(sample),
            "completeness": completeness,
            "anomaly_count": anomaly,
            "passed": completeness >= self.COMPLETENESS_FLOOR and anomaly <= self.ANOMALY_CEILING,
        }

    def build_probe_record(
        self,
        dataset_name: str,
        sample_ratio: float,
        probe_result: dict[str, Any],
    ) -> dict[str, Any]:
        """落库探查样本记录：按探查结论写入已通过/已驳回状态。"""
        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        passed = probe_result["passed"]
        conclusion = "通过" if passed else (
            f"不通过：完整率{probe_result['completeness']}%低于{self.COMPLETENESS_FLOOR}%"
            f"或异常值{probe_result['anomaly_count']}条超限"
        )
        record = {
            "id": new_id,
            "样本编号": f"PROBE-{new_id:04d}",
            "所属数据集": dataset_name,
            "抽样比例": f"{sample_ratio:.0%}",
            "抽样行数": str(probe_result["sample_size"]),
            "字段完整率": f"{probe_result['completeness']}%",
            "异常值条数": str(probe_result["anomaly_count"]),
            "探查结论": conclusion,
            "探查时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已通过" if passed else "已驳回",
            "pending": not passed,
            "abnormal": not passed,
        }
        rows.append(record)
        return record

    def evaluate_pass_criteria(self, completeness: float, anomaly: int) -> bool:
        """评估抽样探查通过标准：完整率达标且异常值不超限。"""
        return completeness >= self.COMPLETENESS_FLOOR and anomaly <= self.ANOMALY_CEILING

    def get_probes_for_dataset(self, dataset_name: str) -> list[dict[str, Any]]:
        """查询数据集名下的全部探查样本数据集。"""
        return [r for r in store.rows(self.MODULE) if r.get("所属数据集") == dataset_name]


def probe_dataset_sample(dataset_name: str, rows: list[dict], ratio: float,
                         required_fields: list[str] | None = None) -> dict:
    """模块级入口：抽样探查数据集并落库探查结论。"""
    service = SampleProbeService()
    result = service.probe_rows(dataset_name, rows, ratio, required_fields)
    record = service.build_probe_record(dataset_name, ratio, result)
    return {"result": result, "record": record}
