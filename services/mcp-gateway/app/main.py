import os

import httpx
from fastapi import FastAPI, Request, Response

LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://llm-gateway:4000")

app = FastAPI(title="MCP Gateway")

_client = httpx.AsyncClient(base_url=LLM_GATEWAY_URL, timeout=None)


@app.get("/health")
def health():
    return {"status": "ok", "service": "mcp-gateway"}


@app.api_route("/mcp/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_mcp(path: str, request: Request):
    """Proxies MCP protocol traffic to the LiteLLM unified MCP endpoint.

    LiteLLM aggregates every registered MCP server behind /mcp (all servers
    the caller's key can access) or /<server_alias>/mcp (one server). This
    gateway forwards the caller's virtual key straight through so LiteLLM's
    own per-key MCP access control applies.
    """
    body = await request.body()
    upstream_headers = {
        k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")
    }

    upstream_resp = await _client.request(
        request.method,
        f"/{path}",
        params=request.query_params,
        headers=upstream_headers,
        content=body,
    )

    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers={
            k: v
            for k, v in upstream_resp.headers.items()
            if k.lower() not in ("content-encoding", "transfer-encoding", "connection")
        },
    )
