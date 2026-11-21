"""Starting the server as Claude Desktop and Claude Code do: a process speaking MCP over stdio."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

START_SERVER = "from cratedigger_mcp.server import main; main()"


def clean_env(**extra: str) -> dict[str, str]:
    """The parent environment without any Discogs token the developer may have set."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("DISCOGS_")}
    return env | extra


@pytest.mark.parametrize("token", [None, "", "   "])
def test_missing_token_stops_the_server_with_a_message_on_stderr(
    token: str | None, tmp_path: Path
) -> None:
    env = clean_env() if token is None else clean_env(DISCOGS_TOKEN=token)

    process = subprocess.run(
        [sys.executable, "-c", START_SERVER],
        env=env,
        cwd=tmp_path,
        input="",
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert process.returncode != 0
    assert process.stdout == ""
    assert "DISCOGS_TOKEN" in process.stderr
    assert "https://www.discogs.com/settings/developers" in process.stderr
    assert "Traceback" not in process.stderr


def test_server_writes_nothing_to_stdout_on_its_own(tmp_path: Path) -> None:
    process = subprocess.run(
        [sys.executable, "-c", START_SERVER],
        env=clean_env(DISCOGS_TOKEN="dummy-token"),
        cwd=tmp_path,
        input="",
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert process.stdout == ""
    assert "dummy-token" not in process.stderr


async def test_server_speaks_mcp_over_stdio(tmp_path: Path) -> None:
    transport = StdioTransport(
        command=sys.executable,
        args=["-c", START_SERVER],
        env=clean_env(DISCOGS_TOKEN="dummy-token"),
        cwd=str(tmp_path),
    )

    async with Client(transport) as client:
        tools = await client.list_tools()

    # The full catalog is pinned in test_tool_catalog; here it is enough that tools are served.
    assert "discogs_get_release" in {tool.name for tool in tools}


def test_unsupported_currency_stops_the_server_with_the_supported_ones(tmp_path: Path) -> None:
    process = subprocess.run(
        [sys.executable, "-c", START_SERVER],
        env=clean_env(DISCOGS_TOKEN="dummy-token", DISCOGS_CURRENCY="XYZ"),
        cwd=tmp_path,
        input="",
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert process.returncode != 0
    assert process.stdout == ""
    assert "discogs_currency" in process.stderr
    assert "'EUR'" in process.stderr
    assert "Traceback" not in process.stderr
