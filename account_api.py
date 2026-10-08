# -*- coding: utf-8 -*-
"""Helpers HTTP para os endpoints documentados da Free Fire API."""
from __future__ import annotations

from typing import Any
import aiohttp

API_BASE = "https://hostfreefire-api.squareweb.app/api"


def api_region(region: Any) -> str:
    code = str(region or "BR").strip().upper()
    if code in {"BR", "SAC", "US", "NA", "LATAM", "BRAZIL"}:
        return "br"
    if code in {"IND", "IN", "INDIA"}:
        return "ind"
    if code in {"SG", "EU", "ME", "VN", "TW", "PK", "RU", "BD", "ID", "TH"}:
        return "sg"
    return "br"


async def api_get(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """Executa apenas GET em uma rota documentada; nunca registra query/segredos."""
    timeout = aiohttp.ClientTimeout(total=15, connect=5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{API_BASE}/{path.lstrip('/')}", params=params) as response:
                payload = await response.json(content_type=None)
                return payload if isinstance(payload, dict) else None
    except Exception:
        return None


async def guest_access_token(uid: str, password: str) -> str | None:
    payload = await api_get("guest", {"guest_uid": uid, "guest_password": password})
    info = payload.get("guestBasicInfo") if isinstance(payload, dict) else None
    token = info.get("access_token") if isinstance(info, dict) else None
    return str(token) if token else None
