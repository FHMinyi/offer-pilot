"""单点防越权「形」（里程碑一放行，里程碑三启用）。

把「按 user_id 收窄查询」与「校验对象归属」收敛到这两个函数：里程碑一全部
**放行**（不加 where、不校验 owner，保证 41 个无 header 测试与「打开即用」不破），
里程碑三只改这两处实现即可一处收紧全站，无需散落各路由改写。

KNOWN-MULTI-TENANT-LEAK（里程碑三收口）：本期 X-Device-Id 仅归属标签、可冒充，
且既有 `conversations.py` / `analysis.py` 为全表返回。本期定位「演示 / 单租户」，
真实多租户隔离推迟到里程碑三：换 deps.get_current_user 实现 + 放开下方两处校验。
"""

from __future__ import annotations

from fastapi import HTTPException


def scope_to_user(stmt, model, user_id):
    """按 user_id 收窄查询。里程碑一：放行（原样返回 stmt）。

    里程碑三：return stmt.where(model.user_id == user_id)
    """
    return stmt


def require_owned(db, model, obj_id, user_id):
    """取对象并校验归属。里程碑一：仅校验存在性（不存在 404），不校验 owner。

    里程碑三：放开下方 owner 校验，越权返回 403。
    """
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} 不存在。")
    # 里程碑三启用：
    # if getattr(obj, "user_id", None) != user_id:
    #     raise HTTPException(status_code=403, detail="无权访问。")
    return obj
