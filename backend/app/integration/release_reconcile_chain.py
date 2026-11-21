"""发布与口径对账链路：数据集发布→口径对账→双跑比对→差异归因。

链路真实调用各领域服务：ReconcileTaskService 逐行对账两侧来源数据集，
DualRunService 比对新旧口径样本，DiffAttribService 逐条归因偏离字段，
DatasetReleaseService 按准入结论发布批次。对账存在差异时阻断发布。
"""
from __future__ import annotations

from typing import Any

from app.services.dataset_release import DatasetReleaseService
from app.services.diff_attrib import DiffAttribService
from app.services.dual_run import DualRunService
from app.services.reconcile_task import ReconcileTaskService


def release_dataset_with_reconcile(
    dataset_name: str,
    version_id: str,
    left_rows: list[dict[str, Any]],
    right_rows: list[dict[str, Any]],
    key_fields: list[str],
    subscribe_scope: str,
    release_tag: str,
) -> dict[str, Any]:
    """链路9：数据集发布——经真实逐行对账校验后发布。

    输入：数据集名称+版本+两侧来源数据集+主键字段 → 处理：逐行对账、平账判定 → 产物：发布批次+对账记录。
    对账结论决定数据集能否继续发布；存在差异时登记差异批次并阻断。
    """
    reconcile_service = ReconcileTaskService()
    reconcile_id = f"RECON-{dataset_name}"
    reconcile_record = reconcile_service.build_reconcile_record(
        reconcile_id=reconcile_id,
        left_source=f"{version_id}-source-a",
        right_source=f"{version_id}-source-b",
        left_rows=left_rows,
        right_rows=right_rows,
        key_fields=key_fields,
    )

    if reconcile_record["status"] == "存在差异":
        diff_details = reconcile_record.pop("_diff_details", [])
        registered = reconcile_service.register_diff(reconcile_id, diff_details)
        return {
            "status": "blocked",
            "reason": "对账存在差异，不能发布",
            "reconcile": reconcile_record,
            "diff_registered": registered,
        }
    reconcile_record.pop("_diff_details", None)

    release_service = DatasetReleaseService()
    result = release_service.publish(
        dataset_name=dataset_name,
        version_id=version_id,
        row_count=len(right_rows),
        subscribe_scope=subscribe_scope,
        release_tag=release_tag,
    )
    return {"status": result["status"], "release": result.get("release"), "reconcile": reconcile_record}


def dual_run_and_attribute(
    reconcile_id: str,
    old_caliber_version: str,
    new_caliber_version: str,
    old_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
    key_fields: list[str],
    compare_fields: list[str] | None = None,
    attributor: str = "system",
) -> dict[str, Any]:
    """链路10：双跑比对与差异归因——新旧口径并行期间逐行比对样本数据集。

    输入：对账标识+新旧口径版本+两侧样本数据集 → 处理：逐行比对、收敛判定、偏离归因 → 产物：双跑记录+归因条目。
    一致与偏离行数共同构成契约版本切换依据；偏离明细逐条归因到字段与根因类别。
    """
    dual_service = DualRunService()
    comparison = dual_service.compare_samples(
        old_rows=old_rows,
        new_rows=new_rows,
        key_fields=key_fields,
        compare_fields=compare_fields,
    )
    dual = dual_service.build_dual_run(
        reconcile_id=reconcile_id,
        old_version=old_caliber_version,
        new_version=new_caliber_version,
        comparison=comparison,
    )
    divergent_details = dual.pop("_divergent_details", [])

    attrib_service = DiffAttribService()
    attributions = attrib_service.attribute_divergences(
        dual_id=int(dual["id"]),
        divergent_details=divergent_details,
        attributor=attributor,
    )

    finalized = dual_service.finalize(int(dual["id"]))
    return {
        "dual_run": finalized.get("dual", dual),
        "consistent_rows": comparison["consistent_rows"],
        "divergent_rows": comparison["divergent_rows"],
        "attributions": attributions,
    }
