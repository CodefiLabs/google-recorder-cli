from recorder_cli.recorder import RecorderClient


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
