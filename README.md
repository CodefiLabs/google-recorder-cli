# google-recorder-cli

Unofficial CLI and MCP server for [Google Recorder](https://recorder.google.com) — the Google Pixel Recorder web companion.

List recordings, copy transcripts, download audio, and access recording metadata from the command line or through an MCP server for AI assistants.

## Requirements

- Python 3.10+
- Google Pixel device with Recorder backup enabled
- Chrome browser installed

## Installation

```bash
pip install -e .
playwright install chromium
```

## Usage

### Authentication

```bash
recorder login
```

Opens a Chrome window. Sign into your Google account. The session is saved to `~/.recorder-cli/session.json` and persists for several weeks.

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

```bash
recorder-mcp
```

Configure in Claude Desktop:

```json
{
  "mcpServers": {
    "google-recorder": {
      "command": "recorder-mcp"
    }
  }
}
```

**Tools:** `list_recordings`, `get_transcript`, `download_audio`, `get_recording_info`, `search_recordings`

## How It Works

Uses Playwright to load recorder.google.com and intercept JSON responses from the page's internal API calls. No API reverse-engineering required — the tool captures structured data directly from network traffic.

## Limitations

- Read-only — cannot create or edit recordings
- Requires recordings from a Google Pixel device with backup enabled
- Google session may expire after several weeks (re-run `recorder login`)
