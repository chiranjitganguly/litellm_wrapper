import os

import httpx

LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://llm-gateway:4000")
LITELLM_MASTER_KEY = os.environ["LITELLM_MASTER_KEY"]

_headers = {
    "Authorization": f"Bearer {LITELLM_MASTER_KEY}",
    "Content-Type": "application/json",
}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=LLM_GATEWAY_URL, headers=_headers, timeout=30.0)


async def generate_key(
    *,
    key_alias: str,
    agent_id: str,
    models: list[str] | None = None,
    max_budget: float | None = None,
    tpm_limit: int | None = None,
    rpm_limit: int | None = None,
) -> dict:
    """Provisions a LiteLLM virtual key scoped to one agent.

    Returns the full /key/generate response, including the raw key (only
    ever returned this once) — callers must persist it immediately.
    """
    payload = {
        "key_alias": key_alias,
        "metadata": {"agent_id": agent_id},
        "models": models or [],
        "max_budget": max_budget,
        "tpm_limit": tpm_limit,
        "rpm_limit": rpm_limit,
    }
    async with _client() as client:
        resp = await client.post("/key/generate", json=payload)
        resp.raise_for_status()
        return resp.json()


async def update_key(*, key: str, **fields) -> dict:
    async with _client() as client:
        resp = await client.post("/key/update", json={"key": key, **fields})
        resp.raise_for_status()
        return resp.json()


async def delete_key(*, key: str) -> dict:
    async with _client() as client:
        resp = await client.post("/key/delete", json={"keys": [key]})
        resp.raise_for_status()
        return resp.json()


async def get_key_info(*, key: str) -> dict:
    async with _client() as client:
        resp = await client.get("/key/info", params={"key": key})
        resp.raise_for_status()
        return resp.json()
