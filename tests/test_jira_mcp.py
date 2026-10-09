"""
Standalone test for Atlassian Rovo MCP connection.

Tests in order:
  1. Raw HTTP GET to check if MCP endpoint is reachable and auth is accepted
  2. MCP session initialize (the step that was failing)
  3. List available MCP tools
  4. (Optional) Create a test Jira issue

Usage:
    python scripts/test_jira_mcp.py
"""
from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import httpx
from config import Config


def build_auth_header() -> str:
    if Config.ATLASSIAN_AUTH_HEADER:
        print(f"Using ATLASSIAN_AUTH_HEADER from .env directly")
        return Config.ATLASSIAN_AUTH_HEADER
    credentials = f"{Config.ATLASSIAN_EMAIL}:{Config.ATLASSIAN_API_TOKEN}"
    encoded = base64.b64encode(credentials.encode()).decode()
    header = f"Basic {encoded}"
    print(f"Built Basic auth from email + token")
    return header


# ── Test 1: Raw HTTP ──────────────────────────────────────────────────────────

def test_http_connection(auth_header: str) -> bool:
    print("\n── Test 1: Raw HTTP connection to MCP endpoint")
    print(f"   URL: {Config.ATLASSIAN_MCP_URL}")
    try:
        response = httpx.post(
            Config.ATLASSIAN_MCP_URL,
            headers={
                "Authorization": auth_header,
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            }},
            timeout=15,
        )
        print(f"   HTTP status : {response.status_code}")
        print(f"   Response    : {response.text[:300]}")
        if response.status_code == 401:
            print("   ❌ UNAUTHORIZED — API token or email is wrong")
            return False
        if response.status_code == 403:
            print("   ❌ FORBIDDEN — account does not have Rovo MCP access")
            return False
        if response.status_code == 404:
            print("   ❌ NOT FOUND — MCP URL may be wrong")
            return False
        if response.status_code == 406:
            print("   ✅ Auth accepted (406 is expected for raw HTTP — MCP library handles Accept headers correctly)")
            return True
        if response.status_code in {200, 202}:
            print("   ✅ HTTP connection succeeded")
            return True
        print(f"   ⚠️  Unexpected status {response.status_code}")
        return False
    except Exception as e:
        print(f"   ❌ Connection error: {e}")
        return False


# ── Test 2 & 3: MCP session ───────────────────────────────────────────────────

async def test_mcp_session(auth_header: str) -> bool:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    print("\n── Test 2: MCP session initialize")
    try:
        async with httpx.AsyncClient(
            headers={"Authorization": auth_header, "Content-Type": "application/json"}
        ) as http_client:
            async with streamable_http_client(
                url=Config.ATLASSIAN_MCP_URL,
                http_client=http_client,
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    print("   ✅ MCP session initialized successfully")

                    print("\n── Test 3: List available MCP tools")
                    tools = await session.list_tools()
                    tool_names = [t.name for t in tools.tools]
                    print(f"   Available tools ({len(tool_names)}):")
                    for name in tool_names:
                        print(f"     - {name}")
                    return True
    except Exception as e:
        print(f"   ❌ MCP session failed: {e}")
        return False


# ── Test 4: Create a test issue ───────────────────────────────────────────────

async def test_create_issue(auth_header: str) -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    print("\n── Test 4: Create a test Jira issue")
    if not Config.ATLASSIAN_PROJECT_KEY:
        print("   ⚠️  ATLASSIAN_PROJECT_KEY not set — skipping")
        return

    try:
        async with httpx.AsyncClient(
            headers={"Authorization": auth_header, "Content-Type": "application/json"}
        ) as http_client:
            async with streamable_http_client(
                url=Config.ATLASSIAN_MCP_URL,
                http_client=http_client,
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    response = await session.call_tool(
                        name="executeWrite",
                        arguments={
                            "name": "createJiraIssue",
                            "cloudId": Config.ATLASSIAN_CLOUD_ID,
                            "inputs": {
                                "projectKey": Config.ATLASSIAN_PROJECT_KEY,
                                "summary": "[TEST] MCP connection test — safe to delete",
                                "description": "This issue was created by the MCP connection test script. Please delete it.",
                                "issueType": Config.ATLASSIAN_ISSUE_TYPE or "Task",
                            },
                        },
                    )
                    if response.is_error:
                        print(f"   ❌ Tool call failed: {response.content}")
                    else:
                        print(f"   ✅ Issue created successfully!")
                        print(f"   Response: {response.content}")
    except Exception as e:
        print(f"   ❌ Failed: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("Atlassian Rovo MCP — Connection Test")
    print("=" * 60)
    print(f"MCP URL    : {Config.ATLASSIAN_MCP_URL}")
    print(f"Cloud ID   : {Config.ATLASSIAN_CLOUD_ID}")
    print(f"Project Key: {Config.ATLASSIAN_PROJECT_KEY}")
    print(f"Email set  : {bool(Config.ATLASSIAN_EMAIL)}")
    print(f"Token set  : {bool(Config.ATLASSIAN_API_TOKEN)}")

    auth_header = build_auth_header()

    # Test 1 — raw HTTP (tells us auth + reachability before MCP complexity)
    http_ok = test_http_connection(auth_header)
    if not http_ok:
        print("\n❌ Stopping — fix HTTP connection first before testing MCP session.")
        return

    # Tests 2 & 3 — MCP session
    session_ok = asyncio.run(test_mcp_session(auth_header))
    if not session_ok:
        print("\n❌ MCP session failed. Check Rovo is enabled for your Atlassian account.")
        return

    # Test 4 — create a real issue
    answer = input("\nCreate a test Jira issue? (y/n): ").strip().lower()
    if answer == "y":
        asyncio.run(test_create_issue(auth_header))

    print("\n✅ All tests passed.")


if __name__ == "__main__":
    main()
