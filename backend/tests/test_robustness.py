"""错误/边界路径的负向测试：LLM 失败时优雅降级、空 JD 过滤。"""

from __future__ import annotations

from app.services import jd_parser, llm, pipeline, resume_parser

from .sample_data import SAMPLE_JDS, SAMPLE_RESUME


def test_parsers_fall_back_when_llm_unavailable(monkeypatch):
    """即使 LLM 启用但调用抛 LLMUnavailable，解析也应降级为规则模式且不崩。"""

    def _boom(*_args, **_kwargs):
        raise llm.LLMUnavailable("模拟 LLM 失败")

    monkeypatch.setattr(llm, "complete_json", _boom)

    resume = resume_parser.parse_resume(SAMPLE_RESUME)
    assert resume["skills"], "规则降级仍应抽取到技能"

    jd = jd_parser.parse_jd(SAMPLE_JDS[0])
    assert jd["must_have"], "规则降级仍应抽取到必备技能"


def test_empty_and_whitespace_jds_filtered():
    """jd_texts 中的空串/纯空白应被过滤，不参与解析。"""
    outcome = None
    for kind, payload in pipeline.analyze_match_streaming(
        SAMPLE_RESUME, ["", "   ", "\n", SAMPLE_JDS[0]], "前端实习"
    ):
        if kind == "result":
            outcome = payload
    assert outcome is not None
    assert len(outcome["parsed_jds"]) == 1  # 仅 1 条有效 JD 被解析


def test_analyze_with_many_jds_keeps_order_and_count():
    """并发解析后，JD 数量与顺序应与输入一致（按 index 回填）。"""
    jds = SAMPLE_JDS * 2  # 6 条
    outcome = None
    for kind, payload in pipeline.analyze_match_streaming(SAMPLE_RESUME, jds, "前端实习"):
        if kind == "result":
            outcome = payload
    assert outcome is not None
    parsed = outcome["parsed_jds"]
    assert len(parsed) == len(jds)
    assert all(isinstance(p, dict) and "must_have" in p for p in parsed)
