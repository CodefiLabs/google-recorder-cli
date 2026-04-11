from recorder_cli.recorder import RecorderClient


def test_parse_recordings_list():
    client = RecorderClient()
    data = [
        {
            "id": "rec_1",
            "title": "Meeting",
            "created_at": "2026-01-01T00:00:00",
            "duration_seconds": 300,
            "has_transcript": True,
        }
    ]
    recordings = client._parse_recordings(data)
    assert len(recordings) == 1
    assert recordings[0].id == "rec_1"
    assert recordings[0].title == "Meeting"


def test_parse_recordings_dict():
    client = RecorderClient()
    data = {"recordings": [
        {"id": "rec_2", "title": "Call", "created_at": "2026-02-01T00:00:00", "duration_seconds": 60, "has_transcript": False}
    ]}
    recordings = client._parse_recordings(data)
    assert len(recordings) == 1
    assert recordings[0].id == "rec_2"


def test_parse_transcript():
    client = RecorderClient()
    data = {
        "text": "Hello world",
        "segments": [
            {"timestamp": 0.0, "speaker": "Bob", "text": "Hello"},
            {"timestamp": 1.5, "text": "world"},
        ],
    }
    t = client._parse_transcript("rec_1", data)
    assert t.full_text == "Hello world"
    assert len(t.segments) == 2
    assert t.segments[0].speaker == "Bob"
    assert t.segments[1].speaker is None


def test_parse_transcript_fallback_text():
    client = RecorderClient()
    data = {
        "segments": [
            {"timestamp": 0.0, "text": "Hello"},
            {"timestamp": 1.0, "text": "there"},
        ],
    }
    t = client._parse_transcript("rec_1", data)
    assert t.full_text == "Hello\nthere"
