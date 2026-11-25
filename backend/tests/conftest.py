"""测试共享固件：每次测试前重建干净的 store 实例，隔离种子数据污染。"""
from __future__ import annotations

import importlib
import sys

import pytest

import app.seed as _seed
import app.store as _store_mod


def _sync_store_references(fresh_store) -> None:
    """把已加载的 app 子模块里的 store 引用同步到重建后的实例。

    各领域服务/链路在模块级使用 ``from app.store import store``，
    reload app.store 后这些引用仍指向旧实例；这里统一重指，保证一次
    测试内所有模块读写的是同一份干净 store。
    """
    for module_name, module in list(sys.modules.items()):
        if not (module_name.startswith("app.") or module_name.startswith("tests.")):
            continue
        if module is None:
            continue
        if "store" in module.__dict__ and module.__dict__["store"] is not fresh_store:
            module.__dict__["store"] = fresh_store


@pytest.fixture(autouse=True)
def clean_store():
    """每个测试用例使用独立的 Store 实例，防止跨测试数据污染。

    reload 后必须重新导入才能拿到本次新建的 store，并同步所有
    模块级引用。
    """
    importlib.reload(_seed)
    importlib.reload(_store_mod)
    from app.store import store as fresh_store
    _sync_store_references(fresh_store)
    yield fresh_store
