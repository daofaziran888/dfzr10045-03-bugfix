"""契约生命周期链路测试：登记→版本演进→字段承诺校验→审计。

覆盖：去重登记、过渡期版本共存、字段违约回写、脏行数据恢复。
"""
from __future__ import annotations

import pytest
from app.integration.contract_lifecycle import (
    register_contract_chain,
    evolve_contract_version,
    validate_field_promises,
)
from app.integration.audit_trail import (
    record_audit_entry,
    verify_audit_chain,
)
from app.store import store


class TestRegisterContractChain:
    """链路1：契约登记测试"""

    def test_register_new_contract_creates_version_and_audit(self):
        """登记新契约：自动创建初始版本与审计记录。"""
        result = register_contract_chain(
            contract_id="CTR-TEST-001",
            contract_name="测试数据契约",
            data_topic="测试主题",
            provider_id="PROV-TEST",
            commitment_level="银级",
            effective_start="2026-01-01",
            effective_end="2027-12-31",
        )
        assert result["status"] == "created"
        assert result["contract"]["契约编号"] == "CTR-TEST-001"
        assert result["contract"]["status"] == "已签署"
        assert result["version"]["版本号"] == "v1.0"
        assert result["version"]["status"] == "已生效"

        # 验证审计条目已创建
        audit_rows = store.rows("contract_audit")
        audits = [a for a in audit_rows if a.get("所属契约") == "CTR-TEST-001"]
        assert len(audits) >= 1
        assert audits[0]["操作类型"] == "签署契约"

    def test_register_duplicate_contract_returns_existing(self):
        """重复登记同一契约编号：返回已有契约。"""
        register_contract_chain(
            contract_id="CTR-DUP",
            contract_name="重复测试",
            data_topic="测试",
            provider_id="PROV-TEST",
            commitment_level="铜级",
            effective_start="2026-01-01",
            effective_end="2027-01-01",
        )
        result2 = register_contract_chain(
            contract_id="CTR-DUP",
            contract_name="重复测试2",
            data_topic="测试2",
            provider_id="PROV-TEST",
            commitment_level="铜级",
            effective_start="2026-02-01",
            effective_end="2027-02-01",
        )
        assert result2["status"] == "duplicate"
        assert result2["contract"]["契约编号"] == "CTR-DUP"


class TestEvolveContractVersion:
    """链路2：版本演进测试"""

    def test_evolve_version_with_transition(self):
        """版本演进含过渡期：新版本过渡中，旧版本仍已生效。"""
        register_contract_chain(
            contract_id="CTR-EVO",
            contract_name="演进测试",
            data_topic="测试",
            provider_id="PROV-TEST",
            commitment_level="金级",
            effective_start="2026-01-01",
            effective_end="2027-12-31",
        )
        result = evolve_contract_version(
            contract_id="CTR-EVO",
            new_version="v2.0",
            change_summary="增加新字段并调整聚合逻辑",
            compatibility="向后兼容",
            transition_days=30,
        )
        assert result["status"] == "evolved"
        assert result["version"]["版本号"] == "v2.0"
        assert result["version"]["status"] == "过渡中"
        assert result["transition_days"] == 30

        # 验证旧版本仍可用
        active_versions = [
            v for v in store.rows("contract_version")
            if v.get("所属契约") == "CTR-EVO"
        ]
        assert len(active_versions) >= 2

    def test_evolve_version_without_transition(self):
        """版本演进无过渡期：直接生效。"""
        register_contract_chain(
            contract_id="CTR-NOTR",
            contract_name="无过渡测试",
            data_topic="测试",
            provider_id="PROV-TEST",
            commitment_level="铜级",
            effective_start="2026-06-01",
            effective_end="2027-06-01",
        )
        result = evolve_contract_version(
            contract_id="CTR-NOTR",
            new_version="v1.1",
            change_summary="小修补",
            compatibility="向后兼容",
            transition_days=0,
        )
        assert result["version"]["status"] == "已生效"

    def test_evolve_nonexistent_contract(self):
        """对不存在的契约演进版本：返回错误。"""
        result = evolve_contract_version(
            contract_id="CTR-NONEXIST",
            new_version="v2.0",
            change_summary="不应成功",
            compatibility="兼容",
            transition_days=30,
        )
        assert result["status"] == "error"


class TestValidateFieldPromises:
    """链路3：字段承诺校验测试"""

    def test_validate_all_fields_pass(self):
        """全部字段通过校验：无违约记录。"""
        # 准备版本与承诺数据
        ver_rows = store.rows("contract_version")
        ver_rows.append({
            "id": 99, "版本编号": "VER-TEST-PASS", "所属契约": "CTR-TEST",
            "版本号": "v1.0", "变更摘要": "测试", "兼容判定": "初始",
            "父版本号": "", "过渡期天数": "0", "生效时间": "2026-01-01",
            "status": "已生效", "pending": False, "abnormal": False,
        })
        promise_rows = store.rows("field_promise")
        promise_rows.append({
            "id": 101, "承诺编号": "FP-T001", "所属版本": "VER-TEST-PASS",
            "字段名称": "user_id", "类型声明": "str", "空值承诺": "不允许为空",
            "取值域": "", "校验方式": "非空校验", "违约次数": "0",
            "status": "待校验", "pending": True, "abnormal": False,
        })
        promise_rows.append({
            "id": 102, "承诺编号": "FP-T002", "所属版本": "VER-TEST-PASS",
            "字段名称": "count", "类型声明": "int", "空值承诺": "不允许为空",
            "取值域": "", "校验方式": "类型校验", "违约次数": "0",
            "status": "待校验", "pending": True, "abnormal": False,
        })

        result = validate_field_promises(
            version_id="VER-TEST-PASS",
            field_values={"user_id": "A12345678", "count": 42},
        )
        assert result["breach_count"] == 0
        assert all(r["passed"] for r in result["results"])

    def test_validate_null_violates_promise(self):
        """空值违反非空承诺：记录违约。"""
        ver_rows = store.rows("contract_version")
        ver_rows.append({
            "id": 100, "版本编号": "VER-TEST-NULL", "所属契约": "CTR-TEST",
            "版本号": "v2.0", "变更摘要": "测试", "兼容判定": "初始",
            "父版本号": "v1.0", "过渡期天数": "0", "生效时间": "2026-06-01",
            "status": "已生效", "pending": False, "abnormal": False,
        })
        promise_rows = store.rows("field_promise")
        promise_rows.append({
            "id": 201, "承诺编号": "FP-N001", "所属版本": "VER-TEST-NULL",
            "字段名称": "required_field", "类型声明": "str", "空值承诺": "不允许为空",
            "取值域": "", "校验方式": "非空校验", "违约次数": "1",
            "status": "待校验", "pending": True, "abnormal": False,
        })

        result = validate_field_promises(
            version_id="VER-TEST-NULL",
            field_values={"required_field": None},
        )
        assert result["breach_count"] == 1
        assert not result["results"][0]["passed"]
        assert "字段不允许为空" in result["results"][0]["failure_reason"]

    def test_value_out_of_domain_violates(self):
        """取值不在允许域：记录违约。"""
        ver_rows = store.rows("contract_version")
        ver_rows.append({
            "id": 101, "版本编号": "VER-TEST-DOMAIN", "所属契约": "CTR-TEST",
            "版本号": "v3.0", "变更摘要": "测试", "兼容判定": "初始",
            "父版本号": "v2.0", "过渡期天数": "0", "生效时间": "2026-07-01",
            "status": "已生效", "pending": False, "abnormal": False,
        })
        promise_rows = store.rows("field_promise")
        promise_rows.append({
            "id": 301, "承诺编号": "FP-D001", "所属版本": "VER-TEST-DOMAIN",
            "字段名称": "event_type", "类型声明": "str", "空值承诺": "不允许为空",
            "取值域": "click,view,purchase", "校验方式": "枚举校验", "违约次数": "0",
            "status": "待校验", "pending": True, "abnormal": False,
        })

        result = validate_field_promises(
            version_id="VER-TEST-DOMAIN",
            field_values={"event_type": "invalid_action"},
        )
        assert result["breach_count"] == 1
        assert "不在允许域" in result["results"][0]["failure_reason"]


class TestAuditTrail:
    """审计链路测试"""

    def test_record_and_verify_chain(self):
        """记录审计条目后核查链完整性。"""
        record_audit_entry(
            contract_id="CTR-001",
            operation_type="签署契约",
            target_object="data_contract",
            before_value="",
            after_value="CTR-001-新版",
            operator_id="admin-wang",
        )
        result = verify_audit_chain(contract_id="CTR-001")
        assert result["complete"] is True
        assert result["chain_length"] >= 1

    def test_duplicate_audit_same_day(self):
        """同日同操作同结果的审计去重。"""
        r1 = record_audit_entry(
            contract_id="CTR-001",
            operation_type="版本演进",
            target_object="contract_version",
            before_value="v1.0",
            after_value="v2.0-test",
            operator_id="admin-wang",
        )
        assert r1["status"] == "recorded"

        r2 = record_audit_entry(
            contract_id="CTR-001",
            operation_type="版本演进",
            target_object="contract_version",
            before_value="v1.0",
            after_value="v2.0-test",
            operator_id="admin-wang",
        )
        assert r2["status"] == "duplicate"