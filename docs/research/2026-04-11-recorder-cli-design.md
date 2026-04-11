# Research: google-recorder-cli Design

**Date**: 2026-04-11T14:39:14Z
**Git Commit**: 39a8728
**Branch**: main

## Summary

`google-recorder-cli` is a greenfield Python CLI + MCP server for recorder.google.com. The design spec (`docs/superpowers/specs/2026-04-11-recorder-cli-design.md`) is the authoritative source — no existing code to research.

## Key Technical Decisions

### 1. Playwright Network Interception (not httpx)
The spec calls for all interaction through Playwright — load the page, intercept JSON responses from internal API calls. This differs from `notebooklm-py` (teng-lin/notebooklm-py) which uses Playwright only for auth then switches to httpx for API calls. Our approach is more resilient to API changes but means everything runs through the browser.

### 2. Async/Sync Bridge
Playwright is async; Click is sync. Each Click command should call `asyncio.run(async_impl())`. The RecorderClient and browser module should be fully async internally.

### 3. Unknown API Shape
recorder.google.com's JSON payloads are not yet reverse-engineered. The browser module needs a generic `intercept_response(url_pattern) -> dict` helper. Parsing in recorder.py should use defensive access with sensible defaults until real payloads are captured.

### 4. Session Persistence
Playwright `storage_state` saved to `~/.recorder-cli/session.json`. Google sessions last weeks. Detect expiry by checking for login page redirect.

## Reference Pattern: notebooklm-py
- Uses Playwright for Google auth with persistent context
- Saves cookies via `storage_state()`
- Uses httpx (not Playwright) for subsequent API calls
- Our project uses Playwright for everything — simpler, one dependency for all network ops

## Research Findings
- `docs/research/findings/2026-04-11-recorder-cli/click-rich-patterns.md` — Click CLI + Rich table patterns
- `docs/research/findings/2026-04-11-recorder-cli/fastmcp-patterns.md` — FastMCP server patterns
