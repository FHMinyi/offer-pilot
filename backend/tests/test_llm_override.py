"""前端自定义大语言模型（BYO LLM）契约的稳健离线测试。

覆盖（计划「## 验证」第 2、4 条）：
1. `use_llm_override` 的分档覆盖与退出恢复（直接调 services.llm，monkeypatch settings 分档）。
2. `complete_json(..., effort="high")` 对 openai 注入 `reasoning_effort`，且服务不认时去掉重试兜底。
3. `POST /api/llm/models` 在 list 成功/异常下分别返回 ok:true/false，异常不抛 5xx。
4. pipeline 线程传播：`_parse_inputs_streaming` 在 `use_llm_override` 内，子线程取到覆盖模型（证明 copy_context 生效）。

全程无需真实 API Key / 网络：用 monkeypatch 把 `_build_client` 换成返回假客户端的桩，
或把 parser 换成「读取当前 model_for」的假函数。
"""

from __future__ import annotations

from app.routers import chat as chat_router
from app.routers import llm as llm_router
from app.services import jd_parser, llm, pipeline, resume_parser


def _parse_sse(text: str) -> list[tuple[str, str | None]]:
    """把 SSE 文本拆为 [(event, data_text), ...]。"""
    events: list[tuple[str, str | None]] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        ev: str | None = None
        data: str | None = None
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
        if ev is not None:
            events.append((ev, data))
    return events


# --------------------------------------------------------------- 1. 分档覆盖

def _seed_server_models(monkeypatch):
    """把服务端 .env 分档置为已知值：provider=openai，默认 pro，简历/JD 均 flash。"""
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.settings, "llm_model", "pro")
    monkeypatch.setattr(llm.settings, "llm_model_resume", "flash")
    monkeypatch.setattr(llm.settings, "llm_model_jd", "flash")


def test_override_default_box_applies_to_all_unset_tiers(monkeypatch):
    """只填默认框：默认/简历/JD 三档都回退到该默认框（简历/JD 前端留空）。"""
    _seed_server_models(monkeypatch)
    with llm.use_llm_override({"provider": "openai", "model": "X"}):
        assert llm.model_for("chat") == "X"
        # 简历框留空 → 回退前端默认框 X（而非服务端 flash）
        assert llm.model_for("resume") == "X"
        assert llm.model_for("jd") == "X"


def test_override_per_tier_box(monkeypatch):
    """简历单独填 Y：简历用 Y，JD 留空回退默认框 X。"""
    _seed_server_models(monkeypatch)
    with llm.use_llm_override({"model": "X", "model_resume": "Y"}):
        assert llm.model_for("resume") == "Y"
        assert llm.model_for("jd") == "X"
        assert llm.model_for("chat") == "X"


def test_override_resets_on_exit(monkeypatch):
    """退出 with 后恢复服务端分档（pro / flash / flash）。"""
    _seed_server_models(monkeypatch)
    with llm.use_llm_override({"provider": "openai", "model": "X"}):
        assert llm.model_for("resume") == "X"
    # 退出后恢复服务端分档
    assert llm.model_for("resume") == "flash"
    assert llm.model_for("jd") == "flash"
    assert llm.model_for("chat") == "pro"


def test_empty_override_falls_back_to_server(monkeypatch):
    """空 override（dict 全空）归一为 None，不影响服务端分档。"""
    _seed_server_models(monkeypatch)
    with llm.use_llm_override(None):
        assert llm.model_for("resume") == "flash"
        assert llm.model_for("chat") == "pro"


# --------------------------------------------- 2. complete_json effort 注入 + 兜底

class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResp:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    """记录每次 create 的 kwargs；可配置首调抛错以验证去 reasoning_effort 重试。"""

    def __init__(self, calls: list, fail_first_with_effort: bool):
        self._calls = calls
        self._fail_first_with_effort = fail_first_with_effort

    def create(self, **kwargs):
        self._calls.append(kwargs)
        if self._fail_first_with_effort and "reasoning_effort" in kwargs:
            # 模拟不认 reasoning_effort 的兼容服务首调报错
            raise RuntimeError("unknown parameter: reasoning_effort")
        return _FakeResp('{"ok": true}')


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeOpenAIClient:
    def __init__(self, calls: list, fail_first_with_effort: bool = False):
        self.chat = _FakeChat(_FakeCompletions(calls, fail_first_with_effort))


def _patch_build_client(monkeypatch, calls: list, fail_first_with_effort: bool = False):
    """把 llm._build_client 换成返回假 openai 客户端的桩（捕获 create kwargs）。"""

    def fake_build_client(factory, **kwargs):  # noqa: ARG001 签名对齐，参数无关
        return _FakeOpenAIClient(calls, fail_first_with_effort)

    monkeypatch.setattr(llm, "_build_client", fake_build_client)


def test_complete_json_injects_reasoning_effort(monkeypatch):
    """effort="high" → openai 路径 kwargs 含 reasoning_effort=high。"""
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    calls: list = []
    _patch_build_client(monkeypatch, calls)
    # override 带 api_key → llm_enabled() 为真，且走 openai
    with llm.use_llm_override({"provider": "openai", "api_key": "k", "model": "m"}):
        out = llm.complete_json("sys", "usr", effort="high")
    assert out == {"ok": True}
    assert len(calls) == 1
    assert calls[0]["reasoning_effort"] == "high"
    assert calls[0]["model"] == "m"


def test_complete_json_no_effort_omits_reasoning(monkeypatch):
    """effort=None/off → 不注入 reasoning_effort。"""
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    calls: list = []
    _patch_build_client(monkeypatch, calls)
    with llm.use_llm_override({"provider": "openai", "api_key": "k", "model": "m"}):
        llm.complete_json("sys", "usr")  # effort 默认 None
        llm.complete_json("sys", "usr", effort="off")
    assert all("reasoning_effort" not in c for c in calls)


def test_complete_json_falls_back_when_effort_unsupported(monkeypatch):
    """首调带 reasoning_effort 抛错 → 去掉后第二次成功（兜底重试）。"""
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    calls: list = []
    _patch_build_client(monkeypatch, calls, fail_first_with_effort=True)
    with llm.use_llm_override({"provider": "openai", "api_key": "k", "model": "m"}):
        out = llm.complete_json("sys", "usr", effort="high")
    assert out == {"ok": True}
    # 两次调用：首调带 effort（失败）→ 去掉 effort 重试成功
    assert len(calls) == 2
    assert "reasoning_effort" in calls[0]
    assert "reasoning_effort" not in calls[1]


# ------------------------------------------------- 3. POST /api/llm/models

class _IdObj:
    def __init__(self, id_: str):
        self.id = id_


class _ListModelsOK:
    def list(self):
        return [_IdObj("model-a"), _IdObj("model-b")]


class _ListModelsBoom:
    def list(self):
        raise RuntimeError("401 unauthorized")


class _FakeModelsClient:
    def __init__(self, models):
        self.models = models


def test_list_models_success(client, monkeypatch):
    """list 成功 → ok:true + models（路由复用 llm._build_client，patch 其在 router 模块的引用）。"""

    def fake_build_client(factory, **kwargs):  # noqa: ARG001
        return _FakeModelsClient(_ListModelsOK())

    monkeypatch.setattr(llm_router, "_build_client", fake_build_client)
    r = client.post(
        "/api/llm/models",
        json={"provider": "openai", "base_url": "http://x", "api_key": "k"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["models"] == ["model-a", "model-b"]


def test_list_models_error_does_not_5xx(client, monkeypatch):
    """list 抛异常 → HTTP 200 且 ok:false、error 非空、不抛 5xx。"""

    def fake_build_client(factory, **kwargs):  # noqa: ARG001
        return _FakeModelsClient(_ListModelsBoom())

    monkeypatch.setattr(llm_router, "_build_client", fake_build_client)
    r = client.post(
        "/api/llm/models",
        json={"provider": "openai", "base_url": "http://x", "api_key": "k"},
    )
    assert r.status_code == 200  # 关键：不抛 5xx
    body = r.json()
    assert body["ok"] is False
    assert body["error"]  # 非空错误信息
    assert body["models"] == []


# ----------------------------------------- 4. pipeline 线程传播（copy_context）

def test_pipeline_propagates_override_to_parse_threads(monkeypatch):
    """在 use_llm_override 内跑 _parse_inputs_streaming，断言子线程取到覆盖模型 ZZZ。

    把 parser 换成「调用 llm.model_for(...) 并把结果塞进返回 dict」的假函数；
    这些假函数在 ThreadPoolExecutor 的工作线程里执行，若 copy_context 传播生效，
    子线程内 model_for 应取到覆盖值 ZZZ（否则会回退服务端默认）。
    """
    _seed_server_models(monkeypatch)

    def fake_parse_resume(_text):
        # 在工作线程内读取当前生效模型
        return {"model_seen": llm.model_for("resume"), "skills": []}

    def fake_parse_jd(_text):
        return {
            "model_seen": llm.model_for("jd"),
            "title": "岗位",
            "must_have": [],
            "nice_to_have": [],
        }

    monkeypatch.setattr(resume_parser, "parse_resume", fake_parse_resume)
    monkeypatch.setattr(jd_parser, "parse_jd", fake_parse_jd)

    parsed = None
    with llm.use_llm_override({"provider": "openai", "model": "ZZZ"}):
        # _parse_inputs_streaming 是生成器，需迭代到 ("parsed", ...) 取结果
        for kind, payload in pipeline._parse_inputs_streaming("简历文本", ["JD 文本"]):
            if kind == "parsed":
                parsed = payload

    assert parsed is not None
    resume, parsed_jds = parsed
    # 子线程里 model_for 取到的是覆盖值 ZZZ → 证明 copy_context 传播生效
    assert resume["model_seen"] == "ZZZ"
    assert parsed_jds[0]["model_seen"] == "ZZZ"


# --------------------------- 5. 流式 chat 路由：ctx.run 覆盖跨 yield 传播（回归）

def test_chat_stream_applies_override_across_yields(client, monkeypatch):
    """POST /api/chat/stream 带非空 llm_override：覆盖在整条流式生成器里全程可见，
    且结尾为 done 而非 error。

    回归 Starlette 以线程池逐步迭代同步生成器导致的 “Token created in a different
    Context”：chat.py 用 copy_context() + 每步 ctx.run(next, inner) 驱动，覆盖在
    【后续】yield（不同 next() 调用）里仍可见，退出也无需跨 context reset。
    """
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.settings, "llm_model", "pro")

    seen: dict = {}

    def fake_run_turn(messages, context, db, reasoning_effort="medium", client_time="", user_id="local"):
        # 先 yield 一次（制造跨 next() 的多步迭代），再在后续步骤读取生效模型/provider
        yield ("status", {"phase": "x", "message": "start"})
        seen["model"] = llm.model_for("chat")
        seen["provider"] = llm._eff_provider()
        yield ("delta", {"text": "ok"})
        yield ("done", {})

    monkeypatch.setattr(chat_router.agent, "run_turn", fake_run_turn)

    r = client.post(
        "/api/chat/stream",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "context": {},
            "llm_override": {"provider": "anthropic", "model": "OVERRIDE-MODEL"},
        },
    )
    assert r.status_code == 200
    types = [e for e, _ in _parse_sse(r.text)]
    # 关键：结尾是 done，不是 error（若 Token 跨 context reset 会变 error）
    assert types[-1] == "done", f"应正常结束，实际事件：{types}"
    # 覆盖在流式生成器的后续步骤里仍生效（ctx.run 驱动，跨 yield 可见）
    assert seen["model"] == "OVERRIDE-MODEL"
    assert seen["provider"] == "anthropic"


def test_chat_stream_no_override_unaffected(client, monkeypatch):
    """不带 llm_override：流式生成器内生效模型回退服务端默认，结尾 done。"""
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.settings, "llm_model", "pro")

    seen: dict = {}

    def fake_run_turn(messages, context, db, reasoning_effort="medium", client_time="", user_id="local"):
        yield ("status", {"phase": "x", "message": "start"})
        seen["model"] = llm.model_for("chat")
        yield ("done", {})

    monkeypatch.setattr(chat_router.agent, "run_turn", fake_run_turn)

    r = client.post(
        "/api/chat/stream",
        json={"messages": [{"role": "user", "content": "hi"}], "context": {}},
    )
    assert r.status_code == 200
    types = [e for e, _ in _parse_sse(r.text)]
    assert types[-1] == "done"
    assert seen["model"] == "pro"
