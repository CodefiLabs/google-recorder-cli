# google-recorder-cli

Unofficial CLI and MCP server for [Google Recorder](https://recorder.google.com) — the Google Pixel Recorder web companion.

List recordings, copy transcripts, download audio, and access recording metadata from the command line or through an MCP server for AI assistants.

## Requirements

- Python 3.10+
- Google Pixel device with Recorder backup enabled
- Chrome browser installed

## Installation

```bash
pipx install .   # or: pip install -e .
```

Requires Google Chrome — the tool drives your real Chrome (via Playwright's `channel="chrome"`), so `playwright install chromium` is not needed and not sufficient.

## Usage

### Authentication

```bash
recorder login
```

Opens a Chrome window. Sign into your Google account. The session is saved as a browser profile under `~/.recorder-cli/chrome-profile/` and persists for several weeks.

### CLI Commands

```bash
recorder list                          # Table of all recordings
recorder list --format json            # JSON output
recorder list --id-only                # Just IDs (for scripting)
recorder transcript <id> -o ~/docs/    # Save transcript as .txt
recorder download <id> -o ~/audio/     # Download audio as .m4a
recorder info <id>                     # Print recording metadata
recorder search <query>                # Search by keyword
recorder sync -o ~/recorder-backup/    # Bulk download everything
```

### MCP Server

Register with a local client (idempotent; `uninstall` reverses it):

```bash
recorder mcp install claude-desktop   # patches claude_desktop_config.json, backs up first
recorder mcp install claude-code      # delegates to `claude mcp add` (user scope)
recorder mcp status                   # show registration state for both clients
```

Registrations point at the `recorder-mcp` binary, which speaks stdio by default. To serve over the network instead (bearer-token auth, loopback bind — exposing it beyond that is deliberately left to you):

```bash
recorder mcp serve --transport http --port 8420
# token is generated once and stored at ~/.recorder-cli/mcp_token (never printed)
```

**Tools:** `list_recordings`, `get_transcript`, `download_audio`, `get_recording_info`, `search_recordings`

### Claude Code Skill

Installs a `SKILL.md` at `~/.claude/skills/google-recorder-cli/` so Claude Code knows when and how to use this CLI — the login prerequisite, command reference, and gotchas like silently truncated live transcripts.

```bash
recorder skill install     # idempotent; backs up a locally-edited copy before overwriting
recorder skill status      # installed / not installed / differs from the bundled version
recorder skill uninstall   # idempotent
```

## How It Works

Uses Playwright to load recorder.google.com and intercept JSON responses from the page's internal API calls. No API reverse-engineering required — the tool captures structured data directly from network traffic.

## Transcript Format

Transcripts include speaker labels (e.g. `[Speaker 1]`, `[Speaker 2]`) and are fetched from Google's official download endpoint — the same source as the web UI's "Download" button. This ensures complete transcripts even for long recordings, rather than truncated live captions.

## Limitations

- Read-only — cannot create or edit recordings
- Requires recordings from a Google Pixel device with backup enabled
- Google session may expire after several weeks (re-run `recorder login`)
