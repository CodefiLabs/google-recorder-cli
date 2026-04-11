# google-recorder-cli Design Spec

**Date:** 2026-04-11
**Status:** Approved

---

## Overview

`google-recorder-cli` is an unofficial CLI tool and MCP server for [recorder.google.com](https://recorder.google.com) — the Google Pixel Recorder web companion. It allows users to list recordings, copy transcripts as plain text files, download audio files, and access recording metadata programmatically. It mirrors the pattern established by `notebooklm-py` and `notebooklm-mcp-cli` for NotebookLM.

**Repository:** `CodefiLabs/google-recorder-cli` (public)
**Language:** Python
**Approach:** Playwright network interception — Playwright loads recorder.google.com, intercepts structured JSON responses from the page's internal API calls, and parses them into clean data models. No API reverse-engineering required upfront.

---

## Architecture

### Core Principle

All recorder.google.com interaction goes through Playwright. The page is loaded in a persistent browser context; network responses are intercepted to capture structured JSON data (recording list, transcript payloads, audio URLs) rather than scraping the DOM. This makes the tool resilient to UI changes while still capturing clean structured data.

### Components

| Module | Responsibility |
|---|---|
| `recorder_cli/models.py` | Data classes: `Recording`, `Transcript`, `TranscriptSegment` |
| `recorder_cli/browser.py` | Playwright session lifecycle — login flow, persistent context, network interception helper |
| `recorder_cli/recorder.py` | `RecorderClient` — all recorder.google.com operations |
| `recorder_cli/cli.py` | Click-based CLI (`recorder` entrypoint) |
| `recorder_cli/mcp_server.py` | FastMCP server (`recorder-mcp` entrypoint) |

### Data Flow

```
recorder list
  → RecorderClient.list_recordings()
    → Playwright loads recorder.google.com with saved session
    → network interception captures JSON response with recording list
    → parsed into list[Recording]
  → CLI renders as rich table (or JSON if --format json)
```

```
recorder transcript <id>
  → RecorderClient.get_transcript(id)
    → Playwright navigates to recording
    → network interception captures transcript JSON payload
    → parsed into Transcript, written as plain .txt file
```

---

## Authentication

**Session storage:** `~/.recorder-cli/session.json` — Playwright `storage_state` format (cookies + localStorage).

**Login flow:**
1. User runs `recorder login`
2. Visible Chromium window opens (not headless)
3. User signs into Google account normally (handles 2FA, security prompts, etc.)
4. Playwright saves storage state to `~/.recorder-cli/session.json`
5. All subsequent commands load this session — no browser window shown

**Session lifetime:** Google sessions last several weeks. When a command detects an expired session (redirect to login page), it prints a clear error: `Session expired. Run: recorder login`

---

## Data Models

```python
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
    full_text: str                    # plain text, newline-separated segments
    segments: list[TranscriptSegment] # with timestamps/speakers if available
```

---

## CLI Commands

**Entry point:** `recorder`

| Command | Description |
|---|---|
| `recorder login` | Opens browser for Google auth, saves session |
| `recorder list` | Table of all recordings: ID, title, date, duration |
| `recorder transcript <id>` | Saves transcript as `<title>.txt` |
| `recorder download <id>` | Downloads audio as `<title>.m4a` |
| `recorder info <id>` | Prints metadata for one recording |
| `recorder search <query>` | Lists recordings matching a keyword |
| `recorder sync` | Bulk: saves all transcripts + audio to output dir |

**Shared flags:**
- `--output / -o <path>` — output path for `transcript`, `download`, `sync`
- `--format table|json` — output format for `list` (default: table)
- `--id-only` — print only IDs, for scripting (on `list`)

**Example usage:**
```bash
recorder login
recorder list
recorder list --format json
recorder transcript rec_abc123 -o ~/transcripts/
recorder download rec_abc123 -o ~/audio/
recorder info rec_abc123
recorder sync -o ~/recorder-backup/
```

---

## MCP Server

**Entry point:** `recorder-mcp`
**Framework:** FastMCP

Reuses the same `~/.recorder-cli/session.json` as the CLI — no separate auth.

**Tools:**

| Tool | Arguments | Returns |
|---|---|---|
| `list_recordings` | none | JSON array: `[{id, title, date, duration_seconds}]` |
| `get_transcript` | `recording_id: str` | Plain text transcript string |
| `download_audio` | `recording_id: str, output_path: str` | Absolute path to saved `.m4a` |
| `get_recording_info` | `recording_id: str` | JSON object with full metadata |
| `search_recordings` | `query: str` | Filtered recording list |

**Claude Desktop config:**
```json
{
  "mcpServers": {
    "google-recorder": {
      "command": "recorder-mcp"
    }
  }
}
```

---

## Project Structure

```
google-recorder-cli/
├── pyproject.toml
├── README.md
├── recorder_cli/
│   ├── __init__.py
│   ├── models.py
│   ├── browser.py
│   ├── recorder.py
│   ├── cli.py
│   └── mcp_server.py
└── tests/
    └── test_recorder.py
```

---

## Packaging & Installation

**Dependencies:**
- `playwright` — browser automation + network interception
- `click` — CLI framework
- `fastmcp` — MCP server
- `rich` — table/pretty terminal output

**Entry points (`pyproject.toml`):**
```toml
[project.scripts]
recorder = "recorder_cli.cli:main"
recorder-mcp = "recorder_cli.mcp_server:main"
```

**Install:**
```bash
pip install google-recorder-cli
playwright install chromium  # one-time
```

---

## Key Risks

1. **API shape unknown** — recorder.google.com's internal JSON payloads have not been reverse-engineered yet. Network interception will reveal the shape during initial development; payloads may change with Google updates.
2. **Audio download path** — signed audio URLs may expire quickly or require specific headers. May need to pipe through Playwright's download handler rather than direct URL fetching.
3. **Pixel-only requirement** — recorder.google.com requires recordings made on a Google Pixel device with backup enabled. The tool cannot create recordings, only access existing ones.
4. **Headless detection** — Google may detect headless Playwright. Using a persistent context with `channel="chrome"` (real Chrome install) mitigates this.

---

## Out of Scope

- Creating or editing recordings (read-only tool)
- Non-Pixel device support
- Transcript editing
- Sharing/permissions management
