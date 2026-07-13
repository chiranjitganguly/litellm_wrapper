import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class Agent(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str | None = None
    owner: str | None = None

    # LiteLLM virtual key provisioned for this agent. The raw key itself is
    # stored here since this DB is private to the platform's own trusted
    # services — never returned over the network to non-admin callers.
    litellm_key: str
    litellm_key_alias: str
    allowed_models: str = ""  # comma-separated model_names allowed via LiteLLM

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
