# Click + Rich CLI Patterns Research

**Date:** 2026-04-11
**Purpose:** Patterns for building a `recorder` CLI with Click groups/subcommands, Rich table output, async Playwright integration, and pyproject.toml packaging.

---

## 1. Click Group/Command Pattern for Subcommands

### Single-file pattern (recommended for small CLIs)

```python
import click

@click.group()
@click.option('--debug/--no-debug', default=False, help='Enable debug mode')
@click.pass_context
def cli(ctx, debug):
    """Google Recorder CLI tool."""
    ctx.ensure_object(dict)
    ctx.obj['DEBUG'] = debug

@cli.command()
@click.pass_context
def login(ctx):
    """Authenticate with Google Recorder."""
    click.echo("Logging in...")

@cli.command()
@click.pass_context
def list(ctx):
    """List all recordings."""
    click.echo("Listing recordings...")

@cli.command()
@click.argument('recording_id')
@click.pass_context
def transcript(ctx, recording_id):
    """Get transcript for a specific recording."""
    click.echo(f"Fetching transcript for {recording_id}...")

if __name__ == '__main__':
    cli(obj={})
```

Usage:
```
recorder login
recorder list
recorder transcript abc123
```

### Multi-file pattern (for larger CLIs)

```python
# cli.py
import click
from commands import login, list_cmd, transcript

@click.group()
def cli():
    """Google Recorder CLI tool."""
    pass

cli.add_command(login.login)
cli.add_command(list_cmd.list)
cli.add_command(transcript.transcript)
```

```python
# commands/login.py
import click

@click.command()
def login():
    """Authenticate with Google Recorder."""
    click.echo("Logging in...")
```

### Context passing between group and commands

```python
@click.group()
@click.option('--debug/--no-debug', default=False)
@click.pass_context
def cli(ctx, debug):
    ctx.ensure_object(dict)
    ctx.obj['DEBUG'] = debug

@cli.command()
@click.pass_context
def sync(ctx):
    if ctx.obj['DEBUG']:
        click.echo("Debug mode on")
    click.echo("Syncing...")
```

---

## 2. Click Options and Arguments

### Format choice option

```python
@cli.command()
@click.option(
    '--format', '-f', 'output_format',
    type=click.Choice(['table', 'json'], case_sensitive=False),
    default='table',
    help='Output format'
)
def list(output_format):
    if output_format == 'json':
        # raw JSON to stdout for piping
        print(json.dumps(data))
    else:
        # Rich table for terminal display
        print_table(data)
```

Note: the parameter name `output_format` avoids shadowing Python's built-in `format`.

### Output path option

```python
@cli.command()
@click.option(
    '--output', '-o',
    type=click.Path(writable=True),
    default=None,
    help='Write output to file'
)
def transcript(output):
    text = fetch_transcript()
    if output:
        with open(output, 'w') as f:
            f.write(text)
    else:
        click.echo(text)
```

### Boolean flag

```python
@cli.command()
@click.option('--id-only', is_flag=True, help='Print only recording IDs')
def list(id_only):
    recordings = fetch_recordings()
    if id_only:
        for r in recordings:
            click.echo(r['id'])
    else:
        print_table(recordings)
```

### Positional argument

```python
@cli.command()
@click.argument('recording_id')
def transcript(recording_id):
    """Get transcript for RECORDING_ID."""
    ...
```

### Combined example matching the target CLI

```python
@cli.command('list')
@click.option('--format', '-f', 'output_format',
              type=click.Choice(['table', 'json'], case_sensitive=False),
              default='table', help='Output format')
@click.option('--id-only', is_flag=True, help='Print only recording IDs')
@click.pass_context
def list_recordings(ctx, output_format, id_only):
    """List all recordings."""
    recordings = fetch_all()

    if id_only:
        for r in recordings:
            click.echo(r['id'])
        return

    if output_format == 'json':
        import json
        click.echo(json.dumps(recordings, indent=2))
    else:
        _print_recordings_table(recordings)
```

---

## 3. Rich Table Output

### Basic table

```python
from rich.console import Console
from rich.table import Table

console = Console()

def _print_recordings_table(recordings):
    table = Table(title="Recordings")

    table.add_column("ID", justify="left", style="cyan", no_wrap=True)
    table.add_column("Title", justify="left", style="magenta")
    table.add_column("Date", justify="center", style="green")
    table.add_column("Duration", justify="right", style="dim")

    for r in recordings:
        table.add_row(
            r['id'],
            r['title'],
            r['created_at'],
            r.get('duration', '—'),
        )

    console.print(table)
```

### Column options

- `justify`: "left", "center", "right"
- `style`: color names ("cyan", "magenta", "bold red") or hex
- `no_wrap`: prevents line wrapping in that column
- `min_width` / `max_width` / `width`: explicit sizing
- `header_style`: override style for header row only
- `row_styles=["dim", ""]`: zebra-stripe alternating rows

### JSON output with Rich (pretty terminal JSON)

```python
# For pretty JSON in the terminal (colored, indented)
console.print_json(data=recordings)

# For piping to jq or other tools (raw, no color)
import json
print(json.dumps(recordings, indent=2))
```

**Key design rule:** `--format json` should emit raw `json.dumps()` to stdout so it can be piped (`recorder list -f json | jq '.[] | .title'`). Use `console.print_json()` only when you want pretty terminal-only display. The `--format table` path uses Rich; the `--format json` path bypasses Rich entirely.

### Transcript display

```python
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

def _print_transcript(transcript_data):
    console.print(Panel(
        transcript_data['text'],
        title=transcript_data.get('title', 'Transcript'),
        subtitle=transcript_data.get('date', ''),
    ))
```

---

## 4. Running Async Code from Click Commands

Click is synchronous. There are three approaches for async code (like Playwright):

### Approach A: Use Playwright's sync API (RECOMMENDED for CLIs)

The simplest path. Playwright provides a synchronous API that works directly inside Click commands with zero async bridging:

```python
from playwright.sync_api import sync_playwright

@cli.command()
def login():
    """Open browser for Google login."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto("https://recorder.google.com")
        # wait for user to complete login
        page.wait_for_url("**/recorder.google.com/**", timeout=120000)
        cookies = page.context.cookies()
        save_cookies(cookies)
        browser.close()
        click.echo("Logged in successfully.")
```

No decorators, no event loops, no `asyncio.run()`. This is the correct choice for a CLI tool.

### Approach B: asyncio.run() inside a sync Click command

If you need the async Playwright API for some reason:

```python
import asyncio
from playwright.async_api import async_playwright

@cli.command()
def login():
    """Open browser for Google login."""
    asyncio.run(_async_login())

async def _async_login():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto("https://recorder.google.com")
        await page.wait_for_url("**/recorder.google.com/**", timeout=120000)
        cookies = await page.context.cookies()
        save_cookies(cookies)
        await browser.close()
```

### Approach C: make_sync decorator (reusable wrapper)

```python
import functools
import asyncio

def make_sync(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))
    return wrapper

@cli.command()
@make_sync
async def login():
    """Open browser for Google login."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ...
```

### Recommendation

**Use Approach A (sync_playwright)** unless you have a specific reason for async (e.g., concurrent page operations). The sync API avoids all event loop complications, works on all platforms, and keeps Click commands simple.

---

## 5. pyproject.toml Entry Point Configuration

```toml
[build-system]
requires = ["setuptools>=65.5.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "google-recorder-cli"
version = "0.1.0"
description = "CLI for Google Recorder transcripts"
requires-python = ">=3.10"
dependencies = [
    "click>=8.1",
    "rich>=13.0",
    "playwright>=1.40",
]

[project.scripts]
recorder = "recorder_cli.cli:cli"
```

The `[project.scripts]` format is:
```
command-name = "package.module:callable"
```

- `recorder` = the terminal command name
- `recorder_cli.cli` = import path (package `recorder_cli`, module `cli`)
- `cli` = the Click group function to call (must take no arguments)

### Install in development

```bash
pip install -e .
# Now `recorder` command is available
recorder --help
recorder list --format json
recorder transcript abc123 -o output.txt
```

Every time you edit `pyproject.toml` dependencies, re-run `pip install -e .`

### With uv (faster alternative)

```bash
uv pip install -e .
# or for a project with uv.lock
uv sync
```

---

## 6. Single-File CLI Structure (Best Practice)

For a small-to-medium CLI like `recorder`, a single-file structure is cleanest:

```
google-recorder-cli/
  recorder_cli/
    __init__.py
    cli.py          # Click groups, commands, all in one file
    auth.py         # Cookie/token storage helpers
    api.py          # Google Recorder HTTP/scraping logic
    display.py      # Rich table/panel rendering functions
  pyproject.toml
```

### Complete single-file example (`cli.py`)

```python
"""Google Recorder CLI."""
import json
import click
from rich.console import Console
from rich.table import Table

console = Console()

# --- Display helpers ---

def _print_recordings_table(recordings):
    table = Table(title="Recordings")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="magenta")
    table.add_column("Date", justify="center", style="green")
    table.add_column("Duration", justify="right", style="dim")
    for r in recordings:
        table.add_row(r['id'], r['title'], r['date'], r.get('duration', ''))
    console.print(table)

# --- CLI group ---

@click.group()
@click.version_option(version='0.1.0')
@click.pass_context
def cli(ctx):
    """Google Recorder CLI - manage recordings and transcripts."""
    ctx.ensure_object(dict)

# --- Commands ---

@cli.command()
def login():
    """Authenticate with Google Recorder via browser."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto("https://recorder.google.com")
        page.wait_for_url("**/recorder.google.com/**", timeout=120000)
        cookies = page.context.cookies()
        # save_cookies(cookies)
        browser.close()
    click.echo("Login successful.")

@cli.command('list')
@click.option('--format', '-f', 'output_format',
              type=click.Choice(['table', 'json'], case_sensitive=False),
              default='table', help='Output format (table or json)')
@click.option('--id-only', is_flag=True, help='Print only recording IDs')
def list_recordings(output_format, id_only):
    """List all recordings."""
    recordings = []  # fetch_recordings()

    if id_only:
        for r in recordings:
            click.echo(r['id'])
        return

    if output_format == 'json':
        click.echo(json.dumps(recordings, indent=2))
    else:
        _print_recordings_table(recordings)

@cli.command()
@click.argument('recording_id')
@click.option('--output', '-o', type=click.Path(writable=True),
              default=None, help='Write transcript to file')
@click.option('--format', '-f', 'output_format',
              type=click.Choice(['text', 'json'], case_sensitive=False),
              default='text', help='Transcript output format')
def transcript(recording_id, output, output_format):
    """Get transcript for a specific RECORDING_ID."""
    data = {}  # fetch_transcript(recording_id)

    if output_format == 'json':
        result = json.dumps(data, indent=2)
    else:
        result = data.get('text', '')

    if output:
        with open(output, 'w') as f:
            f.write(result)
        click.echo(f"Written to {output}")
    else:
        click.echo(result)
```

### When to split into multiple files

Split when:
- More than ~8 commands
- Commands have complex logic (scraping, auth flows)
- You want to test commands independently

Keep the CLI entry points thin: Click decorators + argument parsing in `cli.py`, business logic in separate modules (`auth.py`, `api.py`, `display.py`).

---

## Sources

- [Click Commands and Groups (official docs)](https://click.palletsprojects.com/en/stable/commands-and-groups/)
- [Click Options (official docs)](https://click.palletsprojects.com/en/stable/options/)
- [Click Entry Points (official docs)](https://click.palletsprojects.com/en/stable/entry-points/)
- [Click Advanced Patterns (official docs)](https://click.palletsprojects.com/en/stable/advanced/)
- [Rich Tables Documentation](https://rich.readthedocs.io/en/stable/tables.html)
- [Rich Console API (print_json)](https://rich.readthedocs.io/en/latest/console.html)
- [Rich GitHub Repository](https://github.com/Textualize/rich)
- [Better Stack: Creating composable CLIs with Click](https://betterstack.com/community/guides/scaling-python/click-explained/)
- [Real Python: Click and Python CLI Apps](https://realpython.com/python-click/)
- [Playwright Python Getting Started](https://playwright.dev/python/docs/library)
- [Click async support discussion (GitHub #2033)](https://github.com/pallets/click/issues/2033)
- [Playwright + Click async issue (GitHub #239)](https://github.com/microsoft/playwright-python/issues/239)
- [Python Packaging: Writing pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [Safir: Using Click for CLI (asyncio integration)](https://safir.lsst.io/user-guide/click.html)
- [Simon Willison: Python packages with pyproject.toml](https://til.simonwillison.net/python/pyproject)
