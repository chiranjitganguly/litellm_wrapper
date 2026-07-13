from fastapi import FastAPI, HTTPException
from httpx import HTTPStatusError

from app import litellm_client

app = FastAPI(title="MCP Registry")


@app.get("/health")
def health():
    return {"status": "ok", "service": "mcp-registry"}


@app.get("/servers")
async def list_servers():
    return await litellm_client.list_servers()


@app.get("/servers/{server_id}")
async def get_server(server_id: str):
    try:
        return await litellm_client.get_server(server_id)
    except HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@app.post("/servers", status_code=201)
async def create_server(payload: dict):
    try:
        return await litellm_client.create_server(payload)
    except HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@app.put("/servers")
async def update_server(payload: dict):
    try:
        return await litellm_client.update_server(payload)
    except HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


@app.delete("/servers/{server_id}", status_code=204)
async def delete_server(server_id: str):
    try:
        await litellm_client.delete_server(server_id)
    except HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
