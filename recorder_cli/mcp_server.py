import json
import os
import secrets
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import click
from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier

from recorder_cli.recorder import RecorderClient

try:
    _VERSION = version("google-recorder-cli")
except PackageNotFoundError:
    _VERSION = "0.0.0.dev0"

mcp = FastMCP("google-recorder", version=_VERSION)
client = RecorderClient()

TOKEN_PATH = Path.home() / ".recorder-cli" / "mcp_token"


@mcp.tool
async def list_recordings() -> str:
    """List all recordings from Google Recorder.

    Returns JSON array of recordings with id, title, date, and duration.
    """
    recordings = await client.list_recordings()
    return json.dumps([
        {
            "id": r.id,
            "title": r.title,
            "created_at": r.created_at.isoformat(),
            "duration_seconds": r.duration_seconds,
            "has_transcript": r.has_transcript,
        }
        for r in recordings
    ], indent=2)


@mcp.tool
async def get_transcript(recording_id: str) -> str:
    """Get the transcript for a recording.

    Args:
        recording_id: The ID of the recording to get the transcript for.

    Returns plain text transcript.
    """
    t = await client.get_transcript(recording_id)
    return t.full_text


@mcp.tool
async def download_audio(recording_id: str, output_path: str) -> str:
    """Download audio file for a recording.

    Args:
        recording_id: The ID of the recording to download.
        output_path: Directory to save the audio file.

    Returns the absolute path to the saved .m4a file.
    """
    filepath = await client.download_audio(recording_id, Path(output_path))
    return str(filepath.resolve())


@mcp.tool
async def get_recording_info(recording_id: str) -> str:
    """Get metadata for a single recording.

    Args:
        recording_id: The ID of the recording.

    Returns JSON object with full metadata.
    """
    rec = await client.get_recording_info(recording_id)
    return json.dumps({
        "id": rec.id,
        "title": rec.title,
        "created_at": rec.created_at.isoformat(),
        "duration_seconds": rec.duration_seconds,
        "has_transcript": rec.has_transcript,
    }, indent=2)


@mcp.tool
async def search_recordings(query: str) -> str:
    """Search recordings by keyword.

    Args:
        query: Search keyword to match against recording titles.

    Returns JSON array of matching recordings.
    """
    results = await client.search_recordings(query)
    return json.dumps([
        {
            "id": r.id,
            "title": r.title,
            "created_at": r.created_at.isoformat(),
            "duration_seconds": r.duration_seconds,
        }
        for r in results
    ], indent=2)


def _load_or_create_token() -> str:
    """Load the persisted bearer token, generating one (owner-readable only) on first run."""
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    fd = os.open(TOKEN_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    return token


def run_server(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8420) -> None:
    """Run the MCP server. stdio serves a local client subprocess; http requires bearer auth."""
    if transport == "stdio":
        mcp.run()
        return

    # The token is never printed — read it from the file when configuring a client.
    token = _load_or_create_token()
    mcp.auth = StaticTokenVerifier(tokens={token: {"client_id": "recorder-mcp-client"}})
    click.echo(f"Bearer auth required; token stored at {TOKEN_PATH}")
    click.echo(f"Listening on http://{host}:{port}/mcp — loopback-only unless you deliberately front it with a tunnel.")
    mcp.run(transport="http", host=host, port=port)


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http"]),
    default="stdio",
    help="stdio for a local client subprocess (what registrations use); http to serve over the network.",
)
@click.option("--host", default="127.0.0.1", help="Bind address for --transport http.")
@click.option("--port", default=8420, type=int, help="Bind port for --transport http.")
def main(transport, host, port):
    """Entry point for the recorder-mcp binary."""
    run_server(transport, host, port)
