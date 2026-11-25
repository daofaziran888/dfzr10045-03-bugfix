"""发布撤回—订阅消费交接链路：发布撤回 → 订阅状态流转 → 按实际批次取数。

链路把发布批次与订阅取数串成一条可核验的状态流：

1. 撤回发布批次时，只处理当前真正依赖该批次的生效订阅——能改绑同版本
   独立有效发布的保持生效，其余暂停并写明等候原因；依赖其他发布批次
   （如同版本的其他数据集）的订阅不受影响；
2. 撤回重试幂等，不覆盖已凭独立有效发布恢复的订阅；
3. 新取数请求按订阅实际绑定的发布批次交付，已撤回批次无法再供数；
4. 每条取数记录都关联本次实际使用的发布批次，可按发布批次反查取数记录。
"""
from __future__ import annotations

from typing import Any

from app.services.dataset_release import DatasetReleaseService
from app.services.subscription_plan import SubscriptionPlanService


def withdraw_release(release_id: int) -> dict[str, Any]:
    """链路入口：撤回一个发布批次并完成订阅消费交接。"""
    service = DatasetReleaseService()
    return service.withdraw(int(release_id))


def restore_subscription_with_release(
    subscription_id: int,
    replacement_release_id: int,
) -> dict[str, Any]:
    """凭独立有效发布恢复因撤回暂停的订阅（消费交接的恢复侧）。"""
    release_service = DatasetReleaseService()
    replacement = release_service.get_release(int(replacement_release_id))
    if replacement is None:
        return {"status": "error", "message": "替代发布不存在"}
    sub_service = SubscriptionPlanService()
    return sub_service.restore_with_replacement(int(subscription_id), replacement)


def submit_fetch_request(
    subscription_id: int,
    requested_rows: int,
) -> dict[str, Any]:
    """链路入口：订阅发起一次取数，按实际发布批次交付并落取数记录。"""
    service = SubscriptionPlanService()
    return service.request_fetch(int(subscription_id), int(requested_rows))


def query_fetch_records_by_release(release_id: int) -> list[dict[str, Any]]:
    """按实际发布批次查询本次/历次取数记录。"""
    service = SubscriptionPlanService()
    return service.list_fetch_records(release_id=int(release_id))


def query_fetch_records_by_subscription(subscription_id: int) -> list[dict[str, Any]]:
    """按订阅查询其全部取数记录（每条均带实际发布批次）。"""
    service = SubscriptionPlanService()
    return service.list_fetch_records(subscription_id=int(subscription_id))
