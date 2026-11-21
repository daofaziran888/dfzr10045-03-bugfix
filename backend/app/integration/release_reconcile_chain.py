"""发布与口径对账链路：数据集发布→口径对账→双跑比对→差异归因。

支持双跑比对在新旧口径并行期间运作、差异逐条归因到字段与根因、修正后重新比对确认收敛。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store


def release_dataset_with_reconcile(
    dataset_name: str,
    version_id: str,
    row_count: int,
    subscribe_scope: str,
    release_tag: str,
) -> dict[str, Any]:
    """链路9：数据集发布——经对账校验后发布。

    输入：数据集名称+版本+行数+订阅范围 → 处理：对账任务执行、发布批次创建 → 产物：发布批次+对账结果。
    对账结论决定数据集能否继续发布。
    """
    # 先执行口径对账
    reconcile_id = f"RECON-{dataset_name}"
    reconcile_result = _run_reconcile(reconcile_id, version_id, row_count)
    if reconcile_result["status"] == "存在差异":
        return {
            "status": "blocked",
            "reason": "对账存在差异，不能发布",
            "reconcile": reconcile_result,
        }

    # 创建发布批次
    release_rows = store.rows("dataset_release")
    new_id = max((int(r.get("id", 0)) for r in release_rows), default=0) + 1
    release = {
        "id": new_id,
        "发布编号": f"REL-{new_id:04d}",
        "数据集名称": dataset_name,
        "绑定版本": version_id,
        "数据行数": str(row_count),
        "对账结论": "已平账",
        "可订阅范围": subscribe_scope,
        "发布标签": release_tag,
        "发布时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "已发布",
        "pending": False,
        "abnormal": False,
    }
    release_rows.append(release)

    return {
        "status": "released",
        "release": release,
        "reconcile": reconcile_result,
    }


def dual_run_and_attribute(
    reconcile_id: str,
    old_caliber_version: str,
    new_caliber_version: str,
    sample_size: int,
) -> dict[str, Any]:
    """链路10：双跑比对与差异归因——新旧口径并行运行期间比对样本输出。

    输入：对账标识+旧口径版本+新口径版本+样本数 → 处理：双跑比对执行、差异逐条归因 → 产物：比对结果+归因条目。
    一致与偏离行数共同构成契约版本切换依据。
    """
    # 创建双跑记录
    dual_rows = store.rows("dual_run")
    dual_id = max((int(r.get("id", 0)) for r in dual_rows), default=0) + 1

    # 模拟新老口径比对
    consistent = int(sample_size * 0.85)  # 85% 一致
    divergent = sample_size - consistent

    dual = {
        "id": dual_id,
        "双跑编号": f"DUAL-{dual_id:04d}",
        "关联对账": reconcile_id,
        "旧口径版本": old_caliber_version,
        "新口径版本": new_caliber_version,
        "比对样本数": str(sample_size),
        "一致行数": str(consistent),
        "偏离行数": str(divergent),
        "双跑结论": "已收敛" if divergent <= sample_size * 0.2 else "偏离超限",
        "status": "比对中",
        "pending": True,
        "abnormal": divergent > 0,
    }
    dual_rows.append(dual)

    # 对有差异的行做归因
    attribution_results = []
    if divergent > 0:
        for i in range(min(divergent, 5)):  # 最多归因5条
            attr_result = _attribute_one_divergence(
                dual_id=dual_id,
                field_name=f"field_{i+1}",
                category="口径差异" if i % 2 == 0 else "数据类型转换",
                row_count=1,
            )
            attribution_results.append(attr_result)

    # 判断是否收敛
    if divergent <= sample_size * 0.2:
        dual["status"] = "已收敛"
        dual["pending"] = False
        dual["abnormal"] = False
    else:
        dual["status"] = "偏离超限"
        dual["abnormal"] = True

    return {
        "dual_run": dual,
        "consistent_rows": consistent,
        "divergent_rows": divergent,
        "attributions": attribution_results,
    }


def _run_reconcile(
    reconcile_id: str,
    version_id: str,
    expected_rows: int,
) -> dict[str, Any]:
    """执行口径对账校验。"""
    rec_rows = store.rows("reconcile_task")
    new_id = max((int(r.get("id", 0)) for r in rec_rows), default=0) + 1

    # 模拟对账：左右两侧来源比对
    actual_left = expected_rows + max(0, expected_rows // 10 - 2)
    actual_right = expected_rows - max(0, expected_rows // 20)
    matched = min(actual_left, actual_right)
    diff = max(actual_left, actual_right) - matched

    reconcile = {
        "id": new_id,
        "对账编号": reconcile_id,
        "对账口径": "全量逐行比对",
        "左侧来源": f"{version_id}-source-a",
        "右侧来源": f"{version_id}-source-b",
        "对账窗口": datetime.now().strftime("%Y-%m"),
        "匹配行数": str(matched),
        "差异行数": str(diff),
        "对账耗时": f"{expected_rows * 0.01:.1f}s",
        "status": "已平账" if diff == 0 else "存在差异",
        "pending": diff > 0,
        "abnormal": diff > 0,
    }
    rec_rows.append(reconcile)
    return reconcile


def _attribute_one_divergence(
    dual_id: int,
    field_name: str,
    category: str,
    row_count: int,
) -> dict[str, Any]:
    attr_rows = store.rows("diff_attrib")
    attr_id = max((int(r.get("id", 0)) for r in attr_rows), default=0) + 1
    attribution = {
        "id": attr_id,
        "归因编号": f"ATTR-{attr_id:04d}",
        "关联比对": str(dual_id),
        "差异字段": field_name,
        "归因类别": category,
        "根因说明": f"新旧口径对字段{field_name}的处理逻辑不同导致{row_count}行差异",
        "影响行数": str(row_count),
        "修正方案": f"统一口径对{field_name}的处理规则为新口径",
        "归因人标识": "system",
        "status": "已修正" if row_count == 0 else "待归因",
        "pending": row_count > 0,
        "abnormal": row_count > 0,
    }
    attr_rows.append(attribution)
    return attribution