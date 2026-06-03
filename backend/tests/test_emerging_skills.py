"""新兴 AI/大模型 技能的识别与 free-form 保留测试（规则模式）。"""

from __future__ import annotations

from app.services import jd_parser, skills


def test_ontology_recognizes_emerging_ai_skills():
    m = skills.match_skills("用 LangChain 搭建 RAG，接入向量数据库 Qdrant，做 AI Agent，掌握 Prompt 工程")
    for key in ["langchain", "rag", "vector_db", "agent_dev", "prompt_engineering"]:
        assert key in m, f"未识别到 {key}"


def test_vector_db_distinct_from_relational_db():
    m = skills.match_skills("熟悉 MySQL，并用过向量数据库 Milvus")
    assert "database" in m  # MySQL → 关系型数据库
    assert "vector_db" in m  # 向量数据库 Milvus → 独立技能


def test_normalize_terms_keeps_freeform():
    out = skills.normalize_terms(["LangChain", "Dify", "TypeScript"])
    keys = {s["key"] for s in out}
    assert "langchain" in keys  # 本体内
    assert "typescript" in keys  # 本体内
    # Dify 未收录 → free-form，名称原样保留、归类「其他」
    dify = next(s for s in out if s["name"] == "Dify")
    assert dify["category"] == "其他"
    assert dify["key"] == "dify"


def test_jd_parser_picks_up_ai_stack():
    jd = jd_parser.parse_jd(
        "AI Agent 开发实习\n任职要求\n熟悉 LangChain、RAG 检索增强、向量数据库；了解 MCP 与 Prompt 工程"
    )
    keys = {s["key"] for s in jd["must_have"]} | {s["key"] for s in jd["nice_to_have"]}
    assert {"langchain", "rag", "vector_db"}.issubset(keys), keys


def test_skill_graph_has_ai_category():
    graph = skills.build_graph()
    cats = [c["category"] for c in graph["categories"]]
    assert "AI / 大模型" in cats
    ai = next(c for c in graph["categories"] if c["category"] == "AI / 大模型")
    ai_keys = {s["key"] for s in ai["skills"]}
    assert {"langchain", "rag", "vector_db", "agent_dev"}.issubset(ai_keys)
