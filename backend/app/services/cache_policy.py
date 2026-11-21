"""缓存策略领域服务：维护端点结果缓存的键构成、存活时间与失效触发条件。

缓存键由筛选字段构成，契约版本切换时旧缓存必须整体失效，
命中率与回源比例按查询批次持续累计，用于评估缓存策略是否调整。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class CachePolicyService(BaseModuleService):
    MODULE = "cache_policy"
    ENTITY = "缓存策略"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["策略编号", "所属端点", "缓存键构成", "存活秒数", "失效触发", "命中率", "回源比例", "最近调整"]
    REQUIRED_FIELDS = ["策略编号", "所属端点"]
    STATUS_ORDER = ["草稿", "已生效", "失效中", "已停用"]
    ACTION_RULES = {"启效策略": "已生效", "强制失效": "失效中", "停用策略": "已停用"}
    NEGATIVE_ACTIONS = []

    def build_cache_key(self, endpoint_id: str, key_fields: dict[str, str]) -> str:
        """按策略声明的缓存键构成生成缓存键，键含端点与筛选字段摘要。"""
        policy = self.get_policy_for_endpoint(endpoint_id)
        composition = str(policy.get("缓存键构成", "")) if policy else ""
        declared = [c.strip() for c in composition.split("+") if c.strip()]
        parts = [str(key_fields.get(f, "")) for f in declared] if declared else [
            f"{k}={v}" for k, v in sorted(key_fields.items())
        ]
        payload = endpoint_id + "|" + "|".join(parts)
        return hashlib.md5(payload.encode("utf-8")).hexdigest()

    def lookup(self, cache: dict[str, Any], key: str) -> dict[str, Any] | None:
        """在缓存条目集中按键查找未过期的结果集数据集。"""
        entry = cache.get(key)
        if entry is None:
            return None
        ttl = int(entry.get("expires_at", "0"))
        if ttl and ttl < int(datetime.now().timestamp()):
            cache.pop(key, None)
            return None
        return entry.get("payload")

    def record_access(
        self,
        endpoint_id: str,
        cache: dict[str, Any],
        key: str,
        payload: Any,
        hit: bool,
    ) -> dict[str, Any]:
        """记录一次缓存访问：命中累加命中率，未命中写入缓存并累加回源。

        按存活秒数写入缓存条目过期水位，同时更新策略的命中率与
        回源比例统计，供缓存策略调整决策消费。
        """
        policy = self.get_policy_for_endpoint(endpoint_id)
        if policy is None:
            return {"cached": False, "hit": hit}
        ttl = int(policy.get("存活秒数", "3600") or "3600")
        if not hit:
            cache[key] = {
                "payload": payload,
                "endpoint_id": endpoint_id,
                "expires_at": int(datetime.now().timestamp()) + ttl,
            }
        hit_rate = int(policy.get("命中率", "0") or "0")
        total = hit_rate + int(policy.get("回源比例", "0") or "0") + 1
        policy["命中率"] = str(hit_rate + (1 if hit else 0))
        policy["回源比例"] = str(total - hit_rate - (1 if hit else 0))
        policy["最近调整"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {"cached": True, "hit": hit, "ttl": ttl}

    def invalidate_on_version_switch(self, endpoint_id: str, cache: dict[str, Any]) -> int:
        """契约版本切换时整体失效该端点旧缓存，返回清除的条目数。

        版本切换后旧缓存数据集必须全部失效，策略进入失效中状态，
        避免消费方读到切换前版本的过期明细。
        """
        cleared = 0
        policy = self.get_policy_for_endpoint(endpoint_id)
        if policy is not None:
            policy["status"] = "失效中"
            policy["abnormal"] = True
        for key in list(cache.keys()):
            entry = cache.get(key) or {}
            if entry.get("endpoint_id") == endpoint_id:
                cache.pop(key, None)
                cleared += 1
        return cleared

    def get_policy_for_endpoint(self, endpoint_id: str) -> dict[str, Any] | None:
        """查询端点当前生效的缓存策略数据集。"""
        for r in store.rows(self.MODULE):
            if r.get("所属端点") == endpoint_id and r.get("status") == "已生效":
                return r
        return None


def serve_with_cache(endpoint_id: str, key_fields: dict, cache: dict, loader) -> dict:
    """模块级入口：按缓存键构成命中或回源加载结果数据集并更新命中率指标。"""
    service = CachePolicyService()
    key = service.build_cache_key(endpoint_id, key_fields)
    cached = service.lookup(cache, key)
    if cached is not None:
        service.record_access(endpoint_id, cache, key, cached, hit=True)
        return {"hit": True, "payload": cached}
    payload = loader()
    service.record_access(endpoint_id, cache, key, payload, hit=False)
    return {"hit": False, "payload": payload}
