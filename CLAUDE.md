# Agentic Platform

A locally-hosted (Docker/OrbStack on macOS) platform for running and managing
LLM agents. Built incrementally — this document describes the current
architecture and the conventions to follow as it grows.

## What this platform is

Kong sits in front of everything as the platform's single API gateway/
ingress. **LiteLLM's admin UI is the only thing published directly to the
host** — every other service, including Kong's own Admin API and Kong
Manager, is reached exclusively through Kong's proxy port:

| Component        | Role                                                                 | Reached via Kong at |
|-------------------|----------------------------------------------------------------------|------|
| **Kong**           | Single ingress for the whole platform. DB-backed (own Postgres), configured declaratively through its Admin API by `infra/kong/bootstrap.sh`. Bundles its own admin UI (Kong Manager). | `:8000` (proxy, the only host-published Kong port); Admin API and Kong Manager are internal-only, reached via Kong itself at `/kong-admin/*` and `/kong-manager/*` |
| **LLM Gateway**    | All LLM calls. The official [LiteLLM](https://www.litellm.ai) proxy container — not custom code. Also the source of truth for virtual keys and registered MCP servers (see below). | `/llm/*` **and** directly at `http://localhost:4000` — the one intentional exception (see "Kong bypass" below) |
| **Agent Registry** | Catalog of agents (identity, description, owner). On agent creation, provisions a LiteLLM virtual key scoped to that agent (models, budget, rate limits) via LiteLLM's key-management API and stores the key reference. Has its own Postgres for agent identity — LiteLLM owns the key/budget/spend data. | `/agent-registry/*` |
| **MCP Registry**   | Thin control-plane wrapper around LiteLLM's native MCP server management (`/v1/mcp/server`). No database of its own — LiteLLM is the source of truth for registered MCP servers. | `/mcp-registry/*` |
| **MCP Gateway**    | Proxies MCP protocol traffic through to LiteLLM's unified MCP endpoint, which aggregates every registered MCP server and enforces per-key access control. | `/mcp-gateway/*` |

The platform will evolve (orchestration, observability, a UI, evals, etc.)
but these are the foundation. Don't design far beyond what's listed
in "Roadmap" below — add complexity when a real need shows up, not before.

## Why this shape

- **Kong is the ingress for everything except the LiteLLM admin UI.**
  Every other service is `expose`d on the internal Docker network only,
  never `ports:`-published to the host — including Kong's own Admin API
  (`:8001`) and Kong Manager (`:8002`), which are reached by routing
  through Kong's own proxy port back to itself (see `infra/kong/bootstrap.sh`).
  This means auth, rate limiting, logging, and routing policy live in one
  place instead of being reimplemented per service, and it matches where
  this platform is headed (OIDC/SSO in the roadmap) — that gets bolted
  onto Kong once, not onto four services. If you add a new service, give
  it `expose`, not `ports`, and add its route to `infra/kong/bootstrap.sh`.
  `llm-gateway` is the sole exception, published directly on `:4000` so
  its Admin UI works — see "Kong bypass" under "LLM Gateway (LiteLLM)
  specifics" for why and what that costs. Do not add another direct
  `ports:` publish without a similarly hard technical reason (a SPA that
  can't tolerate Kong's path-stripping) — route through Kong first.
- **LiteLLM does the LLM gateway job well already** — cost tracking, budgets,
  rate limits, 100+ provider routing, virtual keys, Prometheus metrics. We
  run its official proxy image (`ghcr.io/berriai/litellm`) rather than
  reimplementing any of that. Custom logic (agent-aware routing, policy)
  belongs in the services that call it, not inside the gateway itself.
- **Registries are metadata/control-plane, gateways are data-plane.** A
  registry answers "what exists and who can use it"; a gateway is the thing
  actually proxying live traffic and enforcing that answer. Keep that split
  — don't let a registry start proxying, and don't let a gateway start
  owning source-of-truth metadata.
- **Agent Registry and MCP Registry are separate services**, not one
  generic "registry" — they have different schemas, lifecycles, and (later)
  different access-control models. Merge them only if a concrete need
  appears, not preemptively.
- **LiteLLM already has MCP server management and virtual-key management
  built in — use them instead of reimplementing.** MCP Registry and MCP
  Gateway are deliberately thin: LiteLLM's `/v1/mcp/server` CRUD and unified
  `/mcp` endpoint already do server registration, tool aggregation, and
  per-key access control (`object_permission.mcp_servers` /
  `mcp_access_groups`). Similarly, Agent Registry doesn't invent its own
  auth/budget system — it calls LiteLLM's `/key/generate` /`/key/update`
  /`/key/delete` to provision a scoped virtual key per agent. Only build
  custom logic here when LiteLLM genuinely doesn't cover the need (e.g.
  agent-level metadata like "owner" or "description" that LiteLLM has no
  concept of); don't duplicate what it already does well.

## Stack & conventions

- **Language**: Python 3.12, FastAPI, for every custom service (Agent
  Registry, MCP Registry, MCP Gateway). Keep this consistent across
  services unless there's a strong reason to deviate.
- **Data layer**: each service that owns state gets its own Postgres
  instance (`sqlmodel` for models/queries). No shared database across
  services — a service's schema is private to it; other services talk to
  it over HTTP, never direct DB access. Not every service needs a
  database — MCP Registry has none because LiteLLM is its backing store
  (see "Why this shape"). Don't add a Postgres to a service "for
  consistency" if it has no actual state of its own to own.
- **SQLAlchemy/psycopg**: `DATABASE_URL` values must use the
  `postgresql+psycopg://` scheme (psycopg3), not bare `postgresql://`
  (which makes SQLAlchemy default to psycopg2, which isn't installed).
  `requirements.txt` installs `psycopg[binary]`, not `psycopg2-binary`.
- **Service layout** (per service under `services/<name>/`):
  ```
  services/<name>/
    app/
      main.py        # FastAPI app + route registration
      models.py       # SQLModel/pydantic models (once introduced)
      db.py            # engine/session setup (once introduced)
      routers/         # split routes here once main.py grows
    requirements.txt
    Dockerfile
    .env.example
  ```
  Start flat (`main.py` only, as scaffolded). Split into `routers/` /
  `models.py` / `db.py` only once a file actually gets unwieldy — don't
  pre-create empty structure.
- **Every service exposes `GET /health`** returning `{"status": "ok",
  "service": "<name>"}`. Docker healthchecks and future orchestration
  depend on this contract.
- **Config via environment variables**, loaded with `pydantic-settings`.
  Each service ships a committed `.env.example` and a gitignored `.env`
  for local secrets/config. Never commit a real `.env`.
- **Inter-service calls use plain HTTP** (`httpx`) directly against other
  services' container hostnames on the shared `agentic-platform` Docker
  network — service name resolution (e.g. `http://mcp-registry:8000`),
  not through Kong and not localhost. Kong is for platform-external
  ingress (host machine, agents, future UI); service-to-service calls
  inside Compose skip it.

## LLM Gateway (LiteLLM) specifics

- Config lives in `llm-gateway/config/config.yaml` — this is the
  source of truth for which models/providers are exposed. Add new models
  here, not by patching the container.
- Secrets (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `LITELLM_MASTER_KEY`,
  `DATABASE_URL`) live in `llm-gateway/.env` (gitignored); copy from
  `.env.example` to set up locally.
- LiteLLM has its own Postgres (`llm-gateway-db`) for virtual keys, spend
  tracking, etc. — separate from the app-level registry databases.
- Anything outside the Compose network (host machine, external agents, a
  future UI) calls the LLM Gateway via Kong at `http://localhost:8000/llm/*`
  using a virtual key issued by LiteLLM, never by calling OpenAI/Anthropic
  directly. Other services *inside* Compose call `llm-gateway:4000`
  directly (see inter-service call convention above). This is what makes
  cost tracking, budgets, and provider-swapping actually work
  platform-wide.
- When adding a new model/provider: edit `config.yaml`, add the API key to
  `.env`, restart the `llm-gateway` container. No code changes needed for
  the common case.
- **Kong bypass — LiteLLM Admin UI**: `llm-gateway` publishes `4000:4000`
  directly to the host in addition to being routed through Kong at
  `/llm/*`. This is deliberate: the LiteLLM Admin UI (`http://localhost:4000/ui`)
  is a SPA with hardcoded internal routes that don't tolerate Kong's
  `/llm` prefix-stripping, so it needs unprefixed access to work. Use
  `http://localhost:4000/ui` for admin/browser use (view spend, manage
  keys, register MCP servers by hand), and `http://localhost:8000/llm/*`
  or `http://localhost:4000` (both work) for API calls. This is the one
  intentional hole in "Kong is the only ingress" — it has no auth in
  front of it beyond LiteLLM's own login, so treat `:4000` as sensitive
  the same way you'd treat Kong's Admin API on `:8001`. If this platform
  is ever exposed beyond localhost, revisit this (put LiteLLM's UI behind
  Kong with a rewritten base path, or gate `:4000` some other way) rather
  than shipping it as-is.

## Agent Registry

- `POST /agents` creates an agent record *and* provisions a LiteLLM virtual
  key for it in the same call (`app/litellm_client.py` wraps
  `/key/generate`). The raw key is stored in the Agent Registry's own DB
  (`Agent.litellm_key`) — this DB is trusted/internal, so that's fine, but
  the key is never returned by any endpoint that isn't already
  agent-registry-internal. Don't add an endpoint that echoes it back.
- `DELETE /agents/{id}` revokes the LiteLLM key (`/key/delete`) before
  deleting the local row — keep key lifecycle and agent lifecycle in sync;
  don't let an agent row outlive its key or vice versa.
- Needs `LITELLM_MASTER_KEY` (to call LiteLLM's key-management API, which
  requires proxy-admin auth) and `LLM_GATEWAY_URL` in its env — see
  `services/agent-registry/.env.example`.
- Budgets/rate limits (`max_budget`, `tpm_limit`, `rpm_limit`) are accepted
  on `POST /agents` and passed straight through to LiteLLM at key-creation
  time; the Agent Registry doesn't track or enforce spend itself — LiteLLM
  does. Query spend via LiteLLM's `/key/info`, not via the Agent Registry.

## MCP Registry & MCP Gateway

- MCP Registry has no database — `GET/POST/PUT/DELETE /servers*` on the
  Agent Registry's `/mcp-registry/*` routes just call through to LiteLLM's
  `/v1/mcp/server*` endpoints (`app/litellm_client.py`) and return LiteLLM's
  response as-is. If you need to add registry-only metadata that LiteLLM's
  MCP server schema has no field for, that's a signal to reconsider this
  design, not to bolt on a local DB silently — raise it first.
- MCP Gateway's `/mcp/{path:path}` route forwards MCP protocol traffic
  (method, query params, headers, body) straight to LiteLLM's `/mcp` (or
  `/<server_alias>/mcp`) endpoint and streams the response back unchanged.
  It intentionally does no MCP-protocol-aware logic itself — LiteLLM
  aggregates registered servers and enforces per-key access
  (`object_permission.mcp_servers` / `mcp_access_groups`) already.
- A caller that wants to actually invoke MCP tools needs a LiteLLM virtual
  key with access to the relevant server(s)/access group(s) — i.e. an
  agent provisioned via the Agent Registry, or a key created directly
  against LiteLLM. The MCP Gateway does not issue or check keys itself; it
  passes the caller's `Authorization` header through to LiteLLM.
- Both services need `LLM_GATEWAY_URL`; MCP Registry additionally needs
  `LITELLM_MASTER_KEY` since server registration is an admin operation.

## Kong

- Kong is DB-backed (`kong-db` Postgres) and configured declaratively —
  `infra/kong/bootstrap.sh` calls the Admin API (`PUT` on
  `/services/...` and `/services/.../routes/...`) to upsert each
  service/route. It runs as the `kong-config` one-shot Compose service
  after Kong and all backends are up, and is idempotent — safe to re-run.
- To add a new route: add a `put_service` / `put_route` pair to
  `bootstrap.sh` for the new backend, then either re-run that container
  (`docker compose up kong-config`) or `docker compose up --build`.
- Current routing is flat path-prefix routing (`/llm`, `/agent-registry`,
  `/mcp-registry`, `/mcp-gateway`, `/kong-admin`, `/kong-manager`) with
  `strip_path=true`, so a request to `http://localhost:8000/agent-registry/health`
  reaches the Agent Registry's `/health`. No auth/rate-limiting plugins
  are configured yet — that's roadmap item 4 (OIDC), not implemented
  today.
- **Kong's own Admin API (`:8001`) and Kong Manager (`:8002`) are not
  published to the host** — only `expose`d internally. They're reached by
  routing Kong's proxy back to itself: `bootstrap.sh` registers two extra
  Kong "services" whose upstream URL is `http://kong:8001` and
  `http://kong:8002` respectively, so Kong proxies requests to its own
  other listeners just like any other backend. `http://localhost:8000/kong-admin/*`
  → Admin API, `http://localhost:8000/kong-manager` → Kong Manager UI.
  This keeps the "only LiteLLM is published directly" rule intact while
  still making both usable.
- Kong Manager is Kong's own bundled OSS admin UI (`Kong/kong-manager`,
  compatible with Kong OSS 3.4+, no Enterprise/Konnect required) — no
  separate container or database needed. It's enabled via
  `KONG_ADMIN_GUI_LISTEN=0.0.0.0:8002` on the `kong` service, with
  `KONG_ADMIN_GUI_URL` / `KONG_ADMIN_GUI_API_URL` pointed at the
  `/kong-manager` and `/kong-admin` Kong routes so the SPA's own asset and
  API references stay correct when served from behind Kong rather than
  directly on `:8002`. Its static assets (`/kconfig.js`, `/assets/*`,
  `/favicon.ico`, `/robots.txt`) are always requested by the browser as
  root-absolute paths regardless of `KONG_ADMIN_GUI_URL`, so
  `kong-manager-assets-route` in `bootstrap.sh` routes those specific
  root paths through to the same upstream with `strip_path=false` — if
  Kong Manager ever loads blank, that's the first thing to check.
- Auth on `/kong-admin/*` and `/kong-manager/*` is currently *none* — same
  local-dev caveat as before, just moved behind Kong instead of removed.
  Treat these paths as sensitive; lock them down (Kong auth plugin, or an
  IP restriction) before this platform is ever exposed beyond localhost.

## Docker / OrbStack

- Deployment is `docker-compose.yml` at the repo root, one Compose project
  named `agentic-platform`. All services share the `agentic-platform`
  network so they can address each other by service name.
- Target runtime is **OrbStack** on macOS (drop-in Docker Desktop
  replacement) — no OrbStack-specific config should be needed; if
  something only works on OrbStack and not vanilla Docker, treat that as a
  bug, not a feature.
- Bring the whole platform up with `docker compose up --build`. Bring up a
  single service with `docker compose up --build <service>` — Compose
  will start its declared dependencies (e.g. its Postgres) automatically.
- Each service+its Postgres are separate Compose services
  (`<name>` and `<name>-db`) with a healthcheck-gated `depends_on`, so
  dependents don't race a not-yet-ready database.

## Roadmap (directional, not committed)

Rough order of what's likely to get added as the platform matures — use
this to judge whether a proposed change fits the platform's current stage
or is getting ahead of it:

1. ~~Agent Registry: real schema + CRUD API.~~ Done — basic identity +
   LiteLLM key provisioning. Still missing: versions, capabilities,
   richer ownership model.
2. ~~MCP Registry: CRUD API.~~ Done, as a thin LiteLLM proxy.
3. ~~MCP Gateway: proxy logic.~~ Done — forwards to LiteLLM's `/mcp`.
4. Auth across the platform (likely OIDC, matching LiteLLM's own support
   for it) instead of per-service ad hoc secrets. Kong is unauthenticated
   today — this is next.
5. An orchestration/runtime layer for actually executing agents (not just
   cataloging them).
6. Observability: shared Prometheus/Grafana, log aggregation across
   services.
7. A UI/dashboard.

Don't build ahead of this list without checking in first — e.g. don't
start on OIDC while the registries still have no tests or real-world
usage to validate the current design against.

## Commands

```bash
# Start everything
docker compose up --build

# Start one service (+ its dependencies)
docker compose up --build agent-registry

# Tail logs
docker compose logs -f llm-gateway

# Tear down (keep volumes/data)
docker compose down

# Tear down and wipe data
docker compose down -v
```

## Local setup checklist

1. Copy every `.env.example` to `.env` in place (`llm-gateway/`,
   `services/agent-registry/`, `services/mcp-registry/`,
   `services/mcp-gateway/`). Agent Registry and MCP Registry both need
   `LITELLM_MASTER_KEY` to match whatever's set in `llm-gateway/.env`.
2. Fill in real provider API keys in `llm-gateway/.env`.
3. `docker compose up --build`.
4. Verify everything is reachable through Kong (only LiteLLM's admin port
   is published separately):
   - `curl localhost:8000/llm/health/liveliness` (LLM Gateway)
   - `curl localhost:8000/agent-registry/health`
   - `curl localhost:8000/mcp-registry/health`
   - `curl localhost:8000/mcp-gateway/health`
   - `curl localhost:8000/kong-admin/status` (Kong Admin API, via Kong)
5. Open Kong Manager at `http://localhost:8000/kong-manager` to
   browse/manage Kong's services and routes visually — no login/setup
   step needed; it's bundled into Kong itself, backed by the same
   `kong-db`.
6. Smoke-test the LiteLLM integration end to end:
   ```bash
   # Register an agent — provisions a real LiteLLM virtual key
   curl -X POST localhost:8000/agent-registry/agents \
     -H "Content-Type: application/json" \
     -d '{"name":"demo","allowed_models":["gpt-4o"],"max_budget":10}'

   # Register an MCP server — proxied straight to LiteLLM
   curl -X POST localhost:8000/mcp-registry/servers \
     -H "Content-Type: application/json" \
     -d '{"server_name":"demo_server","url":"https://example.com/mcp","transport":"http","auth_type":"none"}'
   ```
