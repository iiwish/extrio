import json
import re
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_product_contract_defers_scope_and_ux_policy_to_ssot() -> None:
    product_contract = (ROOT / "docs/product-contract.md").read_text()
    ssot = (ROOT / "docs/SSOT.md").read_text()

    assert "| 文档版本 | `v0.46.0` |" in product_contract
    assert "| 文档版本 | `v0.46.0` |" in ssot
    assert "| 对应产品版本 | `v1.0.0`（未发布） |" in product_contract
    assert "| 对应产品版本 | `v1.0.0`（未发布） |" in ssot
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


def test_current_contracts_distinguish_published_rc_from_unpublished_stable() -> None:
    for path in (
        "docs/SSOT.md",
        "docs/product-contract.md",
        "docs/frontend-prototype.md",
        "docs/releases/v0.2-acceptance.md",
    ):
        document = (ROOT / path).read_text()
        assert "`v1.0.0`（未发布）" in document
        assert "`Needs_Review`" in document
        assert "v1.0.0.md" in document
        assert "`v1.0.0-rc.1`（未发布）" not in document

    rc = (ROOT / "docs/releases/v1.0-rc.1.md").read_text()
    assert "https://github.com/iiwish/extrio/releases/tag/v1.0.0-rc.1" in rc
    assert "c2fc06f420c31aaf5bbbea53332ef4af2b48804e" in rc
    for run_id in ("36315751225", "36315751207", "36316015065"):
        assert f"https://github.com/iiwish/extrio/actions/runs/{run_id}" in rc


def test_stable_handoff_covers_all_acceptance_items_and_preserves_release_gates() -> None:
    handoff = (ROOT / "docs/releases/v1.0.0.md").read_text()
    matrix = handoff.split("## 当前验收矩阵", 1)[1].split("## 稳定版剩余门槛", 1)[0]
    assert set(re.findall(r"\bP\d{2}\b", matrix)) == {f"P{number:02}" for number in range(1, 33)}
    assert "状态：`Needs_Review`，`v1.0.0`（未发布）" in handoff
    assert "RC 风险接受不等于稳定版风险接受" in handoff
    assert "72 小时观测" in handoff
    assert "不计为通过" in handoff
    assert "禁止合并、创建 `v1.0.0` tag、运行 release 工作流、发布镜像或生产部署" in handoff


def test_manifest_generator_tracks_unpublished_stable_handoff_without_mutating_input() -> None:
    generator = runpy.run_path(str(ROOT / "scripts/update-docset-manifest.py"))
    current = json.loads((ROOT / "docs/releases/v0.2-docset-manifest.json").read_text())
    original = json.dumps(current, sort_keys=True)
    expected = generator["expected_manifest"](current)

    assert json.dumps(current, sort_keys=True) == original
    assert expected["productVersion"] == "v1.0.0"
    entries = expected["authoritativeFiles"]
    stable_entries = [entry for entry in entries if entry["path"] == "docs/releases/v1.0.0.md"]
    assert len(stable_entries) == 1
    assert len(stable_entries[0]["sha256"]) == 64
    assert generator["expected_manifest"](expected) == expected
