# FastMCP Patterns for Google Recorder MCP Server

Research date: 2026-04-11

## 1. Package Choice: `fastmcp` (standalone) vs `mcp` SDK

There are two import paths that look similar but are different packages:

- **Standalone `fastmcp` package** (actively maintained, ~1M downloads/day):
  ```
  pip install fastmcp
  from fastmcp import FastMCP
  ```

- **Bundled version inside the official `mcp` SDK** (older API surface):
  ```
  pip install "mcp[cli]"
  from mcp.server.fastmcp import FastMCP
  ```

**Use the standalone `fastmcp` package.** It is FastMCP 3.x, actively maintained by Prefect/jlowin, and is the canonical version. The bundled version inside `mcp` SDK is an older snapshot (FastMCP 1.x era). The standalone package has the full feature set documented at https://gofastmcp.com.

Install: `pip install fastmcp` or `uv add fastmcp`
Requires: Python >= 3.10

---

## 2. Basic Server Setup

```python
from fastmcp import FastMCP

mcp = FastMCP("google-recorder")

@mcp.tool
def list_recordings() -> list[dict]:
    """List all recordings from Google Recorder."""
    # implementation
    return [{"id": "abc", "title": "Meeting notes"}]

if __name__ == "__main__":
    mcp.run()
```

Key points:
- The `FastMCP("name")` constructor takes a server name string
- `mcp.run()` defaults to **stdio transport** (what Claude Desktop expects)
- The `if __name__ == "__main__"` block is recommended for compatibility with all MCP clients
- FastMCP CLI (`fastmcp run server.py`) bypasses `__main__` and imports the server object directly -- it auto-discovers objects named `mcp`, `server`, or `app`

---

## 3. Defining Tools with `@mcp.tool`

### Basic decorator usage

```python
@mcp.tool
def search_recordings(query: str, max_results: int = 10) -> list[dict]:
    """Search recordings by keyword."""
    return []
```

FastMCP automatically:
- Uses the **function name** as the tool identifier
- Extracts the **docstring** as the tool description
- Generates **input schema** from type annotations
- Validates inputs before execution

**Important**: Use `@mcp.tool` (no parentheses needed for defaults). Using `@mcp.tool()` with parentheses also works and is required when passing decorator arguments.

### Decorator arguments

```python
@mcp.tool(
    name="find_recording",           # Override tool name
    description="Search recordings", # Override docstring
    tags={"recordings", "search"},   # Categorization
    timeout=30.0,                    # Execution timeout (seconds)
    annotations={
        "readOnlyHint": True,        # Tells client: no side effects
        "idempotentHint": True,      # Safe to retry
        "openWorldHint": False,      # No external system interaction
    }
)
def search_recordings_impl(query: str) -> list[dict]:
    ...
```

### Annotations (behavior hints for clients)

| Annotation | Meaning |
|---|---|
| `readOnlyHint` | Tool only reads data (no modifications) |
| `destructiveHint` | Changes are irreversible |
| `idempotentHint` | Repeated calls with same args produce same effect |
| `openWorldHint` | Interacts with external systems |
| `title` | Display name for UIs |

---

## 4. Tool Argument Types and Return Types

### Supported argument types

```python
from typing import Annotated, Literal
from pydantic import Field

@mcp.tool
def process_recording(
    recording_id: str,                                    # Required string
    format: Literal["txt", "json", "srt"] = "txt",       # Constrained values
    include_timestamps: bool = True,                      # Optional boolean
    max_length: Annotated[int, Field(ge=1, le=50000)] = 10000,  # Validated int
    tags: list[str] | None = None,                        # Optional list
) -> dict:
    """Process a recording transcript."""
    return {"id": recording_id, "status": "processed"}
```

Supported categories:
- **Basics**: `int`, `float`, `str`, `bool`
- **Collections**: `list[T]`, `dict[K, V]`, `set[T]`
- **Constraints**: `Literal[...]`, `Enum`
- **Temporal**: `datetime`, `date`, `timedelta`
- **Special**: `UUID`, `Path`, `bytes`
- **Objects**: Pydantic models, dataclasses

### Parameter metadata with Annotated

```python
@mcp.tool
def get_transcript(
    recording_id: Annotated[str, "The unique ID of the recording"],
    language: Annotated[str, "ISO 639-1 language code"] = "en",
) -> str:
    ...
```

Shorthand string annotations become the parameter description. Use `Field(description=..., ge=..., le=...)` for validation constraints.

### Parameters without defaults are required; with defaults are optional.

### Return type mapping

| Python Return Type | MCP Content |
|---|---|
| `str` | Text content |
| `int` / `float` | Wrapped as `{"result": value}` |
| `dict` / Pydantic model | Structured JSON content |
| `bytes` | Base64-encoded blob |
| `None` | Empty response |
| `list[dict]` | Structured content |

### Constraints

- Every parameter **must** have a type annotation
- `*args` and `**kwargs` are **not supported** -- MCP requires complete parameter schemas
- Functions returning complex types should use dataclasses or Pydantic models

---

## 5. Async Tool Functions

### Sync vs async

```python
@mcp.tool
def sync_tool(recording_id: str) -> dict:
    """Sync tools run in a thread pool automatically."""
    # blocking I/O is OK here -- FastMCP wraps it
    result = subprocess.run(["recorder-cli", "get", recording_id], capture_output=True)
    return {"transcript": result.stdout.decode()}

@mcp.tool
async def async_tool(recording_id: str) -> dict:
    """Async tools run on the event loop -- preferred for I/O."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.example.com/{recording_id}") as resp:
            return await resp.json()
```

**Best practices:**
- Use `async def` for any tool doing network I/O, database queries, or file reads
- Sync tools are automatically run in a thread pool (won't block the event loop) but are less efficient
- A blocking sync function that doesn't use the thread pool correctly can freeze the entire MCP server
- For the recorder CLI (which shells out to `subprocess`), sync is acceptable since FastMCP wraps it in a thread pool

### Context object for logging and progress

```python
from fastmcp import FastMCP, Context

@mcp.tool
async def export_recording(recording_id: str, ctx: Context) -> dict:
    """Export a recording with progress updates."""
    await ctx.info(f"Starting export for {recording_id}")
    
    await ctx.report_progress(progress=0, total=100)
    # ... do work ...
    await ctx.report_progress(progress=50, total=100)
    # ... more work ...
    await ctx.report_progress(progress=100, total=100)
    
    return {"status": "exported"}
```

Context methods:
- `ctx.debug()`, `ctx.info()`, `ctx.warning()`, `ctx.error()` -- logging
- `ctx.report_progress(progress, total)` -- progress tracking
- `ctx.read_resource(uri)` -- read MCP resources
- `ctx.sample(...)` -- request LLM help from the client
- `ctx.request_id`, `ctx.client_id` -- request metadata

The `ctx: Context` parameter is automatically injected by FastMCP and hidden from the tool schema (the LLM never sees it).

### Error handling

```python
from fastmcp.exceptions import ToolError

@mcp.tool
def get_recording(recording_id: str) -> dict:
    """Get a recording by ID."""
    if not recording_id:
        raise ToolError("Recording ID is required.")  # Always shown to client
    
    try:
        result = fetch_recording(recording_id)
    except FileNotFoundError:
        raise ToolError(f"Recording '{recording_id}' not found.")
    except Exception as e:
        # With mask_error_details=True, this becomes a generic error
        raise
    
    return result
```

Server-level error masking:
```python
mcp = FastMCP("google-recorder", mask_error_details=True)
# Only ToolError messages shown; other exceptions become generic
```

### Timeouts

```python
@mcp.tool(timeout=60.0)
async def long_export(recording_id: str) -> dict:
    """Export with 60-second timeout."""
    ...
```

---

## 6. CLI Entry Point and Claude Desktop Configuration

### The full chain: pyproject.toml -> pip install -> Claude Desktop

**Step 1: Define the entry point in pyproject.toml**

```toml
[project]
name = "google-recorder-cli"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "fastmcp",
    "click",       # if using click for the main CLI
]

[project.scripts]
recorder-mcp = "google_recorder_cli.mcp_server:main"
```

This follows the same pattern as the official `mcp-server-fetch` package:
```toml
# mcp-server-fetch's pyproject.toml for reference:
[project.scripts]
mcp-server-fetch = "mcp_server_fetch:main"
```

**Step 2: Create the main() function**

```python
# google_recorder_cli/mcp_server.py

from fastmcp import FastMCP

mcp = FastMCP("google-recorder")

@mcp.tool
def list_recordings() -> list[dict]:
    """List all recordings from Google Recorder."""
    ...

@mcp.tool
def get_transcript(recording_id: str) -> str:
    """Get the transcript for a specific recording."""
    ...

@mcp.tool
def search_recordings(query: str, max_results: int = 10) -> list[dict]:
    """Search recordings by keyword."""
    ...

def main():
    """Entry point for the MCP server (stdio transport)."""
    mcp.run()

if __name__ == "__main__":
    main()
```

**Step 3: Install the package**

```bash
# Development install (editable):
pip install -e .
# or with uv:
uv pip install -e .
```

After installation, `recorder-mcp` is on PATH as a command.

**Step 4: Configure Claude Desktop**

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "google-recorder": {
      "command": "recorder-mcp"
    }
  }
}
```

That's it. No `uv run` wrapper needed when the package is pip-installed into the active environment. The `recorder-mcp` command calls `main()` which calls `mcp.run()` with stdio transport.

**Alternative: Without pip install (using uv run)**

If not pip-installed, use `uv run` to create an isolated environment:

```json
{
  "mcpServers": {
    "google-recorder": {
      "command": "uv",
      "args": [
        "run",
        "--with", "fastmcp",
        "--with", "google-recorder-cli",
        "recorder-mcp"
      ]
    }
  }
}
```

**Alternative: Direct script execution**

```json
{
  "mcpServers": {
    "google-recorder": {
      "command": "python",
      "args": ["/absolute/path/to/google_recorder_cli/mcp_server.py"]
    }
  }
}
```

### Environment variables

If the server needs env vars (e.g., API keys, config paths):

```json
{
  "mcpServers": {
    "google-recorder": {
      "command": "recorder-mcp",
      "env": {
        "RECORDER_DATA_DIR": "/Users/kk/.recorder",
        "DEBUG": "true"
      }
    }
  }
}
```

**Critical**: Claude Desktop runs servers in a completely isolated environment with no access to your shell environment. You must explicitly pass any environment variables your server needs.

### Using FastMCP CLI to auto-install

```bash
fastmcp install claude-desktop mcp_server.py
# Optionally with deps:
fastmcp install claude-desktop mcp_server.py --with pandas --with requests
```

This auto-generates the `claude_desktop_config.json` entry. Restart Claude Desktop after.

### Verification

After configuration, restart Claude Desktop completely. A hammer icon in the bottom-left of the input box confirms MCP tools are active.

### Testing with MCP Inspector

```bash
fastmcp dev mcp_server.py
# Opens browser at http://127.0.0.1:6274 for interactive testing
```

---

## 7. Dependency Injection (Hiding Internal State)

Use `Depends()` to inject values that the LLM should not see:

```python
from fastmcp.dependencies import Depends

def get_db_connection():
    return sqlite3.connect("/path/to/recordings.db")

@mcp.tool
def list_recordings(db = Depends(get_db_connection)) -> list[dict]:
    """List all recordings."""
    cursor = db.execute("SELECT * FROM recordings")
    return [dict(row) for row in cursor.fetchall()]
```

The `db` parameter is injected at runtime and excluded from the tool schema.

---

## 8. Validation Modes

```python
# Default: flexible (coerces "10" -> 10)
mcp = FastMCP("google-recorder")

# Strict: rejects type mismatches
mcp = FastMCP("google-recorder", strict_input_validation=True)
```

---

## 9. Full Example: Recorder MCP Server Skeleton

```python
"""Google Recorder MCP Server.

Exposes Google Recorder operations as MCP tools for use with
Claude Desktop and other MCP-compatible clients.
"""

from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from typing import Annotated
from pydantic import Field

mcp = FastMCP(
    "google-recorder",
    mask_error_details=False,  # Show full errors during development
)


@mcp.tool(annotations={"readOnlyHint": True})
def list_recordings(
    limit: Annotated[int, Field(description="Max recordings to return", ge=1, le=100)] = 20,
) -> list[dict]:
    """List recordings from Google Recorder, most recent first."""
    # TODO: implement via recorder CLI or direct file access
    raise ToolError("Not yet implemented")


@mcp.tool(annotations={"readOnlyHint": True})
def get_transcript(
    recording_id: Annotated[str, "The unique ID of the recording"],
) -> str:
    """Get the full transcript text for a specific recording."""
    raise ToolError("Not yet implemented")


@mcp.tool(annotations={"readOnlyHint": True})
def search_recordings(
    query: Annotated[str, "Search query to match against recording content"],
    max_results: Annotated[int, Field(ge=1, le=50)] = 10,
) -> list[dict]:
    """Search recordings by keyword across titles and transcripts."""
    raise ToolError("Not yet implemented")


@mcp.tool(annotations={"readOnlyHint": True})
async def get_recording_details(
    recording_id: Annotated[str, "The unique ID of the recording"],
    ctx: Context = None,
) -> dict:
    """Get full metadata and transcript for a recording."""
    if ctx:
        await ctx.info(f"Fetching details for {recording_id}")
    raise ToolError("Not yet implemented")


def main():
    """Entry point for the recorder-mcp command."""
    mcp.run()


if __name__ == "__main__":
    main()
```

---

## Sources

- [FastMCP Tools Documentation](https://gofastmcp.com/servers/tools)
- [FastMCP Quickstart](https://gofastmcp.com/getting-started/quickstart)
- [FastMCP Claude Desktop Integration](https://gofastmcp.com/integrations/claude-desktop)
- [FastMCP MCP JSON Configuration](https://gofastmcp.com/integrations/mcp-json-configuration)
- [FastMCP GitHub Repository](https://github.com/jlowin/fastmcp)
- [FastMCP PyPI](https://pypi.org/project/fastmcp/)
- [MCP Python SDK GitHub](https://github.com/modelcontextprotocol/python-sdk)
- [Official MCP Build Server Guide](https://modelcontextprotocol.io/docs/develop/build-server)
- [mcp-server-fetch pyproject.toml (console_scripts example)](https://glama.ai/mcp/servers/@ExactDoug/mcp-fetch/blob/master/pyproject.toml)
- [FastMCP Tutorial - Firecrawl](https://www.firecrawl.dev/blog/fastmcp-tutorial-building-mcp-servers-python)
- [FastMCP Tutorial - MCPcat](https://mcpcat.io/guides/building-mcp-server-python-fastmcp/)
