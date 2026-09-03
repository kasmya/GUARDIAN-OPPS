"""Chaos Injector.

Thin service that fires failure scenarios into fraud-api on demand. The demo
dashboard talks to *this* service, never to fraud-api's admin endpoints
directly — keeping the "attacker surface" and the "victim service" separated
is a small but real security-hygiene point worth mentioning in the talk.
"""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

FRAUD_API = os.environ.get("FRAUD_API_URL", "http://fraud-api:8000")
TIMEOUT = httpx.Timeout(3.0)

app = FastAPI(title="chaos-injector", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "chaos-injector"}


async def _call(path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        try:
            r = await c.post(f"{FRAUD_API}{path}", params=params)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            raise HTTPException(502, f"fraud-api unreachable: {e}") from e


@app.post("/crash")
async def crash() -> dict:
    try:
        await _call("/admin/crash")
    except HTTPException:
        pass
    return {"scenario": "crash", "expected_recovery": "auto_restart"}


@app.post("/slow")
async def slow(ms: int = 800) -> dict:
    await _call("/admin/slow", params={"ms": ms})
    return {"scenario": "slow", "delay_ms": ms, "expected_recovery": "auto_restart"}


@app.post("/corrupt")
async def corrupt() -> dict:
    await _call("/admin/corrupt")
    return {
        "scenario": "corrupt",
        "expected_recovery": "human_approval_required",
        "note": "output distribution shifted; no crash, no latency spike",
    }


@app.post("/reset")
async def reset() -> dict:
    return await _call("/admin/reset")
