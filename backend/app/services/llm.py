"""LLM 抽象层。

统一封装 OpenAI / Anthropic 两种 **API 协议** 的 JSON 输出调用。
provider 指的是协议而非厂商：配合 base_url，可对接任意兼容该协议的服务
（OpenAI 官方、Azure OpenAI、DeepSeek、Moonshot、OpenRouter、本地 vLLM/Ollama 等
走 openai 协议；Anthropic 官方或其兼容网关走 anthropic 协议）。

未配置或调用失败时，`complete_json` 抛出 `LLMUnavailable`，由上层解析器自动
降级为规则解析，从而保证在无任何密钥的情况下也能跑通完整闭环。
"""

from __future__ import annotations

import json
import logging

from ..config import get_settings

logger = logging.getLogger("offerpilot.llm")

settings = get_settings()

# 各 provider 的默认模型
_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-6",
}


class LLMUnavailable(Exception):
    """LLM 不可用（未配置或调用失败），用于触发规则降级。"""


def engine_name() -> str:
    """返回本次将使用的解析引擎标识。"""
    if llm_enabled():
        return f"llm:{settings.llm_provider}"
    return "rule"


def llm_enabled() -> bool:
    """判断 LLM 是否可用。

    provider 合法，且配置了 API Key 或自定义 base_url 之一即视为可用
    （部分本地/兼容服务无需 Key，仅凭 base_url 即可调用）。
    """
    provider = settings.llm_provider.lower()
    if provider == "openai":
        return bool(settings.openai_api_key or settings.openai_base_url)
    if provider == "anthropic":
        return bool(settings.anthropic_api_key or settings.anthropic_base_url)
    return False


def _model() -> str:
    return settings.llm_model or _DEFAULT_MODELS.get(settings.llm_provider.lower(), "")


def model_for(role: str) -> str:
    """按任务返回应使用的模型名。

    role: "resume" 解析简历 / "jd" 单条 JD 解析 / 其它(对话/聚合) 用默认。
    具体任务模型留空时回退到默认 llm_model（再回退到 provider 内置默认）。
    """
    override = {
        "resume": settings.llm_model_resume,
        "jd": settings.llm_model_jd,
    }.get(role, "")
    return override or _model()


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


def complete_json(system: str, user: str, model: str | None = None) -> dict:
    """调用 LLM 并返回解析后的 JSON。失败时抛出 LLMUnavailable。

    model 指定本次使用的模型（用于按任务分流）；留空则用默认 _model()。
    """
    if not llm_enabled():
        raise LLMUnavailable("未配置可用的 LLM provider / API Key")

    use_model = model or _model()
    provider = settings.llm_provider.lower()
    try:
        if provider == "openai":
            return _call_openai(system, user, use_model)
        if provider == "anthropic":
            return _call_anthropic(system, user, use_model)
        raise LLMUnavailable(f"不支持的 provider: {provider}")
    except LLMUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 调用异常统一降级处理
        logger.warning("LLM 调用失败，降级为规则解析：%s", exc)
        raise LLMUnavailable(str(exc)) from exc


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


def _call_openai(system: str, user: str, model: str) -> dict:
    from openai import OpenAI  # 延迟导入，未安装时自动降级

    # base_url 留空 -> 官方地址；填写 -> 任意 openai 兼容服务
    # 部分兼容服务无需鉴权，SDK 仍要求非空 key，这里用占位值兜底
    client = _build_client(
        OpenAI,
        api_key=settings.openai_api_key or "not-needed",
        base_url=settings.openai_base_url or None,
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    return _extract_json(resp.choices[0].message.content or "")


def streaming_supported() -> bool:
    """当前是否支持对话 Agent（openai 流式 / anthropic 思考路径）。"""
    return settings.llm_provider.lower() in ("openai", "anthropic") and llm_enabled()


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


def agent_stream(messages: list[dict], tools: list[dict] | None = None, effort: str = "medium"):
    """对话 Agent 的统一流式入口，按 provider 分派，产出统一事件。

    事件：{"type":"reasoning"|"delta", ...} 与一次 {"type":"final", content, tool_calls, finish}。
    传入/返回的 messages、tools 均为 openai 格式，anthropic 的格式转换在内部完成，
    从而让上层 Agent 循环保持 provider 无关。
    """
    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        # 未知/非法档位默认 0（不开启思考），与 openai 路径对未知值不思考保持一致
        yield from anthropic_stream(messages, tools, _ANTHROPIC_BUDGET.get(effort, 0))
    else:
        yield from openai_stream(messages, tools, _OPENAI_EFFORT.get(effort))


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
        api_key=settings.openai_api_key or "not-needed",
        base_url=settings.openai_base_url or None,
    )
    kwargs: dict = {
        "model": _model(),
        "messages": messages,
        "temperature": 0.3,
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools
    if reasoning_effort and reasoning_effort != "off":
        kwargs["reasoning_effort"] = reasoning_effort

    try:
        stream = client.chat.completions.create(**kwargs)
    except Exception:  # noqa: BLE001 部分兼容服务不认识 reasoning_effort，去掉后重试
        if "reasoning_effort" in kwargs:
            kwargs.pop("reasoning_effort")
            stream = client.chat.completions.create(**kwargs)
        else:
            raise

    content = ""
    tool_slots: dict[int, dict] = {}
    finish = None

    for chunk in stream:
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


def anthropic_stream(messages: list[dict], tools: list[dict] | None = None, budget: int = 0):
    """anthropic 协议的 Agent 单步（非逐 token 流式，但产出同样的事件结构）。

    支持扩展思考（thinking budget）与工具调用。为规避“思考块 + 工具续写”的签名约束，
    仅在尚无工具结果（即首轮、无续写）时开启思考。
    """
    import anthropic  # 延迟导入

    client = _build_client(
        anthropic.Anthropic,
        api_key=settings.anthropic_api_key or "not-needed",
        base_url=settings.anthropic_base_url or None,
    )
    system, conv = _messages_to_anthropic(messages)
    has_tool_result = any(m.get("role") == "tool" for m in messages)

    kwargs: dict = {
        "model": _model() or "claude-sonnet-4-6",
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

    resp = client.messages.create(**kwargs)

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


def _call_anthropic(system: str, user: str, model: str) -> dict:
    import anthropic  # 延迟导入，未安装时自动降级

    client = _build_client(
        anthropic.Anthropic,
        api_key=settings.anthropic_api_key or "not-needed",
        base_url=settings.anthropic_base_url or None,
    )
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0.2,
        system=system + "\n\n只输出一个 JSON 对象，不要任何额外说明或 Markdown 代码块。",
        messages=[{"role": "user", "content": user}],
    )
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return _extract_json("".join(parts))
