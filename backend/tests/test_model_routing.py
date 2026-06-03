"""按任务分流 LLM 模型的逻辑测试（不发真实请求）。"""

from __future__ import annotations

from app.services import jd_parser, llm, resume_parser


def test_model_for_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.settings, "llm_model", "default-model")
    monkeypatch.setattr(llm.settings, "llm_model_resume", "")
    monkeypatch.setattr(llm.settings, "llm_model_jd", "")
    assert llm.model_for("resume") == "default-model"
    assert llm.model_for("jd") == "default-model"
    assert llm.model_for("chat") == "default-model"


def test_model_for_per_task_override(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.settings, "llm_model", "deepseek-v4-pro")
    monkeypatch.setattr(llm.settings, "llm_model_resume", "deepseek-v4-flash")
    monkeypatch.setattr(llm.settings, "llm_model_jd", "deepseek-v4-flash")
    assert llm.model_for("resume") == "deepseek-v4-flash"
    assert llm.model_for("jd") == "deepseek-v4-flash"
    # 对话/聚合用默认
    assert llm.model_for("chat") == "deepseek-v4-pro"
    assert llm.model_for("anything-else") == "deepseek-v4-pro"


def test_parsers_pass_role_specific_model(monkeypatch):
    """验证 resume/jd parser 把各自角色的模型传给 complete_json。"""
    captured = {}

    def fake_complete_json(system, user, model=None):
        captured["model"] = model
        # 抛 LLMUnavailable 触发规则降级，避免真实请求；这里只关心传入的 model
        raise llm.LLMUnavailable("stub")

    monkeypatch.setattr(llm.settings, "llm_model", "pro")
    monkeypatch.setattr(llm.settings, "llm_model_resume", "flash-resume")
    monkeypatch.setattr(llm.settings, "llm_model_jd", "flash-jd")
    monkeypatch.setattr(llm, "complete_json", fake_complete_json)

    # 调公开入口：内部捕获 LLMUnavailable 降级为规则解析，但传给 complete_json 的 model 已被捕获
    resume_parser.parse_resume("张三 简历 熟悉 Python")
    assert captured["model"] == "flash-resume"

    jd_parser.parse_jd("前端实习 任职要求 熟悉 Vue")
    assert captured["model"] == "flash-jd"
