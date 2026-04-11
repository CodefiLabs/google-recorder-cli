# google-recorder-cli Implementation Plan

## Overview

Build `google-recorder-cli` — a Python CLI tool and MCP server for recorder.google.com using Playwright network interception. The tool lets users list recordings, copy transcripts, download audio, and access metadata programmatically.

## Current State Analysis

- Greenfield project — only `.git/` and `docs/` exist
- Design spec is approved and comprehensive: `docs/superpowers/specs/2026-04-11-recorder-cli-design.md`
- No existing code, no dependencies installed, no pyproject.toml

### Key Discoveries:
- recorder.google.com's internal JSON API shape is unknown — must use generic interception
- Playwright is async; Click is sync — need `asyncio.run()` bridge in each command
- FastMCP standalone package (`pip install fastmcp`) is the correct choice, not the bundled `mcp` SDK version
- Google sessions persist weeks via `storage_state`; detect expiry by login page redirect

## Desired End State

A working Python package installable via `pip install -e .` with:
1. `recorder` CLI command with all subcommands (login, list, transcript, download, info, search, sync)
2. `recorder-mcp` MCP server with all tools (list_recordings, get_transcript, download_audio, get_recording_info, search_recordings)
3. Full test suite
4. README with installation and usage instructions

Verification: `recorder --help` shows all commands; `recorder-mcp` starts without error; tests pass.

## What We're NOT Doing

- Reverse-engineering the actual recorder.google.com API (we build the interception framework; real payloads come later during manual testing)
- Creating or editing recordings (read-only)
- Publishing to PyPI (local install only for now)
- Non-Pixel device support

## Implementation Approach

Seven sequential phases, each building on the last. Playwright network interception is the core innovation — browser.py provides a generic `intercept_response()` helper that recorder.py uses for all operations. The async/sync bridge happens at the CLI layer via `asyncio.run()`.

---

## Phase 1: Project Scaffolding

### Overview
Set up pyproject.toml, directory structure, virtual environment, and install all dependencies including Playwright's Chromium browser.

### Changes Required:

#### 1. pyproject.toml
**File**: `pyproject.toml`
**Changes**: Create project configuration with all dependencies and entry points.

```toml
[project]
name = "google-recorder-cli"
version = "0.1.0"
description = "Unofficial CLI and MCP server for Google Recorder (recorder.google.com)"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "playwright>=1.40.0",
    "click>=8.1.0",
    "fastmcp>=2.0.0",
    "rich>=13.0.0",
]

[project.scripts]
recorder = "recorder_cli.cli:main"
recorder-mcp = "recorder_cli.mcp_server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

#### 2. Package directory structure
**Files**: Create empty `__init__.py` files for the package.

```
recorder_cli/__init__.py
tests/__init__.py
```

### Success Criteria:

#### Automated Verification:
- [ ] `cd /Users/kk/Sites/CodefiLabs/google-recorder-cli && uv venv && uv pip install -e .` completes without error
- [ ] `uv run playwright install chromium` completes
- [ ] `uv run python -c "import recorder_cli"` succeeds
- [ ] `uv run recorder --help` shows help (after cli.py exists — validated in Phase 5)

---

## Phase 2: Data Models

### Overview
Implement the three dataclasses: `Recording`, `TranscriptSegment`, `Transcript`. Pure Python, no external dependencies.

### Changes Required:

#### 1. recorder_cli/models.py
**File**: `recorder_cli/models.py`
**Changes**: Define all data models from the spec.

```python
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Recording:
    id: str
    title: str
    created_at: datetime
    duration_seconds: int
    has_transcript: bool


@dataclass
class TranscriptSegment:
    timestamp_seconds: float
    speaker: str | None
    text: str


@dataclass
class Transcript:
    recording_id: str
    full_text: str
    segments: list[TranscriptSegment] = field(default_factory=list)
```

### Success Criteria:

#### Automated Verification:
- [ ] `uv run python -c "from recorder_cli.models import Recording, Transcript, TranscriptSegment; print('OK')"` succeeds

---

## Phase 3: Browser Module

### Overview
Implement Playwright session lifecycle — login flow with visible browser, persistent context loading, and a generic `intercept_response()` helper for capturing JSON from network requests.

### Changes Required:

#### 1. recorder_cli/browser.py
**File**: `recorder_cli/browser.py`
**Changes**: Full browser module with session management and network interception.

```python
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright, BrowserContext, Page, Response

SESSION_DIR = Path.home() / ".recorder-cli"
SESSION_FILE = SESSION_DIR / "session.json"
RECORDER_URL = "https://recorder.google.com"


async def login() -> None:
    """Open visible browser for Google login, save session."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="chrome")
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(RECORDER_URL)
        # Wait for user to complete login — detect by URL no longer being accounts.google.com
        await page.wait_for_url(f"{RECORDER_URL}/**", timeout=300_000)
        # Give the page a moment to fully load after login
        await page.wait_for_load_state("networkidle")
        await context.storage_state(path=str(SESSION_FILE))
        await browser.close()


def has_session() -> bool:
    """Check if a saved session exists."""
    return SESSION_FILE.exists()


async def _create_context(playwright) -> BrowserContext:
    """Create a browser context with saved session."""
    if not has_session():
        raise RuntimeError("No session found. Run: recorder login")
    browser = await playwright.chromium.launch(headless=True, channel="chrome")
    context = await browser.new_context(storage_state=str(SESSION_FILE))
    return context


async def intercept_response(
    page: Page,
    url_pattern: str,
    trigger_url: str,
    timeout: float = 30_000,
) -> dict:
    """Navigate to trigger_url and capture the first response matching url_pattern."""
    captured = asyncio.Future()

    async def on_response(response: Response) -> None:
        if url_pattern in response.url and not captured.done():
            try:
                data = await response.json()
                captured.set_result(data)
            except Exception:
                pass

    page.on("response", on_response)
    await page.goto(trigger_url)

    try:
        return await asyncio.wait_for(captured, timeout=timeout / 1000)
    except asyncio.TimeoutError:
        raise TimeoutError(
            f"No response matching '{url_pattern}' within {timeout/1000}s. "
            "Session may be expired. Run: recorder login"
        )
    finally:
        page.remove_listener("response", on_response)
```

### Success Criteria:

#### Automated Verification:
- [ ] `uv run python -c "from recorder_cli.browser import login, has_session, intercept_response; print('OK')"` succeeds
- [ ] Module imports without runtime errors

---

## Phase 4: Recorder Client

### Overview
Implement `RecorderClient` — all recorder.google.com operations using the browser module. Since the actual API shape is unknown, parsing uses defensive access with TODO markers for real payload mapping.

### Changes Required:

#### 1. recorder_cli/recorder.py
**File**: `recorder_cli/recorder.py`
**Changes**: RecorderClient class with all operations.

```python
import asyncio
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

from recorder_cli.browser import (
    _create_context,
    intercept_response,
    RECORDER_URL,
)
from recorder_cli.models import Recording, Transcript, TranscriptSegment


class RecorderClient:
    """Client for recorder.google.com operations."""

    async def list_recordings(self) -> list[Recording]:
        """Fetch all recordings."""
        async with async_playwright() as p:
            context = await _create_context(p)
            page = await context.new_page()
            try:
                data = await intercept_response(
                    page,
                    url_pattern="recorder",  # TODO: narrow after discovering real URL pattern
                    trigger_url=RECORDER_URL,
                )
                return self._parse_recordings(data)
            finally:
                await context.close()

    async def get_transcript(self, recording_id: str) -> Transcript:
        """Fetch transcript for a recording."""
        async with async_playwright() as p:
            context = await _create_context(p)
            page = await context.new_page()
            try:
                data = await intercept_response(
                    page,
                    url_pattern="transcript",  # TODO: narrow after discovering real URL pattern
                    trigger_url=f"{RECORDER_URL}/{recording_id}",
                )
                return self._parse_transcript(recording_id, data)
            finally:
                await context.close()

    async def download_audio(self, recording_id: str, output_path: Path) -> Path:
        """Download audio file for a recording."""
        async with async_playwright() as p:
            context = await _create_context(p)
            page = await context.new_page()
            try:
                data = await intercept_response(
                    page,
                    url_pattern="audio",  # TODO: narrow after discovering real URL pattern
                    trigger_url=f"{RECORDER_URL}/{recording_id}",
                )
                # TODO: Extract audio URL from response and download
                # Audio URLs may be signed and expire quickly
                audio_url = data.get("url", "")
                info = await self.get_recording_info(recording_id)
                filename = f"{info.title}.m4a"
                filepath = output_path / filename

                # Use page to download (handles signed URLs/cookies)
                response = await page.request.get(audio_url)
                filepath.parent.mkdir(parents=True, exist_ok=True)
                filepath.write_bytes(await response.body())
                return filepath
            finally:
                await context.close()

    async def get_recording_info(self, recording_id: str) -> Recording:
        """Get metadata for a single recording."""
        recordings = await self.list_recordings()
        for rec in recordings:
            if rec.id == recording_id:
                return rec
        raise ValueError(f"Recording not found: {recording_id}")

    async def search_recordings(self, query: str) -> list[Recording]:
        """Search recordings by keyword in title."""
        recordings = await self.list_recordings()
        query_lower = query.lower()
        return [r for r in recordings if query_lower in r.title.lower()]

    async def sync_all(self, output_path: Path) -> dict:
        """Download all transcripts and audio to output directory."""
        output_path.mkdir(parents=True, exist_ok=True)
        transcripts_dir = output_path / "transcripts"
        audio_dir = output_path / "audio"
        transcripts_dir.mkdir(exist_ok=True)
        audio_dir.mkdir(exist_ok=True)

        recordings = await self.list_recordings()
        results = {"transcripts": [], "audio": [], "errors": []}

        for rec in recordings:
            try:
                if rec.has_transcript:
                    transcript = await self.get_transcript(rec.id)
                    txt_path = transcripts_dir / f"{rec.title}.txt"
                    txt_path.write_text(transcript.full_text)
                    results["transcripts"].append(str(txt_path))
            except Exception as e:
                results["errors"].append(f"Transcript {rec.id}: {e}")

            try:
                audio_path = await self.download_audio(rec.id, audio_dir)
                results["audio"].append(str(audio_path))
            except Exception as e:
                results["errors"].append(f"Audio {rec.id}: {e}")

        return results

    def _parse_recordings(self, data: dict) -> list[Recording]:
        """Parse raw API response into Recording objects.

        TODO: Update parsing once real API payload shape is known.
        """
        recordings = []
        # Defensive: try common patterns for list data
        items = data if isinstance(data, list) else data.get("recordings", data.get("items", []))
        for item in items:
            try:
                recordings.append(Recording(
                    id=str(item.get("id", item.get("recording_id", ""))),
                    title=str(item.get("title", item.get("name", "Untitled"))),
                    created_at=datetime.fromisoformat(
                        item.get("created_at", item.get("create_time", "2000-01-01"))
                    ),
                    duration_seconds=int(item.get("duration_seconds", item.get("duration", 0))),
                    has_transcript=bool(item.get("has_transcript", item.get("transcript_available", False))),
                ))
            except (KeyError, ValueError, TypeError):
                continue
        return recordings

    def _parse_transcript(self, recording_id: str, data: dict) -> Transcript:
        """Parse raw API response into Transcript.

        TODO: Update parsing once real API payload shape is known.
        """
        # Try to extract text and segments from common patterns
        full_text = data.get("text", data.get("transcript", ""))
        raw_segments = data.get("segments", data.get("results", []))
        segments = []
        for seg in raw_segments:
            try:
                segments.append(TranscriptSegment(
                    timestamp_seconds=float(seg.get("timestamp", seg.get("start_time", 0))),
                    speaker=seg.get("speaker", None),
                    text=str(seg.get("text", seg.get("content", ""))),
                ))
            except (KeyError, ValueError, TypeError):
                continue

        if not full_text and segments:
            full_text = "\n".join(s.text for s in segments)

        return Transcript(
            recording_id=recording_id,
            full_text=full_text,
            segments=segments,
        )
```

### Success Criteria:

#### Automated Verification:
- [ ] `uv run python -c "from recorder_cli.recorder import RecorderClient; print('OK')"` succeeds

---

## Phase 5: CLI

### Overview
Implement the Click-based CLI with all subcommands. Each command bridges async RecorderClient calls via `asyncio.run()`. Uses Rich for table output.

### Changes Required:

#### 1. recorder_cli/cli.py
**File**: `recorder_cli/cli.py`
**Changes**: Full Click CLI implementation.

```python
import asyncio
import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from recorder_cli.browser import login as browser_login, has_session
from recorder_cli.recorder import RecorderClient

console = Console()


@click.group()
def main():
    """Unofficial CLI for Google Recorder (recorder.google.com)."""
    pass


@main.command()
def login():
    """Open browser for Google authentication."""
    console.print("Opening browser for Google login...")
    console.print("Sign in to your Google account, then close the browser when done.")
    asyncio.run(browser_login())
    console.print("[green]Session saved successfully.[/green]")


@main.command("list")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table", help="Output format")
@click.option("--id-only", is_flag=True, help="Print only recording IDs")
def list_recordings(fmt, id_only):
    """List all recordings."""
    _check_session()
    client = RecorderClient()
    recordings = asyncio.run(client.list_recordings())

    if id_only:
        for rec in recordings:
            click.echo(rec.id)
        return

    if fmt == "json":
        data = [
            {
                "id": r.id,
                "title": r.title,
                "created_at": r.created_at.isoformat(),
                "duration_seconds": r.duration_seconds,
                "has_transcript": r.has_transcript,
            }
            for r in recordings
        ]
        click.echo(json.dumps(data, indent=2))
        return

    table = Table(title="Recordings")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Date", style="green")
    table.add_column("Duration", style="yellow")
    table.add_column("Transcript", style="magenta")

    for rec in recordings:
        mins, secs = divmod(rec.duration_seconds, 60)
        table.add_row(
            rec.id,
            rec.title,
            rec.created_at.strftime("%Y-%m-%d %H:%M"),
            f"{mins}m {secs}s",
            "Yes" if rec.has_transcript else "No",
        )
    console.print(table)


@main.command()
@click.argument("recording_id")
@click.option("--output", "-o", type=click.Path(), default=".", help="Output directory")
def transcript(recording_id, output):
    """Save transcript as a text file."""
    _check_session()
    client = RecorderClient()
    t = asyncio.run(client.get_transcript(recording_id))
    out_path = Path(output)
    out_path.mkdir(parents=True, exist_ok=True)
    filepath = out_path / f"{recording_id}.txt"
    filepath.write_text(t.full_text)
    console.print(f"[green]Transcript saved to {filepath}[/green]")


@main.command()
@click.argument("recording_id")
@click.option("--output", "-o", type=click.Path(), default=".", help="Output directory")
def download(recording_id, output):
    """Download audio file."""
    _check_session()
    client = RecorderClient()
    filepath = asyncio.run(client.download_audio(recording_id, Path(output)))
    console.print(f"[green]Audio saved to {filepath}[/green]")


@main.command()
@click.argument("recording_id")
def info(recording_id):
    """Show metadata for a recording."""
    _check_session()
    client = RecorderClient()
    rec = asyncio.run(client.get_recording_info(recording_id))
    console.print(f"[bold]ID:[/bold] {rec.id}")
    console.print(f"[bold]Title:[/bold] {rec.title}")
    console.print(f"[bold]Created:[/bold] {rec.created_at.strftime('%Y-%m-%d %H:%M')}")
    mins, secs = divmod(rec.duration_seconds, 60)
    console.print(f"[bold]Duration:[/bold] {mins}m {secs}s")
    console.print(f"[bold]Transcript:[/bold] {'Yes' if rec.has_transcript else 'No'}")


@main.command()
@click.argument("query")
def search(query):
    """Search recordings by keyword."""
    _check_session()
    client = RecorderClient()
    results = asyncio.run(client.search_recordings(query))
    if not results:
        console.print("[yellow]No recordings found.[/yellow]")
        return
    table = Table(title=f"Search: {query}")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Date", style="green")
    for rec in results:
        table.add_row(rec.id, rec.title, rec.created_at.strftime("%Y-%m-%d %H:%M"))
    console.print(table)


@main.command()
@click.option("--output", "-o", type=click.Path(), default="./recorder-backup", help="Output directory")
def sync(output):
    """Bulk download all transcripts and audio."""
    _check_session()
    client = RecorderClient()
    results = asyncio.run(client.sync_all(Path(output)))
    console.print(f"[green]Transcripts saved: {len(results['transcripts'])}[/green]")
    console.print(f"[green]Audio files saved: {len(results['audio'])}[/green]")
    if results["errors"]:
        console.print(f"[red]Errors: {len(results['errors'])}[/red]")
        for err in results["errors"]:
            console.print(f"  [red]- {err}[/red]")


def _check_session():
    """Check for valid session, exit with message if missing."""
    if not has_session():
        console.print("[red]No session found. Run: recorder login[/red]")
        raise SystemExit(1)
```

### Success Criteria:

#### Automated Verification:
- [ ] `uv run recorder --help` shows all commands
- [ ] `uv run recorder list --help` shows --format and --id-only flags
- [ ] `uv run recorder transcript --help` shows recording_id argument and --output flag

---

## Phase 6: MCP Server

### Overview
Implement the FastMCP server exposing all recorder operations as MCP tools. Reuses the same session as the CLI.

### Changes Required:

#### 1. recorder_cli/mcp_server.py
**File**: `recorder_cli/mcp_server.py`
**Changes**: Full FastMCP server implementation.

```python
import asyncio
import json
from pathlib import Path

from fastmcp import FastMCP

from recorder_cli.recorder import RecorderClient

mcp = FastMCP("google-recorder")
client = RecorderClient()


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


def main():
    """Entry point for recorder-mcp command."""
    mcp.run()
```

### Success Criteria:

#### Automated Verification:
- [ ] `uv run python -c "from recorder_cli.mcp_server import mcp; print(mcp.name)"` prints "google-recorder"
- [ ] `uv run recorder-mcp --help` runs without import errors

---

## Phase 7: Tests and README

### Overview
Add unit tests for models and basic import tests for all modules. Write a README with installation and usage instructions.

### Changes Required:

#### 1. tests/test_models.py
**File**: `tests/test_models.py`
**Changes**: Unit tests for data models.

```python
from datetime import datetime
from recorder_cli.models import Recording, Transcript, TranscriptSegment


def test_recording_creation():
    rec = Recording(
        id="rec_123",
        title="Test Recording",
        created_at=datetime(2026, 1, 1),
        duration_seconds=120,
        has_transcript=True,
    )
    assert rec.id == "rec_123"
    assert rec.duration_seconds == 120


def test_transcript_creation():
    seg = TranscriptSegment(timestamp_seconds=0.0, speaker="Alice", text="Hello")
    t = Transcript(recording_id="rec_123", full_text="Hello", segments=[seg])
    assert t.recording_id == "rec_123"
    assert len(t.segments) == 1
    assert t.segments[0].speaker == "Alice"


def test_transcript_default_segments():
    t = Transcript(recording_id="rec_123", full_text="Hello world")
    assert t.segments == []
```

#### 2. tests/test_recorder.py
**File**: `tests/test_recorder.py`
**Changes**: Test parsing methods on RecorderClient.

```python
from datetime import datetime
from recorder_cli.recorder import RecorderClient


def test_parse_recordings_list():
    client = RecorderClient()
    data = [
        {
            "id": "rec_1",
            "title": "Meeting",
            "created_at": "2026-01-01T00:00:00",
            "duration_seconds": 300,
            "has_transcript": True,
        }
    ]
    recordings = client._parse_recordings(data)
    assert len(recordings) == 1
    assert recordings[0].id == "rec_1"
    assert recordings[0].title == "Meeting"


def test_parse_recordings_dict():
    client = RecorderClient()
    data = {"recordings": [
        {"id": "rec_2", "title": "Call", "created_at": "2026-02-01T00:00:00", "duration_seconds": 60, "has_transcript": False}
    ]}
    recordings = client._parse_recordings(data)
    assert len(recordings) == 1
    assert recordings[0].id == "rec_2"


def test_parse_transcript():
    client = RecorderClient()
    data = {
        "text": "Hello world",
        "segments": [
            {"timestamp": 0.0, "speaker": "Bob", "text": "Hello"},
            {"timestamp": 1.5, "text": "world"},
        ],
    }
    t = client._parse_transcript("rec_1", data)
    assert t.full_text == "Hello world"
    assert len(t.segments) == 2
    assert t.segments[0].speaker == "Bob"
    assert t.segments[1].speaker is None


def test_parse_transcript_fallback_text():
    client = RecorderClient()
    data = {
        "segments": [
            {"timestamp": 0.0, "text": "Hello"},
            {"timestamp": 1.0, "text": "there"},
        ],
    }
    t = client._parse_transcript("rec_1", data)
    assert t.full_text == "Hello\nthere"
```

#### 3. tests/test_imports.py
**File**: `tests/test_imports.py`
**Changes**: Verify all modules import cleanly.

```python
def test_import_models():
    from recorder_cli.models import Recording, Transcript, TranscriptSegment

def test_import_browser():
    from recorder_cli.browser import login, has_session, intercept_response

def test_import_recorder():
    from recorder_cli.recorder import RecorderClient

def test_import_cli():
    from recorder_cli.cli import main

def test_import_mcp():
    from recorder_cli.mcp_server import mcp, main
```

#### 4. README.md
**File**: `README.md`
**Changes**: Installation, usage, and MCP server configuration.

#### 5. pyproject.toml test dependency
**File**: `pyproject.toml`
**Changes**: Add pytest as optional dev dependency.

Add to pyproject.toml:
```toml
[project.optional-dependencies]
dev = ["pytest>=7.0.0"]
```

### Success Criteria:

#### Automated Verification:
- [ ] `uv pip install -e ".[dev]"` succeeds
- [ ] `uv run pytest tests/ -v` — all tests pass
- [ ] README.md exists and is non-empty

#### Manual Verification:
- [ ] `recorder login` opens browser, user can sign in (requires Pixel recordings)
- [ ] `recorder list` shows recordings after login
- [ ] `recorder transcript <id>` saves a .txt file

---

## Testing Strategy

### Unit Tests:
- Model dataclass creation and defaults
- RecorderClient parsing methods with mock JSON payloads
- Various JSON shapes (list vs dict wrappers) for robustness

### Import Tests:
- All modules import without error
- Entry points resolve correctly

### Manual Testing:
1. `recorder login` — opens Chrome, sign in, verify session saved to `~/.recorder-cli/session.json`
2. `recorder list` — shows recordings table
3. `recorder list --format json` — outputs valid JSON
4. `recorder transcript <id>` — saves .txt file
5. `recorder-mcp` — starts MCP server without error

## References

- Design spec: `docs/superpowers/specs/2026-04-11-recorder-cli-design.md`
- Research: `docs/research/2026-04-11-recorder-cli-design.md`
- Click+Rich patterns: `docs/research/findings/2026-04-11-recorder-cli/click-rich-patterns.md`
- FastMCP patterns: `docs/research/findings/2026-04-11-recorder-cli/fastmcp-patterns.md`
