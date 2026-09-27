from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_product_contract_defers_scope_and_ux_policy_to_ssot() -> None:
    product_contract = (ROOT / "docs/product-contract.md").read_text()
    ssot = (ROOT / "docs/SSOT.md").read_text()

    assert "| 文档版本 | `v0.46.0` |" in product_contract
    assert "| 文档版本 | `v0.46.0` |" in ssot
    assert "| 对应产品版本 | `v1.0.0-rc.1`（未发布） |" in product_contract
    assert "| 对应产品版本 | `v1.0.0-rc.1`（未发布） |" in ssot
    assert "| 产品需求 | [`product-contract.md`](./product-contract.md) | `v0.46.0` |" in ssot
    assert "v0.6" not in product_contract

    ssot_owned_sections = (
        "## 1.0 交付范围",
        "## 运营状态与处理入口",
        "## 体验设计评审",
        "## 自托管可靠性",
        "## 自适应网页证据",
        "## 核心操作上下文",
        "## 来源生命周期与所属需求",
        "## 数据查询与导出",
        "## 字段版本与受控迁移",
        "## 单前端实现边界",
        "## 3. 产品定义",
        "### 概览看板时间范围",
    )
    for heading in ssot_owned_sections:
        assert heading in ssot
        assert heading not in product_contract
