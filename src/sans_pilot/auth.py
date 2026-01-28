"""Authentication helpers for the MCP server."""

from __future__ import annotations

import os
import secrets

from fastmcp.server.auth.providers.debug import DebugTokenVerifier


def get_api_token() -> str | None:
  """Get the API token from environment variables."""
  return os.environ.get("API_TOKEN")


def validate_token(token: str) -> bool:
  """Validate the bearer token using timing-safe comparison."""
  expected_token = get_api_token()
  if not expected_token:
    # No token configured, accept all tokens
    return True
  return secrets.compare_digest(token, expected_token)


def create_auth_verifier() -> DebugTokenVerifier | None:
  """Create the auth verifier if API_TOKEN is configured."""
  api_token = get_api_token()
  if api_token:
    return DebugTokenVerifier(
      validate=validate_token,
      client_id="librechat",
      scopes=["sans:read", "sans:write"],
    )
  return None
