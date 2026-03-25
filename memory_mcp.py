#!/usr/bin/env python3.12
"""
Claude Imprint — Memory MCP Server (FastMCP)
Exposes memory operations as MCP tools for all Claude Code sessions.

Usage:
  python3.12 memory_mcp.py           # stdio mode (for CC local use)
  python3.12 memory_mcp.py --http    # HTTP mode (for Claude.ai via tunnel)
"""

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP
import memory_manager as mem

is_http = "--http" in sys.argv

mcp = FastMCP(
    "imprint-memory",
    host="0.0.0.0" if is_http else "127.0.0.1",
    port=8000,
)


@mcp.tool()
def memory_remember(content: str, category: str = "general", source: str = "cc", importance: int = 5) -> str:
    """Store a memory. Call this when you encounter important information.
    category: facts/events/tasks/experience/general
    source: cc/telegram/wechat/chat"""
    return mem.remember(content=content, category=category, source=source, importance=importance)


@mcp.tool()
def memory_search(query: str, limit: int = 10) -> str:
    """Search memories. Supports semantic search (natural language)."""
    return mem.search_text(query=query, limit=limit)


@mcp.tool()
def memory_forget(keyword: str) -> str:
    """Delete memories containing the specified keyword."""
    return mem.forget(keyword=keyword)


@mcp.tool()
def memory_daily_log(text: str) -> str:
    """Append to today's daily log."""
    return mem.daily_log(text=text)


@mcp.tool()
def memory_list(category: Optional[str] = None, limit: int = 20) -> str:
    """List memories (newest first)."""
    items = mem.get_all(category=category, limit=limit)
    if not items:
        return "No memories yet"
    lines = []
    for m in items:
        lines.append(f"[{m['id']}] [{m['category']}|{m['source']}] {m['content']}  ({m['created_at']})")
    return "\n".join(lines)


if __name__ == "__main__":
    if is_http:
        import uvicorn
        import anyio
        import json as _json
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse

        # OAuth 2.0 credentials (stored in file, not hardcoded)
        CRED_FILE = Path.home() / ".imprint-oauth.json"
        if CRED_FILE.exists():
            _creds = _json.loads(CRED_FILE.read_text())
            CLIENT_ID = _creds["client_id"]
            CLIENT_SECRET = _creds["client_secret"]
            ACCESS_TOKEN = _creds["access_token"]
        else:
            CLIENT_ID = ""
            CLIENT_SECRET = ""
            ACCESS_TOKEN = ""

        class OAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                if request.url.path in ("/oauth/token", "/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource", "/oauth/authorize"):
                    return await call_next(request)
                if not ACCESS_TOKEN:
                    return await call_next(request)
                auth = request.headers.get("authorization", "")
                if auth == f"Bearer {ACCESS_TOKEN}":
                    return await call_next(request)
                return JSONResponse({"error": "unauthorized"}, status_code=401)

        app = mcp.streamable_http_app()
        from starlette.routing import Route as _Route
        mcp_route = app.routes[0]
        app.routes.append(_Route("/", mcp_route.endpoint, methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]))

        from starlette.routing import Route
        from starlette.requests import Request

        async def oauth_protected_resource(request: Request):
            """OAuth 2.0 Protected Resource Metadata (RFC 9728)"""
            base = str(request.base_url).rstrip("/")
            return JSONResponse({
                "resource": base,
                "authorization_servers": [base],
            })

        async def oauth_metadata(request: Request):
            """OAuth 2.0 Authorization Server Metadata (RFC 8414)"""
            base = str(request.base_url).rstrip("/")
            return JSONResponse({
                "issuer": base,
                "authorization_endpoint": f"{base}/oauth/authorize",
                "token_endpoint": f"{base}/oauth/token",
                "grant_types_supported": ["authorization_code", "client_credentials"],
                "response_types_supported": ["code"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["client_secret_post"],
            })

        async def oauth_authorize(request: Request):
            """Auto-approve and redirect back with authorization code"""
            from urllib.parse import urlencode
            redirect_uri = request.query_params.get("redirect_uri", "")
            state = request.query_params.get("state", "")
            code = ACCESS_TOKEN
            params = {"code": code, "state": state}
            from starlette.responses import RedirectResponse
            return RedirectResponse(f"{redirect_uri}?{urlencode(params)}")

        async def oauth_token(request: Request):
            """OAuth 2.0 token endpoint"""
            body = await request.body()
            try:
                params = dict(x.split("=") for x in body.decode().split("&"))
            except Exception:
                try:
                    params = _json.loads(body)
                except Exception:
                    return JSONResponse({"error": "invalid_request"}, status_code=400)

            grant_type = params.get("grant_type", "")
            if (grant_type == "client_credentials"
                and params.get("client_id") == CLIENT_ID
                and params.get("client_secret") == CLIENT_SECRET):
                return JSONResponse({
                    "access_token": ACCESS_TOKEN,
                    "token_type": "bearer",
                    "expires_in": 86400,
                })
            if (grant_type == "authorization_code"
                and params.get("code") == ACCESS_TOKEN):
                return JSONResponse({
                    "access_token": ACCESS_TOKEN,
                    "token_type": "bearer",
                    "expires_in": 86400,
                })
            return JSONResponse({"error": "invalid_client"}, status_code=401)

        app.routes.insert(0, Route("/.well-known/oauth-protected-resource", oauth_protected_resource, methods=["GET"]))
        app.routes.insert(1, Route("/.well-known/oauth-authorization-server", oauth_metadata, methods=["GET"]))
        app.routes.insert(2, Route("/oauth/authorize", oauth_authorize, methods=["GET"]))
        app.routes.insert(3, Route("/oauth/token", oauth_token, methods=["POST"]))
        app.add_middleware(OAuthMiddleware)

        print(f"Memory HTTP mode (OAuth): http://0.0.0.0:8000/mcp", flush=True)
        config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
        server = uvicorn.Server(config)
        anyio.run(server.serve)
    else:
        mcp.run(transport="stdio")
