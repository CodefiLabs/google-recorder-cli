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


def _intercept_grpc(page, endpoint: str) -> asyncio.Future:
    """
    Register a one-shot response interceptor for a gRPC endpoint.
    Returns a Future that resolves with the parsed JSON body of the first matching response.
    The listener is automatically removed once the future resolves.
    """
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()

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
                # NOTE: This returns truncated live caption on long recordings
                # The official transcript comes from a different RPC we haven't identified yet
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

        The GetTranscription response (447KB for a 73-min recording) contains:
        - Full word-level data with speaker information in word[6]
        - All the data needed to reconstruct the official speaker-labeled transcript
        
        Response format: [[[segment, ...], ...]]
        Each segment: [sentence, ...]
        Each sentence: [word, ...]
        Each word: [text, alt_display_text, start_ms_str, end_ms_str, ?, ?, [speaker_flags]]
        
        We reconstruct the official format:
        - Initial text (possibly unlabeled before speaker detection)
        - [Speaker 1] on separate line, then that speaker's text
        - [Speaker 2] on separate line, then that speaker's text
        - etc.
        """
        # First pass: extract all words with speaker information
        words_with_speakers = []
        try:
            for segment in data[0]:
                for sentence in segment:
                    for word in sentence:
                        try:
                            text = str(word[0])
                            start_ms = int(word[2])
                            # Extract speaker info from word[6] (speaker_flags array)
                            speaker_id = None
                            if len(word) > 6 and word[6]:
                                # speaker_flags is an array, first element may be speaker ID
                                if isinstance(word[6], list) and len(word[6]) > 0:
                                    speaker_id = word[6][0] if word[6][0] else None
                            
                            words_with_speakers.append({
                                'text': text,
                                'start_ms': start_ms,
                                'speaker_id': speaker_id,
                            })
                        except (IndexError, TypeError, ValueError):
                            continue
        except (IndexError, TypeError):
            pass

        if not words_with_speakers:
            return Transcript(recording_id=recording_id, full_text="", segments=[])

        # Second pass: group into speaker turns and format like official transcript
        lines = []  # Will build the official format line by line
        segments = []
        current_speaker = None
        current_words = []
        
        for word_info in words_with_speakers:
            word_text = word_info['text']
            speaker_id = word_info['speaker_id']
            
            # Detect speaker change
            if speaker_id != current_speaker:
                # Save previous segment if any
                if current_words:
                    text = ' '.join(current_words)
                    if current_speaker is not None:
                        # This was a labeled speaker turn
                        lines.append('')  # Blank line before speaker label
                        lines.append(f'[Speaker {current_speaker}]')
                        lines.append(text)
                        segments.append(TranscriptSegment(
                            timestamp_seconds=0.0,
                            speaker=f'Speaker {current_speaker}',
                            text=text,
                        ))
                    else:
                        # Initial unlabeled text
                        lines.append(text)
                        segments.append(TranscriptSegment(
                            timestamp_seconds=0.0,
                            speaker=None,
                            text=text,
                        ))
                    current_words = []
                
                # Start new speaker turn
                current_speaker = speaker_id
            
            current_words.append(word_text)
        
        # Save final segment
        if current_words:
            text = ' '.join(current_words)
            if current_speaker is not None:
                lines.append('')
                lines.append(f'[Speaker {current_speaker}]')
                lines.append(text)
                segments.append(TranscriptSegment(
                    timestamp_seconds=0.0,
                    speaker=f'Speaker {current_speaker}',
                    text=text,
                ))
            else:
                lines.append(text)
                segments.append(TranscriptSegment(
                    timestamp_seconds=0.0,
                    speaker=None,
                    text=text,
                ))
        
        # Join with CRLF (Windows line endings) to match official file
        full_text = '\r\n'.join(lines)
        
        return Transcript(
            recording_id=recording_id,
            full_text=full_text,
            segments=segments,
        )
