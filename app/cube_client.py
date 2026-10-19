"""Thin client cho Cube REST API (/meta, /load, /sql)."""
from __future__ import annotations

import json
import os
import time

import httpx
import jwt

CUBE_API_URL = os.getenv("CUBE_API_URL", "http://localhost:4000/cubejs-api/v1")
CUBE_SECRET = os.getenv("CUBEJS_API_SECRET", "dev-secret-change-me")
DEFAULT_TZ = os.getenv("CUBE_TIMEZONE", "Asia/Singapore")

_meta_cache: dict = {"at": 0.0, "data": None}


def _token(user_id: str) -> str:
    # security context -> Cube có thể dùng cho row-level security (queryRewrite) về sau
    payload = {"sub": user_id, "user_id": user_id, "exp": int(time.time()) + 3600}
    return jwt.encode(payload, CUBE_SECRET, algorithm="HS256")


def _headers(user_id: str) -> dict:
    return {"Authorization": _token(user_id), "Content-Type": "application/json"}


def get_meta(user_id: str = "agent", ttl: int = 300) -> dict:
    if _meta_cache["data"] and time.time() - _meta_cache["at"] < ttl:
        return _meta_cache["data"]
    r = httpx.get(f"{CUBE_API_URL}/meta", headers=_headers(user_id), timeout=30)
    r.raise_for_status()
    _meta_cache.update(at=time.time(), data=r.json())
    return _meta_cache["data"]


def public_members(user_id: str = "agent") -> dict[str, dict]:
    """Chỉ lấy member của *views* (bề mặt đã curate). Fallback sang cubes nếu chưa có view."""
    meta = get_meta(user_id)
    items = meta.get("cubes", [])
    views = [c for c in items if c.get("type") == "view"] or items
    out: dict[str, dict] = {}
    for c in views:
        for kind in ("measures", "dimensions"):
            for m in c.get(kind, []):
                if m.get("public", True) is False or m.get("isVisible") is False:
                    continue
                out[m["name"]] = {
                    "kind": kind[:-1],
                    "type": m.get("type"),
                    "title": m.get("shortTitle") or m.get("title"),
                    "description": m.get("description", ""),
                    "synonyms": (m.get("meta") or {}).get("synonyms_vi", []),
                    "view": c["name"],
                    "view_description": c.get("description", ""),
                }
    return out


def load(query: dict, user_id: str = "agent", max_wait_s: int = 120) -> dict:
    """POST /load, tự retry khi Cube trả 'Continue wait' (query dài / đang build pre-agg)."""
    query = {"timezone": DEFAULT_TZ, **query}
    deadline = time.time() + max_wait_s
    while True:
        r = httpx.post(f"{CUBE_API_URL}/load", headers=_headers(user_id),
                       content=json.dumps({"query": query}), timeout=60)
        body = r.json()
        if body.get("error") == "Continue wait":
            if time.time() > deadline:
                raise TimeoutError("Cube query vẫn đang chạy quá lâu")
            time.sleep(1.5)
            continue
        if r.status_code >= 400 or "error" in body:
            raise ValueError(body.get("error", r.text))
        return body


def to_sql(query: dict, user_id: str = "agent") -> str:
    query = {"timezone": DEFAULT_TZ, **query}
    r = httpx.get(f"{CUBE_API_URL}/sql", headers=_headers(user_id),
                  params={"query": json.dumps(query)}, timeout=30)
    if r.status_code >= 400:
        return ""
    sql = r.json().get("sql", {}).get("sql", [""])
    return sql[0] if isinstance(sql, list) else str(sql)
