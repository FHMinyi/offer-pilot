"""可复用 JD 库 CRUD 测试。"""

from __future__ import annotations


def test_saved_jd_crud(client):
    # 新建（标题留空 → 用内容首行兜底）
    r = client.post("/api/saved-jds", json={"title": "", "content": "高级前端实习生\n要求熟悉 Vue 与 TypeScript"})
    assert r.status_code == 200, r.text
    jd = r.json()
    jid = jd["id"]
    assert jd["title"] == "高级前端实习生"
    assert "Vue" in jd["content"]

    # 列表
    lst = client.get("/api/saved-jds").json()
    assert any(x["id"] == jid for x in lst)

    # 编辑
    r2 = client.put(f"/api/saved-jds/{jid}", json={"title": "前端实习(改)", "content": "新的 JD 内容"})
    assert r2.status_code == 200
    assert r2.json()["title"] == "前端实习(改)"
    assert client.get("/api/saved-jds").json()[0]["content"] == "新的 JD 内容"  # 最近更新排最前

    # 删除
    assert client.delete(f"/api/saved-jds/{jid}").json()["ok"] is True
    assert all(x["id"] != jid for x in client.get("/api/saved-jds").json())


def test_saved_jd_404(client):
    assert client.put("/api/saved-jds/999999", json={"title": "x", "content": "y"}).status_code == 404
    assert client.delete("/api/saved-jds/999999").status_code == 404


def test_saved_jd_requires_content(client):
    assert client.post("/api/saved-jds", json={"title": "空", "content": ""}).status_code == 422
