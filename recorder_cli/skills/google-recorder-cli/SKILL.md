---
name: google-recorder-cli
description: Unofficial CLI for Google Recorder (recorder.google.com), the Pixel phone's voice recorder web companion. Use when the user asks to list or browse their Google/Pixel Recorder recordings, fetch or save a transcript, download a recording's audio, look up metadata for a specific recording, search recordings by title, or bulk-sync/back up all recordings. Triggers on phrases like "list my recordings", "get the transcript for that recording", "download the audio from recorder.google.com", "search my Pixel recordings for X", "back up my voice recorder recordings", or any task referencing recorder.google.com, Google Recorder, or Pixel Recorder data. Requires a one-time local browser login before any command works — check the Prerequisite section before running commands.
---

# Google Recorder CLI

## Overview

Wraps the `recorder` CLI (installed from the `CodefiLabs/google-recorder-cli` GitHub repo) to list, search, and pull transcripts/audio from recorder.google.com. Read-only — cannot create, edit, or delete recordings.

## Prerequisite: authenticated session (check this before running anything but `login`)

This is the part that breaks silently if skipped, so verify it first.

1. **`recorder` is installed and on PATH.** Check with `which recorder`. If missing, install it straight from GitHub — no local clone needed:
   ```
   pipx install git+https://github.com/CodefiLabs/google-recorder-cli.git
   ```
   (`pip install --user git+https://github.com/CodefiLabs/google-recorder-cli.git` works too if `pipx` isn't available.) If the install itself fails — no network access, no `pip`/`pipx` on this machine — tell the user rather than trying to reconstruct the tool from scratch. It also needs real Google Chrome installed (Playwright launches it via `channel="chrome"`, not Playwright's bundled Chromium — `playwright install chromium` alone is not sufficient).

2. **A logged-in session exists at `~/.recorder-cli/chrome-profile/`.** This is a full persistent Chrome profile Playwright reuses headlessly for every command — not an API token, and not the `~/.recorder-cli/session.json` file (that file is an unused stub; ignore it). Check with:
   ```
   test -d ~/.recorder-cli/chrome-profile && [ "$(ls -A ~/.recorder-cli/chrome-profile 2>/dev/null)" ] && echo present
   ```
   If it's missing, or any command fails with `No session found. Run: recorder login`:
   - `recorder login` opens a **real, visible Chrome window** and blocks waiting for the user to sign in and press Enter in the terminal. It requires an interactive display and cannot run headless, remotely, or in a sandboxed environment with no GUI.
   - **If this environment has no display and no session exists, stop and tell the user** — don't attempt a workaround (no headless login, no cookie injection; the tool's anti-bot-detection approach specifically depends on a real interactive `launch_persistent_context` session). Ask them to run `recorder login` locally on a machine with Chrome, or to confirm the profile is already available here.
   - A session typically lasts several weeks before it needs to be redone.

## Commands

Everything below except `login` requires the session above and only reads data (no writes to the user's account).

### `recorder list`
```
recorder list                  # table: ID, Title, Date, Duration, Transcript (Yes/No)
recorder list --format json    # JSON array: id, title, created_at, duration_seconds, has_transcript
recorder list --id-only        # bare IDs, one per line — for piping into other commands
```

### `recorder transcript <id>`
Saves the transcript as `<output>/<id>.txt`.
```
recorder transcript <id> -o ~/docs/     # -o defaults to "."
```
Fails if the recording has no transcript yet (`has_transcript: false` in `list` output) — check that first. **Can also silently return a truncated transcript on longer recordings — see Gotchas.**

### `recorder download <id>`
Saves audio as `<output>/<sanitized title>.m4a` (named by title, not id).
```
recorder download <id> -o ~/audio/      # -o defaults to "."
```

### `recorder info <id>`
Prints ID, Title, Created date, Duration, and whether a transcript exists, for one recording.

### `recorder search <query>`
Case-insensitive substring match against recording **titles only** (does not search transcript text). Prints a table or "No recordings found."

### `recorder sync`
Bulk export: every available transcript into `<output>/transcripts/`, every audio file into `<output>/audio/`. Continues past individual failures and reports them at the end instead of aborting.
```
recorder sync -o ~/recorder-backup/     # -o defaults to "./recorder-backup"
```

## Gotchas

**`get_transcript` (MCP) and `recorder transcript` (CLI) can silently return a truncated transcript.** Both pull Google Recorder's on-device live transcript — generated in real time on the Pixel while recording, optimized for speed over completeness. On longer recordings it can lose confidence partway through and stop, dropping everything after with no error, warning, or a "partial" flag — the output just looks like a complete, short transcript.

Tell by comparing transcript length to `duration_seconds` (from `list`/`info`): normal speech runs ~2 words/sec, so a transcript running far short of `duration_seconds × 2` words is suspect. (Observed case: a 184s recording, 17-word transcript — about 1 word per 11s.) Skip the check on short recordings (a few seconds, a handful of words) — the live transcript is fine there.

**Fix:** `recorder download <id>` for the raw `.m4a`, then transcribe it locally with a real STT model (e.g. `mlx_whisper`, `large-v3-turbo`) instead of trusting the on-device transcript. This bypasses the live transcript entirely and gets the full content.

## Errors you may see

| Message | Meaning | Fix |
|---|---|---|
| `No session found. Run: recorder login` | No Chrome profile saved at all | Run `recorder login` locally (see Prerequisite) |
| `Recorder did not load. Session may be expired. Run: recorder login` | Profile exists but Google rejected it (30s timeout waiting for the recording list) | Re-run `recorder login` |
| `Recording not found: <id>` | That ID isn't in the account's current recording list | Re-check the ID via `recorder list` |
| `Transcript not available for <id>...` | That recording has no transcript | Not fixable — it just doesn't have one |

## MCP server

`recorder-mcp` exposes the same five operations (`list_recordings`, `get_transcript`, `download_audio`, `get_recording_info`, `search_recordings`) as MCP tools. It has the identical session/Chrome prerequisite as the CLI.

**Client registration (stdio, local client):**
```
recorder mcp install claude-desktop     # patches claude_desktop_config.json (backs up first, then restart the app)
recorder mcp install claude-code        # delegates to `claude mcp add -s user`; new sessions pick it up
recorder mcp uninstall <client>         # reverses either registration
recorder mcp status                     # registration state for both clients, flags stale binary paths
```
All idempotent — re-running detects existing state and no-ops (including replacing a stale registration that points at an old binary path after a reinstall).

**HTTP mode (for a remote/network client, e.g. a cloud sandbox with no local shell access to this Mac):**
```
recorder mcp serve --transport http --host 127.0.0.1 --port 8420   # recorder-mcp binary takes the same flags
```
Requires `Authorization: Bearer <token>` on every request (verified: 401 with no/wrong token, 200 with the right one). The token is generated on first run and stored at `~/.recorder-cli/mcp_token` (0600) — it is never printed to output; read the file when configuring a client. Binds to loopback only, so it's not reachable from outside this Mac until fronted by something else (e.g. a tunnel) — that exposure step is a deliberate, separate decision each time, not something to automate silently, since it puts a real network endpoint in front of the user's private recordings. Don't stand up a tunnel without explicit user confirmation of the specific exposure.
