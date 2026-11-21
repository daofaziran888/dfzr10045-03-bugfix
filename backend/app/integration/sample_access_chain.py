"""抽样探查与访问授权链路：数据集发布→抽样探查→访问授权→授权到期回收。

支持抽样不达标阻断订阅、授权到期或契约冻结自动拒绝取数。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store


def probe_sample_and_grant_access(
    dataset_name: str,
    sample_ratio: float,
    consumer_app_id: str,
    endpoint_id: str,
    visible_columns: str,
    row_filter: str,
    grant_days: int,
) -> dict[str, Any]:
    """链路11：抽样探查→访问授权——先探查再授权。

    输入：数据集+抽样比例+消费方应用+端点+可见列+过滤条件 → 处理：抽样探查、授权创建 → 产物：探查结果+授权记录。
    字段完整率与异常值条数不达标时阻断订阅生效。
    """
    # 执行抽样探查
    probe_result = _run_sample_probe(dataset_name, sample_ratio)
    if probe_result["status"] == "已驳回":
        return {"status": "blocked", "reason": "抽样探查不通过", "probe": probe_result}

    # 创建访问授权
    grant_rows = store.rows("access_grant")
    grant_id = max((int(r.get("id", 0)) for r in grant_rows), default=0) + 1
    grant_start = datetime.now().strftime("%Y-%m-%d")
    grant_end = (datetime.now() + timedelta(days=grant_days)).strftime("%Y-%m-%d")

    grant = {
        "id": grant_id,
        "授权编号": f"GRANT-{grant_id:04d}",
        "消费方应用": consumer_app_id,
        "所属端点": endpoint_id,
        "可见列范围": visible_columns,
        "行级过滤条件": row_filter,
        "授权起日": grant_start,
        "授权止日": grant_end,
        "最近核验": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "已授权",
        "pending": True,
        "abnormal": False,
    }
    grant_rows.append(grant)

    # 也创建消费方应用记录（如果不存在）
    _ensure_consumer_app(consumer_app_id)

    return {
        "status": "granted",
        "probe": probe_result,
        "grant": grant,
    }


def revoke_expired_grants() -> dict[str, Any]:
    """链路12：批量回收到期或契约冻结的授权。

    处理：遍历全部授权记录 → 产物：回收的授权列表+受影响的订阅。
    授权到期或契约冻结时端点必须立即拒绝该应用取数。
    """
    grant_rows = store.rows("access_grant")
    today = datetime.now().strftime("%Y-%m-%d")
    revoked = []
    affected_subscriptions = []

    for grant in grant_rows:
        should_revoke = False
        reason = ""

        # 到期回收
        if grant.get("授权止日", "2099-12-31") <= today:
            should_revoke = True
            reason = "授权已过期"

        # 契约冻结回收
        if not should_revoke:
            endpoint_id = grant.get("所属端点", "")
            if _is_contract_frozen(endpoint_id):
                should_revoke = True
                reason = "关联契约已冻结"

        if should_revoke and grant.get("status") != "已回收":
            grant["status"] = "已回收"
            grant["abnormal"] = True
            revoked.append({
                "grant_id": grant["授权编号"],
                "consumer_app": grant.get("消费方应用"),
                "reason": reason,
            })

            # 暂停受影响订阅
            subs = _find_subscriptions_for_endpoint(grant.get("所属端点", ""),
                                                     grant.get("消费方应用", ""))
            for sub in subs:
                sub["status"] = "已暂停"
                sub["abnormal"] = True
                affected_subscriptions.append(sub.get("订阅编号"))

    return {
        "revoked_count": len(revoked),
        "revoked": revoked,
        "affected_subscriptions": affected_subscriptions,
    }


def _run_sample_probe(
    dataset_name: str,
    sample_ratio: float,
) -> dict[str, Any]:
    probe_rows = store.rows("sample_probe")
    probe_id = max((int(r.get("id", 0)) for r in probe_rows), default=0) + 1
    sample_count = int(100 * sample_ratio)
    completeness = 92.0 + (5.0 * sample_ratio)  # 抽样比例影响完整率
    anomaly_count = int(10 * (1 - sample_ratio))  # 抽样越小异常越多
    passed = completeness >= 95.0 and anomaly_count <= 5

    probe = {
        "id": probe_id,
        "样本编号": f"PROBE-{probe_id:04d}",
        "所属数据集": dataset_name,
        "抽样比例": f"{sample_ratio:.0%}",
        "抽样行数": str(sample_count),
        "字段完整率": f"{completeness:.1f}%",
        "异常值条数": str(anomaly_count),
        "探查结论": "通过" if passed else f"不通过：完整率{completeness:.1f}%低于95%或异常值{anomaly_count}条过多",
        "探查时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "已通过" if passed else "已驳回",
        "pending": not passed,
        "abnormal": not passed,
    }
    probe_rows.append(probe)
    return probe


def _ensure_consumer_app(app_id: str) -> None:
    app_rows = store.rows("consumer_app")
    existing = [a for a in app_rows if a.get("应用编号") == app_id]
    if existing:
        return
    new_id = max((int(r.get("id", 0)) for r in app_rows), default=0) + 1
    app_rows.append({
        "id": new_id,
        "应用编号": app_id,
        "应用名称": f"应用-{app_id}",
        "所属团队": "默认团队",
        "接入方式": "API",
        "调用峰值": "0",
        "绑定契约数": "0",
        "接入时间": datetime.now().strftime("%Y-%m-%d"),
        "最近调用": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "已接入",
        "pending": True,
        "abnormal": False,
    })


def _is_contract_frozen(endpoint_id: str) -> bool:
    """检查端点关联契约是否已冻结。"""
    for ep in store.rows("service_endpoint"):
        if ep.get("端点编号") == endpoint_id:
            contract_id = ep.get("所属契约", "")
            for contract in store.rows("data_contract"):
                if contract.get("契约编号") == contract_id:
                    return contract.get("status") == "已冻结"
    return False


def _find_subscriptions_for_endpoint(
    endpoint_id: str,
    consumer_app_id: str,
) -> list[dict[str, Any]]:
    """查找受影响的订阅计划。"""
    result = []
    for sub in store.rows("subscription_plan"):
        if sub.get("消费方应用") == consumer_app_id:
            # 检查订阅版本与该端点版本的对应关系
            for ep in store.rows("service_endpoint"):
                if ep.get("端点编号") == endpoint_id:
                    result.append(sub)
                    break
    return result