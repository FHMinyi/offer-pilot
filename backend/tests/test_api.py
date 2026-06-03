"""API 端到端测试（TestClient，规则模式）。"""

from __future__ import annotations

from .sample_data import SAMPLE_JDS, SAMPLE_RESUME


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["engine"] == "rule"


def test_skill_graph(client):
    r = client.get("/api/skills/graph")
    assert r.status_code == 200
    body = r.json()
    assert "前端" in [c["category"] for c in body["categories"]]
    assert body["proficiency_levels"][0] == "了解"


def test_analysis_run_inline_and_history(client):
    payload = {
        "resume_text": SAMPLE_RESUME,
        "jd_texts": SAMPLE_JDS,
        "target_role": "前端实习",
        "weeks": 4,
    }
    r = client.post("/api/analysis/run", json=payload)
    assert r.status_code == 200, r.text
    run = r.json()

    assert run["id"] > 0
    assert run["engine"] == "rule"
    assert run["target_role"] == "前端实习"
    assert 0 <= run["match_score"] <= 100
    assert len(run["job_ids"]) == 3

    result = run["result"]
    assert result["skill_gap"]["must_have_gaps"]
    assert len(result["roadmap"]) == 4

    # 历史列表
    r2 = client.get("/api/analysis")
    assert r2.status_code == 200
    summaries = r2.json()
    assert any(s["id"] == run["id"] for s in summaries)
    mine = next(s for s in summaries if s["id"] == run["id"])
    assert mine["job_count"] == 3

    # 详情
    r3 = client.get(f"/api/analysis/{run['id']}")
    assert r3.status_code == 200
    assert r3.json()["id"] == run["id"]


def test_analysis_run_missing_inputs(client):
    r = client.post("/api/analysis/run", json={"resume_text": SAMPLE_RESUME, "weeks": 4})
    assert r.status_code == 400  # 缺少 JD


def test_resume_parse_and_jobs_import_then_reference_run(client):
    # 先粘贴解析简历
    r = client.post("/api/resumes/parse", json={"raw_text": SAMPLE_RESUME})
    assert r.status_code == 200
    resume_id = r.json()["id"]
    assert r.json()["structured"]["skills"], "应解析出技能"

    # 导入 JD
    r = client.post(
        "/api/jobs/import",
        json={"jobs": [{"raw_text": jd} for jd in SAMPLE_JDS]},
    )
    assert r.status_code == 200
    jobs = r.json()
    assert len(jobs) == 3
    job_ids = [j["id"] for j in jobs]

    # 引用模式运行分析
    r = client.post(
        "/api/analysis/run",
        json={"resume_id": resume_id, "job_ids": job_ids, "target_role": "前端实习", "weeks": 3},
    )
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["resume_id"] == resume_id
    assert sorted(run["job_ids"]) == sorted(job_ids)
    assert len(run["result"]["roadmap"]) == 3


def test_get_missing_analysis_404(client):
    r = client.get("/api/analysis/999999")
    assert r.status_code == 404
