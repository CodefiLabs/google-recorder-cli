from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright

from recorder_cli.browser import create_context, intercept_response, RECORDER_URL
from recorder_cli.models import Recording, Transcript, TranscriptSegment


class RecorderClient:
    """Client for recorder.google.com operations."""

    async def list_recordings(self) -> list[Recording]:
        """Fetch all recordings."""
        async with async_playwright() as p:
            context = await create_context(p)
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
            context = await create_context(p)
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
            context = await create_context(p)
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
