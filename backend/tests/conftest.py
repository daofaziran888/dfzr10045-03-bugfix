"""测试共享固件：每次测试前重建干净的 store 实例，隔离种子数据污染。"""
from __future__ import annotations

import importlib
import pytest

import app.seed as _seed
import app.store as _store_mod


@pytest.fixture(autouse=True)
def clean_store():
    """每个测试用例使用独立的 Store 实例，防止跨测试数据污染。"""
    importlib.reload(_seed)
    importlib.reload(_store_mod)
    from app.store import store
    yield store