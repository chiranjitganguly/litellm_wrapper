from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from httpx import HTTPStatusError
from pydantic import BaseModel
from sqlmodel import Session, select

from app import litellm_client
from app.db import get_session, init_db
from app.models import Agent

app = FastAPI(title="Agent Registry")

SessionDep = Annotated[Session, Depends(get_session)]


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok", "service": "agent-registry"}


class AgentCreate(BaseModel):
    name: str
    description: str | None = None
    owner: str | None = None
    allowed_models: list[str] = []
    max_budget: float | None = None
    tpm_limit: int | None = None
    rpm_limit: int | None = None


class AgentPublic(BaseModel):
    id: str
    name: str
    description: str | None
    owner: str | None
    litellm_key_alias: str
    allowed_models: str


@app.post("/agents", response_model=AgentPublic, status_code=201)
async def create_agent(payload: AgentCreate, session: SessionDep):
    existing = session.exec(select(Agent).where(Agent.name == payload.name)).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"agent '{payload.name}' already exists")

    key_alias = f"agent-{payload.name}"
    try:
        key_response = await litellm_client.generate_key(
            key_alias=key_alias,
            agent_id=payload.name,
            models=payload.allowed_models,
            max_budget=payload.max_budget,
            tpm_limit=payload.tpm_limit,
            rpm_limit=payload.rpm_limit,
        )
    except HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"LiteLLM key provisioning failed: {e.response.text}")

    agent = Agent(
        name=payload.name,
        description=payload.description,
        owner=payload.owner,
        litellm_key=key_response["key"],
        litellm_key_alias=key_alias,
        allowed_models=",".join(payload.allowed_models),
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent


@app.get("/agents", response_model=list[AgentPublic])
def list_agents(session: SessionDep):
    return session.exec(select(Agent)).all()


@app.get("/agents/{agent_id}", response_model=AgentPublic)
def get_agent(agent_id: str, session: SessionDep):
    agent = session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


@app.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, session: SessionDep):
    agent = session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="agent not found")

    try:
        await litellm_client.delete_key(key=agent.litellm_key)
    except HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"LiteLLM key revocation failed: {e.response.text}")

    session.delete(agent)
    session.commit()
