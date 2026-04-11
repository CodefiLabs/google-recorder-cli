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
