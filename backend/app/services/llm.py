"""LLM 抽象层。

统一封装 OpenAI / Anthropic 两种 **API 协议** 的 JSON 输出调用。
provider 指的是协议而非厂商：配合 base_url，可对接任意兼容该协议的服务
（OpenAI 官方、Azure OpenAI、DeepSeek、Moonshot、OpenRouter、本地 vLLM/Ollama 等
走 openai 协议；Anthropic 官方或其兼容网关走 anthropic 协议）。

未配置或调用失败时，`complete_json` 抛出 `LLMUnavailable`，由上层解析器自动
降级为规则解析，从而保证在无任何密钥的情况下也能跑通完整闭环。
"""

from __future__ import annotations

import contextvars
import json
import logging
from contextlib import contextmanager

from ..config import get_settings

logger = logging.getLogger("offerpilot.llm")

settings = get_settings()

# 各 provider 的默认模型
_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-6",
}

# 「按请求覆盖」上下文：with use_llm_override(...) 块内生效，退出自动重置。
# 字段全部可选、空串=未设：provider, model, model_resume, model_jd, base_url, api_key。
_override: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "llm_override", default=None
)


@contextmanager
def use_llm_override(override: dict | None):
    """把「按请求覆盖」压入 contextvars，with 块内生效、退出自动重置。

    override 为 dict 或 None（空 dict 也归一为 None）。注意 contextvars 不会自动
    传播到子线程，并发解析需用 copy_context().run 携带本上下文（见 pipeline.py）。
    """
    token = _override.set(override or None)
    try:
        yield
    finally:
        _override.reset(token)


def set_override(override: dict | None) -> None:
    """在【当前】context 内设置覆盖（不返回 token、不负责重置）。

    供流式路由用 ``copy_context().run(set_override, ...)`` 在一个专属 context 里
    设一次，再用同一 context 驱动整个 SSE 生成器（见 routers/chat.py）。这样可
    避开 Starlette 以线程池逐步迭代同步生成器时、``with use_llm_override`` 的
    Token 会在不同 context 间 reset 而报 “created in a different Context” 的问题。
    ``use_llm_override`` 仍适用于单一 context 的同步调用（如测试、独立分析端点）。
    """
    _override.set(override or None)


def _safe_record(provider: str, model: str, raw_usage, streamed: bool = False) -> None:
    """归一并落库一次 token 用量。统计永不连累业务：整体 try/except 吞异常。

    raw_usage 为 SDK 的 usage 对象（或 None）；归一后 total==0（含 None）则不记账。
    归属上下文由 services.usage 的 contextvars 提供（path/user_id/… 由各路由/pipeline 设置）。
    """
    try:
        from .usage import current_ctx, normalize_usage, record_usage

        nu = normalize_usage(provider, raw_usage)
        if nu.total == 0:
            return
        record_usage(
            provider=provider, model=model, streamed=streamed, usage=nu, ctx=current_ctx()
        )
    except Exception as exc:  # noqa: BLE001 统计失败绝不影响 LLM 调用
        logger.debug("token 用量记录失败（已忽略）：%s", exc)


def _eff_provider() -> str:
    """生效 provider（覆盖非空才生效，否则回退 settings）。"""
    ov = _override.get() or {}
    return (ov.get("provider") or settings.llm_provider).lower()


def _eff_model_server() -> str:
    """服务端默认模型：settings.llm_model 留空时回退到生效 provider 的内置默认。"""
    return settings.llm_model or _DEFAULT_MODELS.get(_eff_provider(), "")


def _eff_model() -> str:
    """生效默认档模型：前端默认框 → 服务端默认。"""
    ov = _override.get() or {}
    return ov.get("model") or _eff_model_server()


def _eff_base_url() -> str:
    """生效 base_url：覆盖非空则用之，否则按生效 provider 取 settings.*_base_url。"""
    ov = _override.get() or {}
    if ov.get("base_url"):
        return ov["base_url"]
    if _eff_provider() == "anthropic":
        return settings.anthropic_base_url
    return settings.openai_base_url


def _eff_api_key() -> str:
    """生效 API Key：覆盖非空则用之，否则按生效 provider 取 settings.*_api_key。"""
    ov = _override.get() or {}
    if ov.get("api_key"):
        return ov["api_key"]
    if _eff_provider() == "anthropic":
        return settings.anthropic_api_key
    return settings.openai_api_key


class LLMUnavailable(Exception):
    """LLM 不可用（未配置或调用失败），用于触发规则降级。"""


def engine_name() -> str:
    """返回本次将使用的解析引擎标识。"""
    if llm_enabled():
        return f"llm:{_eff_provider()}"
    return "rule"


def llm_enabled() -> bool:
    """判断 LLM 是否可用。

    provider 合法，且配置了 API Key 或自定义 base_url 之一即视为可用
    （部分本地/兼容服务无需 Key，仅凭 base_url 即可调用）。
    """
    provider = _eff_provider()
    if provider == "openai":
        return bool(_eff_api_key() or _eff_base_url())
    if provider == "anthropic":
        return bool(_eff_api_key() or _eff_base_url())
    return False


def model_for(role: str) -> str:
    """按任务返回应使用的模型名。

    role: "resume" 解析简历 / "jd" 单条 JD 解析 / 其它(对话/聚合) 用默认。
    覆盖优先级：分档框 → 前端默认框 → 服务端分档 → 服务端默认。
    （前端某档留空＝该档回退到前端默认框；前端默认框也空＝整体回退到服务端 .env 分档。）
    """
    ov = _override.get() or {}
    if role == "resume":
        return (ov.get("model_resume") or ov.get("model")) or (
            settings.llm_model_resume or _eff_model_server()
        )
    if role == "jd":
        return (ov.get("model_jd") or ov.get("model")) or (
            settings.llm_model_jd or _eff_model_server()
        )
    return _eff_model()


def _extract_json(text: str) -> dict:
    """从模型返回文本中稳健地抽取 JSON 对象。"""
    text = text.strip()
    # 去掉可能的 ```json ... ``` 代码块包裹
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 退而求其次：截取第一个 { 到最后一个 }
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def complete_json(
    system: str, user: str, model: str | None = None, effort: str | None = None
) -> dict:
    """调用 LLM 并返回解析后的 JSON。失败时抛出 LLMUnavailable。

    model 指定本次使用的模型（用于按任务分流）；留空则用默认 _eff_model()。
    effort 为可选推理强度（6 档键），对支持的 provider 注入推理/思考；不支持时自动忽略。
    """
    if not llm_enabled():
        raise LLMUnavailable("未配置可用的 LLM provider / API Key")

    use_model = model or _eff_model()
    provider = _eff_provider()
    try:
        if provider == "openai":
            result = _call_openai(system, user, use_model, effort)
        elif provider == "anthropic":
            result = _call_anthropic(system, user, use_model, effort)
        else:
            raise LLMUnavailable(f"不支持的 provider: {provider}")
    except LLMUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 调用异常统一降级处理
        logger.warning("LLM 调用失败，降级为规则解析：%s", exc)
        raise LLMUnavailable(str(exc)) from exc
    # 顶层必须是 JSON 对象：模型偶发吐数组/标量（尤其无强制 json 模式的兼容服务）时
    # 按「不可用」降级，而非让调用方对 list/标量做 .get 崩溃（统一守护所有 complete_json 调用方）。
    if not isinstance(result, dict):
        logger.warning("LLM 返回非 JSON 对象（顶层为 %s），降级为规则解析", type(result).__name__)
        raise LLMUnavailable("LLM 返回的不是 JSON 对象")
    return result


# 记录哪些客户端类型在按环境代理构造时失败过，之后直接忽略环境代理，避免重复尝试与刷屏
_env_proxy_broken: set[str] = set()


def _build_client(factory, **kwargs):
    """构造 SDK 客户端，并对环境代理做容错。

    默认尊重环境中的代理变量（GFW 下访问官方端点常需要）；
    若代理变量无法被 httpx 解析（例如把 ALL_PROXY 写成 `socks://` 而非
    `socks5://`），则自动退回忽略环境代理重试，避免整个 LLM 链路不可用。
    首次失败后记住该类型，后续调用直接忽略环境代理。
    """
    name = getattr(factory, "__name__", str(factory))
    if name not in _env_proxy_broken:
        try:
            return factory(**kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "按环境代理构造 %s 失败（%s），后续将忽略环境代理", name, exc
            )
            _env_proxy_broken.add(name)
    import httpx

    return factory(**kwargs, http_client=httpx.Client(trust_env=False))


def _call_openai(system: str, user: str, model: str, effort: str | None = None) -> dict:
    from openai import OpenAI  # 延迟导入，未安装时自动降级

    # base_url 留空 -> 官方地址；填写 -> 任意 openai 兼容服务
    # 部分兼容服务无需鉴权，SDK 仍要求非空 key，这里用占位值兜底
    client = _build_client(
        OpenAI,
        api_key=_eff_api_key() or "not-needed",
        base_url=_eff_base_url() or None,
    )
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    eff = _OPENAI_EFFORT.get(effort)
    if eff:
        kwargs["reasoning_effort"] = eff
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception:  # noqa: BLE001 部分兼容服务不认识 reasoning_effort，去掉后重试
        if "reasoning_effort" in kwargs:
            kwargs.pop("reasoning_effort")
            resp = client.chat.completions.create(**kwargs)
        else:
            raise
    _safe_record(provider="openai", model=model, raw_usage=getattr(resp, "usage", None), streamed=False)
    return _extract_json(resp.choices[0].message.content or "")


def streaming_supported() -> bool:
    """当前是否支持对话 Agent（openai 流式 / anthropic 思考路径）。"""
    return _eff_provider() in ("openai", "anthropic") and llm_enabled()


# 思考强度（6 档）到各 provider 的映射
# openai 协议 reasoning_effort 仅支持 low/medium/high，故 xhigh/max 截到 high
_OPENAI_EFFORT = {
    "off": None,
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}
# anthropic 扩展思考用 budget_tokens（0 表示不开启思考）
_ANTHROPIC_BUDGET = {
    "off": 0,
    "low": 1024,
    "medium": 4096,
    "high": 8192,
    "xhigh": 16384,
    "max": 32000,
}


def agent_stream(
    messages: list[dict],
    tools: list[dict] | None = None,
    effort: str = "medium",
    tail_note: str = "",
):
    """对话 Agent 的统一流式入口，按 provider 分派，产出统一事件。

    事件：{"type":"reasoning"|"delta", ...} 与一次 {"type":"final", content, tool_calls, finish}。
    传入/返回的 messages、tools 均为 openai 格式，anthropic 的格式转换在内部完成，
    从而让上层 Agent 循环保持 provider 无关。

    tail_note：每轮易变的「尾注」（如语气），置于消息序列最末、落在缓存前缀之外，
    改它只作废尾注、不动 system+历史前缀（缓存评审：语气置尾）。
    """
    provider = _eff_provider()
    if provider == "anthropic":
        # 未知/非法档位默认 0（不开启思考），与 openai 路径对未知值不思考保持一致
        yield from anthropic_stream(messages, tools, _ANTHROPIC_BUDGET.get(effort, 0), tail_note=tail_note)
    else:
        yield from openai_stream(messages, tools, _OPENAI_EFFORT.get(effort), tail_note=tail_note)


def _reasoning_delta(delta) -> str | None:
    """从增量中取出“思考过程”文本（兼容 reasoning_content / reasoning 等字段）。"""
    rc = getattr(delta, "reasoning_content", None)
    if rc is None:
        extra = getattr(delta, "model_extra", None) or {}
        rc = extra.get("reasoning_content") or extra.get("reasoning")
    return rc or None


def openai_stream(
    messages: list[dict],
    tools: list[dict] | None = None,
    reasoning_effort: str | None = None,
    tail_note: str = "",
):
    """以 openai 协议进行一次流式对话，按增量产出事件。

    逐块 yield：
    - {"type": "reasoning", "text": str}                  模型思考过程增量（若模型支持）
    - {"type": "delta", "text": str}                      助手文本增量
    - {"type": "final", "content": str,
       "tool_calls": [{"id","name","arguments"}],
       "finish": str}                                     本次生成结束时的汇总

    reasoning_effort：'low'/'medium'/'high' 时尝试请求更强推理（对支持的模型生效，
    如 o 系列；不支持的服务会被自动忽略重试）。'off'/None 表示不请求。
    """
    from openai import OpenAI  # 延迟导入

    client = _build_client(
        OpenAI,
        api_key=_eff_api_key() or "not-needed",
        base_url=_eff_base_url() or None,
    )
    # 语气尾注作为尾随 system 消息置于序列最末——不影响 [system…历史] 前缀缓存，
    # 改语气只让这条尾随消息变化（缓存评审：语气置尾）。
    msgs = [*messages, {"role": "system", "content": tail_note}] if tail_note else messages
    kwargs: dict = {
        "model": _eff_model(),
        "messages": msgs,
        "temperature": 0.3,
        "stream": True,
        # 请求在流末尾附带本次 usage（含 prompt_tokens_details.cached_tokens）。
        # 不认此参数的兼容服务会在下方 except 分支去掉重试。
        "stream_options": {"include_usage": True},
    }
    if tools:
        kwargs["tools"] = tools
    if reasoning_effort and reasoning_effort != "off":
        kwargs["reasoning_effort"] = reasoning_effort

    try:
        stream = client.chat.completions.create(**kwargs)
    except Exception:  # noqa: BLE001 部分兼容服务不认识 reasoning_effort / stream_options，去掉后重试
        if "reasoning_effort" in kwargs or "stream_options" in kwargs:
            kwargs.pop("reasoning_effort", None)
            kwargs.pop("stream_options", None)
            stream = client.chat.completions.create(**kwargs)
        else:
            raise

    content = ""
    tool_slots: dict[int, dict] = {}
    finish = None
    captured_usage = None

    for chunk in stream:
        # usage 一般在最后一个（choices 为空的）块上下发，故先于「无 choices 则跳过」捕获
        if getattr(chunk, "usage", None):
            captured_usage = chunk.usage
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = choice.delta
        if delta:
            reasoning = _reasoning_delta(delta)
            if reasoning:
                yield {"type": "reasoning", "text": reasoning}
            if delta.content:
                content += delta.content
                yield {"type": "delta", "text": delta.content}
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = tool_slots.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        # 工具名首次出现即上报，便于上层在「生成工具参数」这段空窗给出反馈
                        if not slot["name"]:
                            yield {"type": "tool_pending", "name": tc.function.name}
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments
        if choice.finish_reason:
            finish = choice.finish_reason

    tool_calls = [tool_slots[i] for i in sorted(tool_slots)]
    _safe_record(provider="openai", model=_eff_model(), raw_usage=captured_usage, streamed=True)
    yield {"type": "final", "content": content, "tool_calls": tool_calls, "finish": finish}


def _tools_to_anthropic(tools: list[dict] | None) -> list[dict]:
    """openai 工具 schema -> anthropic 工具 schema。"""
    out = []
    for t in tools or []:
        fn = t.get("function", {})
        out.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return out


def _messages_to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    """openai 消息历史 -> (system, anthropic messages)。

    - system 消息合并为顶层 system 字符串
    - assistant 的 tool_calls -> tool_use content block
    - role=tool -> user 消息内的 tool_result content block
    - 连续同 role 合并为一条，满足 anthropic 的交替要求
    """
    system_parts: list[str] = []
    conv: list[dict] = []

    def _append(role: str, blocks: list[dict]) -> None:
        if conv and conv[-1]["role"] == role:
            conv[-1]["content"].extend(blocks)
        else:
            conv.append({"role": role, "content": list(blocks)})

    for m in messages:
        role = m.get("role")
        if role == "system":
            if m.get("content"):
                system_parts.append(m["content"])
        elif role == "user":
            _append("user", [{"type": "text", "text": m.get("content") or ""}])
        elif role == "assistant":
            blocks: list[dict] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    inp = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    inp = {}
                blocks.append({"type": "tool_use", "id": tc.get("id", ""), "name": fn.get("name", ""), "input": inp})
            if not blocks:
                blocks = [{"type": "text", "text": ""}]
            _append("assistant", blocks)
        elif role == "tool":
            _append(
                "user",
                [{"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""), "content": m.get("content") or ""}],
            )
    return ("\n\n".join(system_parts), conv)


def _add_cache_breakpoints(kwargs: dict) -> None:
    """给 anthropic 请求打提示词缓存断点（缓存评审 R3）。

    anthropic 协议必须显式 cache_control 才会缓存，不打断点 = 0 命中、每轮全价。
    两个断点：system 末尾（请求内 tools 在 system 之前，一并被该断点覆盖）+
    最后一条消息的最后一个 content block（覆盖对话历史前缀）。
    """
    if isinstance(kwargs.get("system"), str):
        kwargs["system"] = [
            {"type": "text", "text": kwargs["system"], "cache_control": {"type": "ephemeral"}}
        ]
    conv = kwargs.get("messages") or []
    if conv and isinstance(conv[-1].get("content"), list) and conv[-1]["content"]:
        conv[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}


def _strip_cache_breakpoints(kwargs: dict) -> bool:
    """剥掉缓存断点，返回是否有改动（兼容网关不认 cache_control 时去掉重试用）。"""
    changed = False
    if isinstance(kwargs.get("system"), list):
        kwargs["system"] = "\n\n".join(b.get("text", "") for b in kwargs["system"])
        changed = True
    for m in kwargs.get("messages") or []:
        for block in m.get("content") if isinstance(m.get("content"), list) else []:
            if isinstance(block, dict) and block.pop("cache_control", None) is not None:
                changed = True
    return changed


def anthropic_stream(
    messages: list[dict],
    tools: list[dict] | None = None,
    budget: int = 0,
    tail_note: str = "",
):
    """anthropic 协议的 Agent 单步（非逐 token 流式，但产出同样的事件结构）。

    支持扩展思考（thinking budget）与工具调用。为规避“思考块 + 工具续写”的签名约束，
    仅在尚无工具结果（即首轮、无续写）时开启思考。
    """
    import anthropic  # 延迟导入

    client = _build_client(
        anthropic.Anthropic,
        api_key=_eff_api_key() or "not-needed",
        base_url=_eff_base_url() or None,
    )
    system, conv = _messages_to_anthropic(messages)
    has_tool_result = any(m.get("role") == "tool" for m in messages)

    kwargs: dict = {
        "model": _eff_model() or "claude-sonnet-4-6",
        "max_tokens": 4096,
        "messages": conv,
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = _tools_to_anthropic(tools)
    if budget and budget > 0 and not has_tool_result:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        kwargs["max_tokens"] = max(4096, budget + 1024)
    _add_cache_breakpoints(kwargs)
    # 语气尾注：在打完缓存断点【之后】追加，使其落在最后一个断点之外——
    # 改语气只作废这一尾注 block，system+历史前缀仍命中（缓存评审：语气置尾）。
    if tail_note and conv and isinstance(conv[-1].get("content"), list):
        conv[-1]["content"].append({"type": "text", "text": tail_note})

    try:
        resp = client.messages.create(**kwargs)
    except Exception:  # noqa: BLE001 部分兼容网关不认 cache_control，剥掉后重试
        if _strip_cache_breakpoints(kwargs):
            resp = client.messages.create(**kwargs)
        else:
            raise
    _safe_record(provider="anthropic", model=kwargs["model"], raw_usage=getattr(resp, "usage", None), streamed=True)

    content = ""
    tool_calls: list[dict] = []
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "thinking":
            yield {"type": "reasoning", "text": getattr(block, "thinking", "") or ""}
        elif btype == "text":
            txt = getattr(block, "text", "") or ""
            content += txt
            yield {"type": "delta", "text": txt}
        elif btype == "tool_use":
            tool_calls.append(
                {"id": block.id, "name": block.name, "arguments": json.dumps(block.input, ensure_ascii=False)}
            )

    finish = "tool_calls" if tool_calls else (getattr(resp, "stop_reason", None) or "stop")
    yield {"type": "final", "content": content, "tool_calls": tool_calls, "finish": finish}


def _call_anthropic(system: str, user: str, model: str, effort: str | None = None) -> dict:
    import anthropic  # 延迟导入，未安装时自动降级

    client = _build_client(
        anthropic.Anthropic,
        api_key=_eff_api_key() or "not-needed",
        base_url=_eff_base_url() or None,
    )
    kwargs: dict = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.2,
        "system": system + "\n\n只输出一个 JSON 对象，不要任何额外说明或 Markdown 代码块。",
        "messages": [{"role": "user", "content": user}],
    }
    budget = _ANTHROPIC_BUDGET.get(effort, 0)
    if budget and budget > 0:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        kwargs["max_tokens"] = max(4096, budget + 1024)
    try:
        resp = client.messages.create(**kwargs)
    except Exception:  # noqa: BLE001 部分服务不支持扩展思考，去掉 thinking 后重试
        if "thinking" in kwargs:
            kwargs.pop("thinking")
            kwargs["max_tokens"] = 4096
            resp = client.messages.create(**kwargs)
        else:
            raise
    _safe_record(provider="anthropic", model=model, raw_usage=getattr(resp, "usage", None), streamed=False)
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return _extract_json("".join(parts))
