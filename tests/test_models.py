from datetime import datetime
from recorder_cli.models import Recording, Transcript, TranscriptSegment


def test_recording_creation():
    rec = Recording(
        id="rec_123",
        title="Test Recording",
        created_at=datetime(2026, 1, 1),
        duration_seconds=120,
        has_transcript=True,
    )
    assert rec.id == "rec_123"
    assert rec.duration_seconds == 120


def test_transcript_creation():
    seg = TranscriptSegment(timestamp_seconds=0.0, speaker="Alice", text="Hello")
    t = Transcript(recording_id="rec_123", full_text="Hello", segments=[seg])
    assert t.recording_id == "rec_123"
    assert len(t.segments) == 1
    assert t.segments[0].speaker == "Alice"


def test_transcript_default_segments():
    t = Transcript(recording_id="rec_123", full_text="Hello world")
    assert t.segments == []
