"""字段承诺服务单元测试：逐字段校验、违约计数、违约摘要。

覆盖：类型校验、空值校验、取值域校验、违约累积与回写。
"""
from __future__ import annotations

import pytest
from app.services.field_promise import FieldPromiseService
from app.store import store


class TestFieldValidation:
    """字段承诺单字段校验"""

    def setup_method(self):
        self.service = FieldPromiseService()

    def test_validate_field_pass(self):
        """校验通过：字段值符合承诺。"""
        promise_rows = store.rows("field_promise")
        promise_rows.append({
            "id": 501, "承诺编号": "FP-U001", "所属版本": "VER-TEST",
            "字段名称": "user_id", "类型声明": "str", "空值承诺": "不允许为空",
            "取值域": "", "校验方式": "非空校验", "违约次数": "0",
            "status": "待校验", "pending": True, "abnormal": False,
        })
        ok, msg = self.service.validate_field(501, "U12345678")
        assert ok is True
        assert "校验通过" in msg

    def test_validate_null_violation(self):
        """空值违反非空承诺：校验失败并累加违约次数。"""
        promise_rows = store.rows("field_promise")
        promise_rows.append({
            "id": 502, "承诺编号": "FP-U002", "所属版本": "VER-TEST",
            "字段名称": "name", "类型声明": "str", "空值承诺": "不允许为空",
            "取值域": "", "校验方式": "非空校验", "违约次数": "2",
            "status": "待校验", "pending": True, "abnormal": False,
        })
        ok, msg = self.service.validate_field(502, None)
        assert ok is False
        assert "不允许为空" in msg

        promise = store.find("field_promise", 502)
        assert promise["status"] == "违约中"
        assert int(promise["违约次数"]) >= 3

    def test_validate_type_mismatch(self):
        """类型不匹配：校验失败。"""
        promise_rows = store.rows("field_promise")
        promise_rows.append({
            "id": 503, "承诺编号": "FP-U003", "所属版本": "VER-TEST",
            "字段名称": "count", "类型声明": "int", "空值承诺": "不允许为空",
            "取值域": "", "校验方式": "类型校验", "违约次数": "0",
            "status": "待校验", "pending": True, "abnormal": False,
        })
        ok, msg = self.service.validate_field(503, "not_an_integer")
        assert ok is False
        assert "类型" in msg

    def test_validate_value_out_of_domain(self):
        """取值域校验失败。"""
        promise_rows = store.rows("field_promise")
        promise_rows.append({
            "id": 504, "承诺编号": "FP-U004", "所属版本": "VER-TEST",
            "字段名称": "event_type", "类型声明": "str", "空值承诺": "不允许为空",
            "取值域": "click,view,purchase", "校验方式": "枚举校验", "违约次数": "0",
            "status": "待校验", "pending": True, "abnormal": False,
        })
        ok, msg = self.service.validate_field(504, "delete")
        assert ok is False
        assert "不在允许域" in msg

    def test_null_allowed_passes(self):
        """允许为空：空值校验通过。"""
        promise_rows = store.rows("field_promise")
        promise_rows.append({
            "id": 505, "承诺编号": "FP-U005", "所属版本": "VER-TEST",
            "字段名称": "optional_field", "类型声明": "str", "空值承诺": "允许为空",
            "取值域": "", "校验方式": "无", "违约次数": "0",
            "status": "待校验", "pending": True, "abnormal": False,
        })
        ok, msg = self.service.validate_field(505, None)
        assert ok is True

    def test_nonexistent_promise(self):
        """不存在的承诺ID：返回失败。"""
        ok, msg = self.service.validate_field(99999, "val")
        assert ok is False
        assert "不存在" in msg

    def test_get_breach_summary(self):
        """获取违约摘要：正确统计违约率。"""
        promise_rows = store.rows("field_promise")
        # 添加属于 CTR-001 的承诺
        promise_rows.extend([
            {
                "id": 601, "承诺编号": "FP-B001", "所属版本": "VER-CTR-001",
                "字段名称": "f1", "类型声明": "str", "空值承诺": "不允许为空",
                "取值域": "", "校验方式": "校验", "违约次数": "5",
                "status": "违约中", "pending": True, "abnormal": True,
            },
            {
                "id": 602, "承诺编号": "FP-B002", "所属版本": "VER-CTR-001",
                "字段名称": "f2", "类型声明": "int", "空值承诺": "允许为空",
                "取值域": "", "校验方式": "校验", "违约次数": "0",
                "status": "已达标", "pending": False, "abnormal": False,
            },
        ])
        summary = self.service.get_breach_summary("CTR-001")
        assert "breach_rate" in summary
        assert summary["total_promises"] >= 2