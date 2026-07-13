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


async def list_servers() -> list[dict]:
    async with _client() as client:
        resp = await client.get("/v1/mcp/server")
        resp.raise_for_status()
        return resp.json()


async def get_server(server_id: str) -> dict:
    async with _client() as client:
        resp = await client.get(f"/v1/mcp/server/{server_id}")
        resp.raise_for_status()
        return resp.json()


async def create_server(payload: dict) -> dict:
    async with _client() as client:
        resp = await client.post("/v1/mcp/server", json=payload)
        resp.raise_for_status()
        return resp.json()


async def update_server(payload: dict) -> dict:
    async with _client() as client:
        resp = await client.put("/v1/mcp/server", json=payload)
        resp.raise_for_status()
        return resp.json()


async def delete_server(server_id: str) -> None:
    async with _client() as client:
        resp = await client.delete(f"/v1/mcp/server/{server_id}")
        resp.raise_for_status()
