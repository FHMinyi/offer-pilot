"""里程碑二 · E3 人设引擎（单人设 + 语气滑块，B5）测试。

纯函数验证：语气强度映射、夹取、注入系统提示、人设注册表回退。
"""

from __future__ import annotations

from app.services.agent import PERSONAS, _system_prompt, _tone_directive


def test_tone_directive_varies_by_intensity():
    gentle = _tone_directive(0)
    strict = _tone_directive(100)
    assert gentle != strict
    assert "温柔" in gentle
    assert "严格" in strict
    # 底线：无论松紧都不报 Offer 概率（B7）
    assert "Offer 概率" in gentle and "Offer 概率" in strict


def test_tone_directive_clamps_out_of_range():
    assert "0/100" in _tone_directive(-50)
    assert "100/100" in _tone_directive(999)


def test_tone_moved_out_of_system_prompt():
    # 语气改为消息尾注，不再进系统提示（缓存评审：语气置尾）——拨滑块不冲历史缓存
    assert "语气强度" not in _system_prompt({"tone": 0})
    assert "语气强度" not in _system_prompt({"tone": 100})
    # 语气文案仍由纯函数产出（尾注内容由 run_turn 用它拼装）
    assert "语气强度 0/100" in _tone_directive(0)
    assert "语气强度 100/100" in _tone_directive(100)
    assert "语气强度 50/100" in _tone_directive(50)


def test_persona_registry_default_and_fallback():
    assert "default" in PERSONAS
    assert PERSONAS["default"] in _system_prompt({"persona": "default"})
    # 未知 persona 回退 default，不报错
    assert PERSONAS["default"] in _system_prompt({"persona": "nope"})
