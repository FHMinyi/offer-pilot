"""请求级用户归属接缝（里程碑一：归属标签，非鉴权）。

本文件是「焊死 user_id 接缝、暂不通电」策略的核心：所有需要归属的新路由
统一 `Depends(get_current_user)` 取一个 `user_id` 字符串，里程碑一恒为
设备标签 / 'local'，里程碑三只换本函数实现（token → users 表 → 真实 id），
**函数签名与所有 user_id String(64) 列均不变**。
"""

from __future__ import annotations

from fastapi import Header

DEFAULT_USER = "local"


def get_current_user(
    x_device_id: str | None = Header(None, alias="X-Device-Id"),
) -> str:
    """从 X-Device-Id 头取归属标签，缺省 'local'，零鉴权。

    里程碑一：仅作归属标签（可被改 header 冒充，详见 ownership.py 的
    KNOWN-MULTI-TENANT-LEAK 说明）。里程碑三：替换为真实鉴权，签名不变。
    """
    uid = (x_device_id or "").strip()
    return uid[:64] if uid else DEFAULT_USER
