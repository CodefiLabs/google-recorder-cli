from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Recording:
    id: str
    title: str
    created_at: datetime
    duration_seconds: int
    has_transcript: bool
    audio_id: str = ""  # internal ID used by download/transcript APIs (field [13] in API response)


@dataclass
class TranscriptSegment:
    timestamp_seconds: float
    speaker: str | None
    text: str


@dataclass
class Transcript:
    recording_id: str
    full_text: str
    segments: list[TranscriptSegment] = field(default_factory=list)
