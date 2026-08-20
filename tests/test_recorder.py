from recorder_cli.recorder import RecorderClient

# Fixtures for testing official transcript format
# Based on real file format from 2026-08-19 investigation:
# - Initial text may be unlabeled
# - Then speaker labels: [Speaker 1], [Speaker 2], etc.
# - Footer: "Transcribed by Pixel"
OFFICIAL_TRANSCRIPT_SHORT = """I, um. I think this is a test.

[Speaker 1]
Hello, this is a test recording.

[Speaker 2]
Yes, I can hear you clearly.

[Speaker 1]
Great, let's proceed with the meeting.

Transcribed by Pixel"""

OFFICIAL_TRANSCRIPT_LONG = """I, um. I think I stay grounded with, like?

[Speaker 1]
The data and the? Uh, and like the client deliverable. So I wanted to talk about the project status today.

[Speaker 2]
Sure, that sounds good. What's the latest update?

[Speaker 1]
Well, we've made significant progress on the main features. The authentication system is now complete and we've started working on the dashboard interface.

[Speaker 2]
Excellent. How's the timeline looking?

[Speaker 1]
We're on track to finish by the end of the month. There are a few edge cases we need to handle, but overall things are progressing well.

[Speaker 2]
That's great to hear. What about testing?

[Speaker 1]
We've written unit tests for the core modules and are now working on integration tests. The QA team will start their review next week.

[Speaker 2]
Perfect. Keep me updated on any blockers.

Transcribed by Pixel"""

# GetTranscription ACTUAL format (from 447KB response schema):
# data[0] = list of sentence units (1013 units for 73-min recording)
# Each unit = [words[], sentence_int, sentence_str] (always len=3)
#   unit[0] = flat list of word objects (1-64 words)
#   unit[1] = int (sentence-level field, NOT iterable)
#   unit[2] = str (sentence-level field, NOT iterable)
# 
# Each word = [text, alt_display, start_ms, end_ms, null, null, [speaker_flags]]
#   word[0] = raw token
#   word[1] = display text with punctuation (or null) - PREFER when present
#   word[6] = [speaker_id, ?] where 0/None=unlabeled, 1+=Speaker N

SIMPLE_GET_TRANSCRIPTION_DATA = [
    [
        # Sentence unit 1: Initial unlabeled text
        [
            [
                ["I", "I,", "0", "200", None, None, [0, 0]],
                ["um", "um.", "300", "500", None, None, [0, 0]],
            ],
            0,  # sentence int (always 0)
            "00000"  # sentence str (always same)
        ],
        # Sentence unit 2: Speaker 1
        [
            [
                ["Hello", "Hello", "1000", "1200", None, None, [0, 1]],  # word[6] = [flag0, speaker_id]
                ["there", "there", "1300", "1500", None, None, [0, 1]],
            ],
            0,
            "00000"
        ],
        # Sentence unit 3: Speaker 2
        [
            [
                ["Hi", "Hi", "2000", "2100", None, None, [0, 2]],
                ["back", "back", "2200", "2300", None, None, [0, 2]],
            ],
            0,
            "00000"
        ],
    ]
]

# Truncated version (only first sentence unit) - simulates old bug where
# parser crashed after first unit and dropped remaining 1012 units
TRUNCATED_LIVE_CAPTION_DATA = [
    [
        # Only first sentence unit (the bug: parser aborts early)
        [
            [
                ["I", None, "0", "200", None, None, [0, 0]],  # word[6] = [flag0, speaker_id]
                ["um", None, "300", "500", None, None, [0, 0]],
            ],
            0,  # always 0
            "00000"  # always same
        ],
    ]
]


def test_parse_recordings_basic():
    """Parse a real-format GetRecordingList response (positional arrays)."""
    client = RecorderClient()
    # Real API: [[recording, ...], pagination_cursor]
    # recording: [id, title, [created_sec_str, ns], [dur_sec_str, ns], ..., transcript_segs at [10], ..., audio_id at [13]]
    data = [
        [
            [
                "rec_1",                        # [0] id
                "Meeting",                      # [1] title
                ["1735689600", 0],              # [2] created_at
                ["300", 0],                     # [3] duration
                None, None, None, None, None,   # [4-8]
                None,                           # [9] tags
                [["seg"]],                      # [10] transcript_segments (non-empty = has transcript)
                None, None,                     # [11-12]
                "audio_abc123",                 # [13] audio_id
            ],
        ],
        "cursor",
    ]
    recordings = client._parse_recordings(data)
    assert len(recordings) == 1
    assert recordings[0].id == "rec_1"
    assert recordings[0].title == "Meeting"
    assert recordings[0].has_transcript is True
    assert recordings[0].audio_id == "audio_abc123"
    assert recordings[0].duration_seconds == 300


def test_parse_recordings_no_transcript():
    """Recording with no transcript (field [10] is empty/None)."""
    client = RecorderClient()
    data = [
        [
            [
                "rec_2", "Call",
                ["1738368000", 0], ["60", 0],
                None, None, None, None, None,
                None,
                None,       # [10] no transcript
                None, None,
                "audio_xyz",
            ],
        ],
        "cursor",
    ]
    recordings = client._parse_recordings(data)
    assert len(recordings) == 1
    assert recordings[0].id == "rec_2"
    assert recordings[0].has_transcript is False


def test_parse_recordings_empty():
    """Empty recording list."""
    client = RecorderClient()
    recordings = client._parse_recordings([[], "cursor"])
    assert recordings == []


def test_parse_recordings_malformed():
    """Malformed data returns empty list without raising."""
    client = RecorderClient()
    assert client._parse_recordings(None) == []
    assert client._parse_recordings([]) == []


def test_parse_transcript():
    """Parse GetTranscription response to official format with speaker labels."""
    client = RecorderClient()
    
    # Use the simple example with speaker info
    t = client._parse_transcript("rec_1", SIMPLE_GET_TRANSCRIPTION_DATA)
    assert t.recording_id == "rec_1"
    
    # Should reconstruct official format with speaker labels
    # Initial unlabeled text, then [Speaker 1], then [Speaker 2]
    assert "I, um." in t.full_text
    assert "[Speaker 1]" in t.full_text
    assert "[Speaker 2]" in t.full_text
    assert "Hello there" in t.full_text
    assert "Hi back" in t.full_text
    
    # Should use CRLF line endings
    assert "\r\n" in t.full_text
    
    # Should have 3 segments: unlabeled, speaker 1, speaker 2
    assert len(t.segments) == 3
    assert t.segments[0].speaker is None
    assert "I, um." in t.segments[0].text
    assert t.segments[1].speaker == "Speaker 1"
    assert "Hello there" in t.segments[1].text
    assert t.segments[2].speaker == "Speaker 2"
    assert "Hi back" in t.segments[2].text


def test_parse_transcript_multi_segment():
    """Multiple sentence units with same speaker are grouped together."""
    client = RecorderClient()
    data = [
        [
            # Unit 1: Speaker 1
            [
                [
                    ["Hello", "", "0", "200", None, None, [0, 1]],  # word[6] = [flag0, speaker_id]
                ],
                0,
                "00000"
            ],
            # Unit 2: Same speaker (1)
            [
                [
                    ["there", "", "1000", "1200", None, None, [0, 1]],
                ],
                0,
                "00000"
            ],
        ]
    ]
    t = client._parse_transcript("rec_1", data)
    # Same speaker, should be one segment
    assert len(t.segments) == 1
    assert t.segments[0].speaker == "Speaker 1"
    assert "Hello there" in t.segments[0].text


def test_parse_transcript_empty():
    """Empty transcript data returns empty Transcript."""
    client = RecorderClient()
    t = client._parse_transcript("rec_1", [[]])
    assert t.full_text == ""
    assert t.segments == []


def test_parse_official_transcript_with_speakers():
    """Parse official transcript format with speaker labels and initial unlabeled text."""
    client = RecorderClient()
    t = client._parse_official_transcript_text("rec_1", OFFICIAL_TRANSCRIPT_SHORT)
    
    # Full text should preserve speaker labels and strip footer
    assert "[Speaker 1]" in t.full_text
    assert "[Speaker 2]" in t.full_text
    assert "Transcribed by Pixel" not in t.full_text
    assert "Hello, this is a test recording." in t.full_text
    
    # Should have segments: initial unlabeled + 3 speaker turns
    assert len(t.segments) == 4
    
    # First segment is unlabeled initial text (before speaker detection)
    assert t.segments[0].speaker is None
    assert "I, um" in t.segments[0].text
    
    # Then speaker-labeled segments
    assert t.segments[1].speaker == "Speaker 1"
    assert t.segments[1].text == "Hello, this is a test recording."
    assert t.segments[2].speaker == "Speaker 2"
    assert t.segments[2].text == "Yes, I can hear you clearly."
    assert t.segments[3].speaker == "Speaker 1"
    assert t.segments[3].text == "Great, let's proceed with the meeting."


def test_parse_official_transcript_long():
    """Parse long official transcript (the kind that would truncate with GetTranscription)."""
    client = RecorderClient()
    t = client._parse_official_transcript_text("rec_long", OFFICIAL_TRANSCRIPT_LONG)
    
    # Should contain the full text, not truncated to just "I um"
    assert len(t.full_text) > 100  # Much longer than truncated version
    assert "I, um" in t.full_text  # Contains the start (note: comma)
    assert "Keep me updated on any blockers." in t.full_text  # Contains the end
    assert "Transcribed by Pixel" not in t.full_text  # Footer stripped
    
    # Should have multiple speaker segments plus initial unlabeled text
    assert len(t.segments) >= 5
    assert any(s.speaker == "Speaker 1" for s in t.segments)
    assert any(s.speaker == "Speaker 2" for s in t.segments)
    # First segment is unlabeled initial text
    assert t.segments[0].speaker is None


def test_parse_official_transcript_no_footer():
    """Official transcript without footer still parses correctly."""
    client = RecorderClient()
    # Actual format has speaker labels on separate lines
    text_no_footer = """[Speaker 1]
This transcript has no footer.

[Speaker 2]
But it should still parse correctly."""
    
    t = client._parse_official_transcript_text("rec_2", text_no_footer)
    assert len(t.segments) == 2
    assert t.segments[0].speaker == "Speaker 1"
    assert t.segments[1].speaker == "Speaker 2"


def test_parse_official_transcript_no_speakers():
    """Official transcript without speaker labels (fallback case)."""
    client = RecorderClient()
    text_no_speakers = "This is a simple transcript without any speaker labels."
    
    t = client._parse_official_transcript_text("rec_3", text_no_speakers)
    assert len(t.segments) == 1
    assert t.segments[0].speaker is None
    assert t.segments[0].text == text_no_speakers
    assert t.full_text == text_no_speakers


def test_truncated_vs_full_comparison():
    """Compare truncated data (first 2 words) vs full GetTranscription response.
    
    This demonstrates the OLD bug: we were only reading the first response/few words,
    but the GetTranscription payload (447KB) contains the FULL transcript.
    
    The fix: properly parse ALL words from GetTranscription and extract speaker info.
    """
    client = RecorderClient()
    
    # OLD BUG: Only parsing first 2 words (truncated data)
    truncated = client._parse_transcript("rec_bug", TRUNCATED_LIVE_CAPTION_DATA)
    assert "I" in truncated.full_text
    assert "um" in truncated.full_text
    assert len(truncated.full_text) < 20  # Very short
    
    # NEW: Parsing full GetTranscription response with speaker info
    full = client._parse_transcript("rec_full", SIMPLE_GET_TRANSCRIPTION_DATA)
    assert len(full.full_text) > 20  # Much longer
    assert "[Speaker 1]" in full.full_text  # Has speaker labels
    assert "[Speaker 2]" in full.full_text
    
    # Full version has speaker information
    assert any(s.speaker == "Speaker 1" for s in full.segments)
    assert any(s.speaker == "Speaker 2" for s in full.segments)
