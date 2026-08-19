import asyncio
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

from recorder_cli.browser import create_context, RECORDER_URL
from recorder_cli.models import Recording, Transcript, TranscriptSegment

_GRPC_BASE = (
    "https://pixelrecorder-pa.clients6.google.com"
    "/$rpc/java.com.google.wireless.android.pixel.recorder.protos.PlaybackService"
)
_AUDIO_BASE = "https://usercontent.recorder.google.com/download/playback"


def _intercept_grpc(page, endpoint: str, wait_for_largest: bool = False) -> asyncio.Future:
    """
    Register a response interceptor for a gRPC endpoint.
    
    Args:
        page: Playwright page object
        endpoint: Endpoint name to match (e.g., "GetTranscription")
        wait_for_largest: If True, collect all responses and return the largest one
                         (useful for GetTranscription which may send small then large payloads)
    
    Returns a Future that resolves with the parsed JSON body.
    The listener is automatically removed once the future resolves.
    """
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()

    if not wait_for_largest:
        # Original one-shot behavior: return first response
        def on_response(response: object) -> None:
            if endpoint in response.url and not future.done():  # type: ignore[attr-defined]
                async def _read() -> None:
                    try:
                        data = await response.json()  # type: ignore[attr-defined]
                        if not future.done():
                            future.set_result(data)
                    except Exception:
                        pass
                asyncio.ensure_future(_read())

        page.on("response", on_response)
        future.add_done_callback(lambda _: page.remove_listener("response", on_response))
    else:
        # Collect all responses and return the largest
        responses = []
        
        def on_response(response: object) -> None:
            if endpoint in response.url:  # type: ignore[attr-defined]
                async def _read() -> None:
                    try:
                        data = await response.json()  # type: ignore[attr-defined]
                        responses.append(data)
                    except Exception:
                        pass
                asyncio.ensure_future(_read())
        
        page.on("response", on_response)
        
        # Set up cleanup - after a delay, pick the largest response
        async def _resolve_largest():
            # Wait a bit for all responses to arrive
            await asyncio.sleep(3)
            if responses and not future.done():
                # Return the largest response (by JSON string length)
                import json
                largest = max(responses, key=lambda r: len(json.dumps(r)))
                future.set_result(largest)
                page.remove_listener("response", on_response)
        
        asyncio.ensure_future(_resolve_largest())
    
    return future


class RecorderClient:
    """Client for recorder.google.com operations."""

    async def list_recordings(self) -> list[Recording]:
        """Fetch all recordings."""
        async with async_playwright() as p:
            context = await create_context(p)
            page = await context.new_page()
            try:
                future = _intercept_grpc(page, "GetRecordingList")
                await page.goto(RECORDER_URL)
                try:
                    data = await asyncio.wait_for(asyncio.shield(future), timeout=30)
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        "Recorder did not load. Session may be expired. Run: recorder login"
                    )
                return self._parse_recordings(data)
            finally:
                await context.close()

    async def get_transcript(self, recording_id: str) -> Transcript:
        """
        Fetch the official full transcript for a recording.

        This method intercepts the GetTranscription gRPC response (447KB for a 73-min recording)
        and reconstructs the official speaker-labeled Pixel transcript format that matches
        what the web UI's Download button produces (50KB text file with speaker labels).

        The GetTranscription response contains all word-level data with speaker information
        in word[6]. The parser extracts speaker IDs, groups words by speaker turn, and
        formats the output to match the official transcript:
        - Initial text (possibly unlabeled before speaker detection)
        - [Speaker 1] on its own line, then that speaker's text
        - [Speaker 2] on its own line, then that speaker's text
        - etc.
        - CRLF line endings (Windows format)

        The web UI uses this same GetTranscription response to build the client-side blob
        that gets downloaded as "Recording Name.txt".
        """
        async with async_playwright() as p:
            context = await create_context(p)
            page = await context.new_page()
            try:
                # Step 1: get recording list to find audio_id
                list_future = _intercept_grpc(page, "GetRecordingList")
                await page.goto(RECORDER_URL)
                try:
                    list_data = await asyncio.wait_for(asyncio.shield(list_future), timeout=30)
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        "Recorder did not load. Session may be expired. Run: recorder login"
                    )

                audio_id = None
                for item in list_data[0]:
                    if item[0] == recording_id:
                        audio_id = item[13]
                        break
                if not audio_id:
                    raise ValueError(f"Recording not found: {recording_id}")

                # Step 2: navigate to the recording URL to trigger GetTranscription
                # GetTranscription returns one 447KB response with all data
                trans_future = _intercept_grpc(page, "GetTranscription")
                await page.goto(f"{RECORDER_URL}/{audio_id}")
                try:
                    data = await asyncio.wait_for(asyncio.shield(trans_future), timeout=30)
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"Transcript not available for {recording_id}. "
                        "The recording may not have a transcript yet."
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
                # Get recording list to find audio_id and title
                list_future = _intercept_grpc(page, "GetRecordingList")
                await page.goto(RECORDER_URL)
                try:
                    list_data = await asyncio.wait_for(asyncio.shield(list_future), timeout=30)
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        "Recorder did not load. Session may be expired. Run: recorder login"
                    )

                audio_id = None
                title = recording_id
                for item in list_data[0]:
                    if item[0] == recording_id:
                        audio_id = item[13]
                        title = item[1]
                        break
                if not audio_id:
                    raise ValueError(f"Recording not found: {recording_id}")

                url = f"{_AUDIO_BASE}/{audio_id}"
                response = await page.request.get(url)
                if not response.ok:
                    raise RuntimeError(f"Failed to download audio: HTTP {response.status}")

                safe_title = "".join(c if c.isalnum() or c in " .-_" else "_" for c in title)
                filepath = output_path / f"{safe_title}.m4a"
                output_path.mkdir(parents=True, exist_ok=True)
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
        results: dict = {"transcripts": [], "audio": [], "errors": []}

        for rec in recordings:
            try:
                if rec.has_transcript:
                    transcript = await self.get_transcript(rec.id)
                    safe_title = "".join(
                        c if c.isalnum() or c in " .-_" else "_" for c in rec.title
                    )
                    txt_path = transcripts_dir / f"{safe_title}.txt"
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

    def _parse_recordings(self, data: list) -> list[Recording]:
        """Parse GetRecordingList response.

        Response format: [[recording, ...], pagination_cursor]
        Each recording: [id, title, [created_sec_str, ns], [dur_sec_str, ns], lat, lng,
                         location, null, audio_info, tags, transcript_segments, ..., audio_id, ...]
        """
        recordings = []
        try:
            items = data[0]
        except (IndexError, TypeError):
            return recordings

        for item in items:
            try:
                recordings.append(Recording(
                    id=str(item[0]),
                    title=str(item[1]),
                    created_at=datetime.fromtimestamp(int(item[2][0])),
                    duration_seconds=int(item[3][0]),
                    has_transcript=bool(item[10]),
                    audio_id=str(item[13]) if item[13] else "",
                ))
            except (IndexError, TypeError, ValueError):
                continue
        return recordings

    def _parse_official_transcript_text(self, recording_id: str, text: str) -> Transcript:
        """Parse official transcript download (plain text with speaker labels).

        Format (based on real Pixel transcript file):
            Initial text (possibly unlabeled)
            
            [Speaker 1]
            Text from speaker 1...
            
            [Speaker 2]
            Text from speaker 2...
            ...
            Transcribed by Pixel
        
        The first few lines may appear before any speaker label. Speaker labels are
        preserved in the full_text. The footer is stripped. Segments are created per
        speaker turn (timestamp info not available in official format).
        """
        # Remove the "Transcribed by Pixel" footer if present
        footer = "Transcribed by Pixel"
        if text.strip().endswith(footer):
            text = text[:-len(footer)].strip()

        # Split into segments by speaker labels
        import re
        segments = []
        # Pattern matches [Speaker N] on its own line
        pattern = r'^\[Speaker (\d+)\]$'
        
        lines = text.split('\n')
        current_speaker = None
        current_text = []
        initial_text = []  # Text before first speaker label
        found_first_speaker = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check if this line is a speaker label
            speaker_match = re.match(pattern, line)
            if speaker_match:
                # Save previous segment if any
                if current_speaker and current_text:
                    segments.append(TranscriptSegment(
                        timestamp_seconds=0.0,
                        speaker=current_speaker,
                        text=' '.join(current_text),
                    ))
                    current_text = []
                elif not found_first_speaker and initial_text:
                    # Save initial unlabeled text as a segment
                    segments.append(TranscriptSegment(
                        timestamp_seconds=0.0,
                        speaker=None,
                        text=' '.join(initial_text),
                    ))
                    initial_text = []
                
                # Start new speaker
                current_speaker = f"Speaker {speaker_match.group(1)}"
                found_first_speaker = True
            else:
                # This is text content
                if found_first_speaker:
                    current_text.append(line)
                else:
                    initial_text.append(line)
        
        # Save final segment
        if current_speaker and current_text:
            segments.append(TranscriptSegment(
                timestamp_seconds=0.0,
                speaker=current_speaker,
                text=' '.join(current_text),
            ))
        elif not found_first_speaker and initial_text:
            # Only unlabeled text, no speakers
            segments.append(TranscriptSegment(
                timestamp_seconds=0.0,
                speaker=None,
                text=' '.join(initial_text),
            ))
        
        # If no segments at all, treat entire text as one segment
        if not segments:
            segments.append(TranscriptSegment(
                timestamp_seconds=0.0,
                speaker=None,
                text=text,
            ))

        return Transcript(
            recording_id=recording_id,
            full_text=text,
            segments=segments,
        )

    def _parse_transcript(self, recording_id: str, data: list) -> Transcript:
        """Parse GetTranscription response to official Pixel transcript format.

        Actual structure (from 447KB response):
        data[0] = list of 1013 sentence units (NOT nested arrays)
        Each unit = [words[], sentence_speaker_int, sentence_field_str]
        - unit[0] = FLAT list of 1-64 word objects
        - unit[1] = int (possibly sentence-level speaker)
        - unit[2] = str (sentence-level field, NOT iterable)
        
        Each word = [text, alt_display_text, start_ms, end_ms, null, null, [speaker_flags]]
        - word[0] = raw token (always present)
        - word[1] = display text with punctuation (or null) - PREFER THIS when present
        - word[6] = [speaker_id, ?] where speaker_id: None/0=unlabeled, 1+=Speaker N
        
        Official format: 1029 lines, one block per sentence unit, CRLF, speaker headers
        """
        lines = []
        segments = []
        current_speaker = None
        
        try:
            # Walk sentence units (1013 units in Joel recording)
            for unit in data[0]:
                if not isinstance(unit, list) or len(unit) < 1:
                    continue
                
                # unit[0] is the flat list of word objects
                words = unit[0]
                if not isinstance(words, list):
                    continue
                
                # Extract words and determine speaker for this sentence unit
                sentence_words = []
                sentence_speaker = None
                
                for word in words:
                    if not isinstance(word, list) or len(word) < 7:
                        continue
                    
                    # Prefer word[1] (display text with punctuation) over word[0] (raw token)
                    text = word[1] if word[1] else word[0]
                    if not text:
                        continue
                    
                    sentence_words.append(str(text))
                    
                    # Extract speaker from word[6] speaker_flags
                    if word[6] and isinstance(word[6], list) and len(word[6]) > 0:
                        raw_id = word[6][0]
                        if raw_id and raw_id > 0:
                            sentence_speaker = raw_id
                
                if not sentence_words:
                    continue
                
                # Join words with spaces for this sentence
                sentence_text = ' '.join(sentence_words)
                
                # Detect speaker change
                if sentence_speaker != current_speaker:
                    # Add header for new speaker (if labeled)
                    if sentence_speaker is not None:
                        lines.append('')  # Blank line
                        lines.append(f'[Speaker {sentence_speaker}]')
                    
                    current_speaker = sentence_speaker
                
                # Add sentence text
                lines.append(sentence_text)
                
                # Create segment (group consecutive sentences by speaker for segments)
                if not segments or segments[-1].speaker != (f'Speaker {current_speaker}' if current_speaker else None):
                    segments.append(TranscriptSegment(
                        timestamp_seconds=0.0,
                        speaker=f'Speaker {current_speaker}' if current_speaker else None,
                        text=sentence_text,
                    ))
                else:
                    # Same speaker, append to last segment
                    segments[-1].text += ' ' + sentence_text
        
        except (IndexError, TypeError) as e:
            pass

        if not lines:
            return Transcript(recording_id=recording_id, full_text="", segments=[])
        
        # Join with CRLF (Windows line endings) to match official file
        full_text = '\r\n'.join(lines)
        
        return Transcript(
            recording_id=recording_id,
            full_text=full_text,
            segments=segments,
        )
