from recorder_cli.recorder import RecorderClient

# Fixtures for testing official transcript format
OFFICIAL_TRANSCRIPT_SHORT = """[Speaker 1] Hello, this is a test recording.
[Speaker 2] Yes, I can hear you clearly.
[Speaker 1] Great, let's proceed with the meeting.

Transcribed by Pixel"""

OFFICIAL_TRANSCRIPT_LONG = """[Speaker 1] I um, so I wanted to talk about the project status today.
[Speaker 2] Sure, that sounds good. What's the latest update?
[Speaker 1] Well, we've made significant progress on the main features. The authentication system is now complete and we've started working on the dashboard interface.
[Speaker 2] Excellent. How's the timeline looking?
[Speaker 1] We're on track to finish by the end of the month. There are a few edge cases we need to handle, but overall things are progressing well.
[Speaker 2] That's great to hear. What about testing?
[Speaker 1] We've written unit tests for the core modules and are now working on integration tests. The QA team will start their review next week.
[Speaker 2] Perfect. Keep me updated on any blockers.

Transcribed by Pixel"""

# Truncated live caption (old format) - simulates what GetTranscription returns
TRUNCATED_LIVE_CAPTION_DATA = [
    [
        [[["I", "", "0", "200", None, None, []]]],
        [[["um", "", "300", "500", None, None, []]]],
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
    """Parse a real-format GetTranscription response (positional arrays)."""
    client = RecorderClient()
    # Real API: [[[segment, ...], ...]]
    # data[0] = list of segments; each segment = list of sentences; each sentence = list of words
    # word: [text, alt_text, start_ms_str, end_ms_str, ?, ?, [speaker_flags]]
    data = [
        [  # segments
            [  # segment 0: sentences
                [  # sentence 0: words
                    ["Hello", "Hello", "0", "500", None, None, [1]],
                    ["world", "world", "1500", "2000", None, None, [1]],
                ],
            ],
        ]
    ]
    t = client._parse_transcript("rec_1", data)
    assert t.recording_id == "rec_1"
    assert t.full_text == "Hello world"
    assert len(t.segments) == 2
    assert t.segments[0].text == "Hello"
    assert t.segments[0].timestamp_seconds == 0.0
    assert t.segments[1].text == "world"
    assert t.segments[1].timestamp_seconds == 1.5


def test_parse_transcript_multi_segment():
    """Multiple segments concatenate into a single text."""
    client = RecorderClient()
    data = [
        [
            [[["Hello", "", "0", "200", None, None, []]]],
            [[["there", "", "1000", "1200", None, None, []]]],
        ]
    ]
    t = client._parse_transcript("rec_1", data)
    assert t.full_text == "Hello there"
    assert len(t.segments) == 2


def test_parse_transcript_empty():
    """Empty transcript data returns empty Transcript."""
    client = RecorderClient()
    t = client._parse_transcript("rec_1", [[]])
    assert t.full_text == ""
    assert t.segments == []


def test_parse_official_transcript_with_speakers():
    """Parse official transcript format with speaker labels."""
    client = RecorderClient()
    t = client._parse_official_transcript("rec_1", OFFICIAL_TRANSCRIPT_SHORT)
    
    # Full text should preserve speaker labels and strip footer
    assert "[Speaker 1]" in t.full_text
    assert "[Speaker 2]" in t.full_text
    assert "Transcribed by Pixel" not in t.full_text
    assert "Hello, this is a test recording." in t.full_text
    
    # Should have segments for each speaker turn
    assert len(t.segments) == 3
    assert t.segments[0].speaker == "Speaker 1"
    assert t.segments[0].text == "Hello, this is a test recording."
    assert t.segments[1].speaker == "Speaker 2"
    assert t.segments[1].text == "Yes, I can hear you clearly."
    assert t.segments[2].speaker == "Speaker 1"
    assert t.segments[2].text == "Great, let's proceed with the meeting."


def test_parse_official_transcript_long():
    """Parse long official transcript (the kind that would truncate with GetTranscription)."""
    client = RecorderClient()
    t = client._parse_official_transcript("rec_long", OFFICIAL_TRANSCRIPT_LONG)
    
    # Should contain the full text, not truncated to just "I um"
    assert len(t.full_text) > 100  # Much longer than truncated version
    assert "I um" in t.full_text  # Contains the start
    assert "Keep me updated on any blockers." in t.full_text  # Contains the end
    assert "Transcribed by Pixel" not in t.full_text  # Footer stripped
    
    # Should have multiple speaker segments
    assert len(t.segments) >= 5
    assert any(s.speaker == "Speaker 1" for s in t.segments)
    assert any(s.speaker == "Speaker 2" for s in t.segments)


def test_parse_official_transcript_no_footer():
    """Official transcript without footer still parses correctly."""
    client = RecorderClient()
    text_no_footer = """[Speaker 1] This transcript has no footer.
[Speaker 2] But it should still parse correctly."""
    
    t = client._parse_official_transcript("rec_2", text_no_footer)
    assert len(t.segments) == 2
    assert t.segments[0].speaker == "Speaker 1"
    assert t.segments[1].speaker == "Speaker 2"


def test_parse_official_transcript_no_speakers():
    """Official transcript without speaker labels (fallback case)."""
    client = RecorderClient()
    text_no_speakers = "This is a simple transcript without any speaker labels."
    
    t = client._parse_official_transcript("rec_3", text_no_speakers)
    assert len(t.segments) == 1
    assert t.segments[0].speaker is None
    assert t.segments[0].text == text_no_speakers
    assert t.full_text == text_no_speakers


def test_truncated_vs_official_comparison():
    """Compare truncated live caption (old) vs official transcript (new).
    
    This demonstrates the bug: GetTranscription returns "I um" (2 words)
    while the official download returns the complete transcript (100+ words).
    """
    client = RecorderClient()
    
    # Old method (GetTranscription) - returns truncated caption
    truncated = client._parse_transcript("rec_bug", TRUNCATED_LIVE_CAPTION_DATA)
    assert truncated.full_text == "I um"
    assert len(truncated.full_text.split()) == 2  # Only 2 words
    
    # New method (official download) - returns complete transcript
    official = client._parse_official_transcript("rec_bug", OFFICIAL_TRANSCRIPT_LONG)
    assert len(official.full_text.split()) > 100  # 100+ words
    
    # The official transcript is 50+ times longer
    assert len(official.full_text) > 50 * len(truncated.full_text)
