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

        This method intercepts the GetTranscription gRPC response and waits for the largest
        payload (447KB for a 73-min recording), then reconstructs the official speaker-labeled 
        Pixel transcript format that matches what the web UI's Download button produces 
        (50KB text file with speaker labels).

        GetTranscription may send multiple responses. This method collects them and selects
        the largest one, which contains the full word-level data with speaker information
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
                # GetTranscription may send multiple responses; wait for the largest (447KB)
                trans_future = _intercept_grpc(page, "GetTranscription", wait_for_largest=True)
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

        Actual structure (from 447KB response, live schema):
        data[0] = list of 1013 sentence units
        Each unit = [words[], int(0), str5] — always length 3
        - unit[0] = FLAT list of word objects
        - unit[1] = always 0 (not speaker)
        - unit[2] = always same 5-char BCP-47-like string (not iterable)
        
        Each word = [text, alt_display_text, start_ms, end_ms, null, null, [flag, speaker_id]]
        - word[0] = raw token (always present)
        - word[1] = display text with punctuation (or null) - PREFER THIS when present
                    179 word[1] values start with '\\n' (embedded line breaks)
        - word[6] = [flag0, speaker_id] where:
                    flag0: 0 or 1 (not speaker - distribution {0:8370, 1:199})
                    speaker_id at INDEX 1: 0=unlabeled, 1-7=Speaker N
                    Distribution: {0:9, 1:5122, 2:3209, 3:86, 4:18, 5:33, 6:46, 7:46}
        
        Official format to match:
        - 50970 bytes, CRLF line endings
        - 343 [Speaker N] headers (emitted at start of each paragraph, even for same speaker)
        - 179 paragraph breaks (word[1] starting with '\\n')
        - First paragraph unlabeled (first 9 words have speaker_id 0)
        - SHA256: 2dcfdf2314a0b821b5743fda92e8d9aaed02c885187c7c2099aabe062f6874b5
        """
        output_lines = []
        segments = []
        current_speaker = None
        current_line = []
        current_segment_text = []
        
        try:
            # Walk all sentence units (1013 units in Joel recording)
            for unit in data[0]:
                if not isinstance(unit, list) or len(unit) < 1:
                    continue
                
                # unit[0] is the flat list of word objects
                words = unit[0]
                if not isinstance(words, list):
                    continue
                
                # Process each word in this unit
                for word in words:
                    if not isinstance(word, list) or len(word) < 7:
                        continue
                    
                    # Prefer word[1] (display text with punctuation) over word[0] (raw token)
                    text = word[1] if word[1] else word[0]
                    if not text:
                        continue
                    
                    text = str(text)
                    
                    # Extract speaker from word[6][1] (NOT word[6][0] which is a flag)
                    word_speaker = 0  # Default: unlabeled
                    if word[6] and isinstance(word[6], list) and len(word[6]) > 1:
                        speaker_id = word[6][1]
                        if speaker_id is not None:
                            word_speaker = speaker_id
                    
                    # Detect speaker change - emit header
                    if word_speaker != current_speaker:
                        # Flush current line
                        if current_line:
                            line_text = ' '.join(current_line)
                            output_lines.append(line_text)
                            current_segment_text.append(line_text)
                            current_line = []
                        
                        # Save previous segment
                        if current_segment_text:
                            segments.append(TranscriptSegment(
                                timestamp_seconds=0.0,
                                speaker=f'Speaker {current_speaker}' if current_speaker and current_speaker > 0 else None,
                                text=' '.join(current_segment_text),
                            ))
                            current_segment_text = []
                        
                        # Emit speaker header (skip for unlabeled speaker_id 0)
                        if word_speaker > 0:
                            output_lines.append('')  # Blank line
                            output_lines.append(f'[Speaker {word_speaker}]')
                        
                        current_speaker = word_speaker
                    
                    # Handle embedded newlines in word[1] (179 cases = paragraph breaks)
                    # Official format: emit [Speaker N] at START of each paragraph
                    if text.startswith('\n'):
                        # Flush current line before paragraph break
                        if current_line:
                            line_text = ' '.join(current_line)
                            output_lines.append(line_text)
                            current_segment_text.append(line_text)
                            current_line = []
                        
                        # Emit blank line + speaker header for NEW paragraph
                        # BUT: Skip if we just emitted this exact header (dedup consecutive headers)
                        # This happens when speaker change AND paragraph break occur on same word
                        expected_header = f'[Speaker {word_speaker}]'
                        last_line = output_lines[-1] if output_lines else None
                        
                        if word_speaker > 0 and last_line != expected_header:
                            output_lines.append('')  # Blank line
                            output_lines.append(expected_header)
                        
                        # Continue with text after the newline
                        text = text[1:]
                    
                    if text:
                        current_line.append(text)
        
        except (IndexError, TypeError) as e:
            pass

        # Flush final line and segment
        if current_line:
            line_text = ' '.join(current_line)
            output_lines.append(line_text)
            current_segment_text.append(line_text)
        
        if current_segment_text:
            segments.append(TranscriptSegment(
                timestamp_seconds=0.0,
                speaker=f'Speaker {current_speaker}' if current_speaker and current_speaker > 0 else None,
                text=' '.join(current_segment_text),
            ))
        
        if not output_lines:
            return Transcript(recording_id=recording_id, full_text="", segments=[])
        
        # Join with CRLF (Windows line endings)
        full_text = '\r\n'.join(output_lines)
        
        return Transcript(
            recording_id=recording_id,
            full_text=full_text,
            segments=segments,
        )
