#!/bin/sh
# Declares Kong services/routes via the Admin API. Idempotent: each call
# upserts (PUT) so re-running this on every `docker compose up` is safe.
set -eu

KONG_ADMIN_URL="http://kong:8001"

put_service() {
  name="$1"
  url="$2"
  curl -s -o /dev/null -w "service %s -> %s [%{http_code}]\n" "$name" "$url" \
    -X PUT "${KONG_ADMIN_URL}/services/${name}" \
    -d "url=${url}"
}

put_route() {
  service_name="$1"
  route_name="$2"
  path_prefix="$3"
  curl -s -o /dev/null -w "route %s (%s) [%{http_code}]\n" "$route_name" "$path_prefix" \
    -X PUT "${KONG_ADMIN_URL}/services/${service_name}/routes/${route_name}" \
    -d "paths[]=${path_prefix}" \
    -d "strip_path=true"
}

# LLM Gateway (LiteLLM) — proxied at /llm/*
put_service "llm-gateway" "http://llm-gateway:4000"
put_route "llm-gateway" "llm-gateway-route" "/llm"

# Agent Registry — proxied at /agent-registry/*
put_service "agent-registry" "http://agent-registry:8000"
put_route "agent-registry" "agent-registry-route" "/agent-registry"

# MCP Registry — proxied at /mcp-registry/*
put_service "mcp-registry" "http://mcp-registry:8000"
put_route "mcp-registry" "mcp-registry-route" "/mcp-registry"

# MCP Gateway — proxied at /mcp-gateway/*
put_service "mcp-gateway" "http://mcp-gateway:8000"
put_route "mcp-gateway" "mcp-gateway-route" "/mcp-gateway"

# Kong's own Admin API — proxied at /kong-admin/*. Kong routing to itself
# in-container via its own proxy port, not localhost, since this is just
# another upstream service from the proxy's point of view.
put_service "kong-admin" "http://kong:8001"
put_route "kong-admin" "kong-admin-route" "/kong-admin"

# Kong Manager (bundled admin UI, port 8002) — proxied at /kong-manager/*.
# KONG_ADMIN_GUI_URL/KONG_ADMIN_GUI_API_URL on the kong service are set to
# match these paths so the SPA's own links and API calls stay consistent
# with being served from behind Kong rather than directly on :8002.
put_service "kong-manager" "http://kong:8002"
put_route "kong-manager" "kong-manager-route" "/kong-manager"

# Kong Manager's static assets (kconfig.js, /assets/*, favicon.ico, etc.)
# are always referenced by the SPA as root-absolute paths, regardless of
# KONG_ADMIN_GUI_URL — it does not rewrite them to live under /kong-manager.
# Route those specific root paths straight through to the same upstream,
# WITHOUT stripping, so the browser's root-relative requests still resolve.
# The bare "/" root stays unclaimed/404 — only these known asset paths are
# routed — so this can't collide with any other service's routes.
curl -s -o /dev/null -w "route kong-manager-assets [%{http_code}]\n" \
  -X PUT "${KONG_ADMIN_URL}/services/kong-manager/routes/kong-manager-assets-route" \
  -d "paths[]=/assets" \
  -d "paths[]=/kconfig.js" \
  -d "paths[]=/favicon.ico" \
  -d "paths[]=/robots.txt" \
  -d "strip_path=false"

echo "Kong bootstrap complete."
