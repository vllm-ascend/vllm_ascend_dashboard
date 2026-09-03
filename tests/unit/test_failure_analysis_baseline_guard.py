from pathlib import Path


def test_auto_bug_fixer_requires_evidence_before_changing_baseline():
    skill_path = (
        Path(__file__).resolve().parents[2]
        / "backend"
        / ".agents"
        / "skills"
        / "auto-bug-fixer"
        / "SKILL.md"
    )

    skill = skill_path.read_text(encoding="utf-8")

    assert "不得建议放宽阈值、降低精度要求或修改基线" in skill
    assert "同配置复测、运行环境/硬件状态排除、源码或依赖变更因果分析" in skill
