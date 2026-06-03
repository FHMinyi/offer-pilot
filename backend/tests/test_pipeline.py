"""核心分析 pipeline 的离线（规则模式）测试。"""

from __future__ import annotations

from app.services import llm, pipeline, skills

from .sample_data import SAMPLE_JDS, SAMPLE_RESUME


def _keys(items):
    return {i["key"] for i in items}


def test_engine_is_rule_without_keys():
    # 未配置 API Key 时应走规则模式
    assert llm.engine_name() == "rule"
    assert llm.llm_enabled() is False


def test_skill_normalization_aliases():
    # 别名应归一到同一规范节点
    assert "typescript" in skills.match_skills("精通 TS 和类型体操")
    assert "javascript" in skills.match_skills("熟悉 ES6 与事件循环")
    # 边界匹配：不应把 good 里的 go 误判成 Golang
    assert "go" not in skills.match_skills("good morning")


def test_full_pipeline_rule_mode():
    out = pipeline.run_analysis(SAMPLE_RESUME, SAMPLE_JDS, target_role="前端实习", weeks=4)

    assert out["engine"] == "rule"
    result = out["result"]

    # 匹配度在合理区间
    assert 0 <= result["match_score"] <= 100

    gap = result["skill_gap"]
    must_keys = _keys(gap["must_have_gaps"])
    nice_keys = _keys(gap["nice_to_have_gaps"])
    possessed_keys = _keys(gap["possessed"])

    # 必备缺口：简历缺 TypeScript / React
    assert "typescript" in must_keys
    assert "react" in must_keys

    # 已具备：HTML / CSS / JavaScript / Vue
    assert {"html", "css", "javascript", "vue"}.issubset(possessed_keys)

    # 加分缺口：Docker / Node.js
    assert "docker" in nice_keys
    assert "nodejs" in nice_keys

    # 至少有一个“薄弱”判定（git 仅在技能罗列中出现，缺项目支撑）
    assert any(g["gap_level"] == "薄弱" for g in gap["must_have_gaps"])

    # 每个缺口都带来源说明与原因（可解释性）
    for g in gap["must_have_gaps"]:
        assert g["required_by"], "缺口必须标明来自哪些 JD"
        assert g["reason"]
        assert g["priority"] in {"高", "中", "低"}
        assert g["gap_level"] in {"缺失", "薄弱"}


def test_roadmap_structure():
    out = pipeline.run_analysis(SAMPLE_RESUME, SAMPLE_JDS, target_role="前端实习", weeks=4)
    roadmap = out["result"]["roadmap"]
    assert len(roadmap) == 4
    for i, week in enumerate(roadmap, start=1):
        assert week["week"] == i
        assert isinstance(week["tasks"], list) and week["tasks"]
        assert isinstance(week["deliverables"], list) and week["deliverables"]
        assert isinstance(week["interview_focus"], list)
        assert week["estimated_hours"] > 0


def test_suggestions_and_profile():
    out = pipeline.run_analysis(SAMPLE_RESUME, SAMPLE_JDS, target_role="前端实习", weeks=6)
    result = out["result"]

    assert result["resume_suggestions"], "应给出简历优化建议"
    for s in result["resume_suggestions"]:
        assert s["title"] and s["detail"]

    profile = result["job_profile"]
    assert len(profile["titles"]) == 3
    assert profile["tech_stack"]
    assert len(profile["jobs"]) == 3

    # 周数可调
    assert len(result["roadmap"]) == 6


def test_empty_jobs_does_not_crash():
    # 没有有效 JD 时也不应崩溃（路由层会拦截，但 pipeline 需健壮）
    out = pipeline.run_analysis(SAMPLE_RESUME, [], target_role="前端实习", weeks=2)
    assert out["result"]["match_score"] >= 0
    assert len(out["result"]["roadmap"]) == 2
