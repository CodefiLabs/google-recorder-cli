"""
Test using the exact real-world repro case from Kevin's investigation (2026-08-19).

This demonstrates the fix using the actual IDs and data from the bug report.
Cannot be run without authentication, but documents the expected behavior.
"""

from recorder_cli.recorder import RecorderClient

# Real IDs from Kevin's investigation (2026-08-19 ~4:38pm CT)
REAL_RECORDING_ID = "6c75f5e7-a2ff-4c30-967c-48db9f896b6b"
REAL_AUDIO_ID = "80da17b9-29ac-4932-9579-c5bafe0daec9"
REAL_TITLE = "Aug 19 at 2:32 PM call with Joel"
REAL_DURATION_SECONDS = 4407  # 73m 27s

# What GetTranscription returned (the bug)
REAL_TRUNCATED_RESPONSE = [
    [
        [[["I", "", "0", "500", None, None, []]]],
        [[["um", "", "600", "900", None, None, []]]],
    ]
]

# Simulated excerpt from the official download (50,970 bytes total)
# The real file has ~9,255 words with speaker labels
SIMULATED_OFFICIAL_EXCERPT = """[Speaker 1] I um, so I wanted to discuss the quarterly objectives and key results for the engineering team.

[Speaker 2] Sounds good. Let me pull up the document we started last week.

[Speaker 1] Perfect. I've been thinking about how we structure the rollout plan, especially given the dependencies on the infrastructure team.

[Speaker 2] Right, and we also need to coordinate with product on the feature prioritization.

[Speaker 1] Exactly. So my proposal is to break this into three phases. Phase one would focus on the core API endpoints and database migrations.

[Speaker 2] That makes sense. What's the timeline for phase one?

[Speaker 1] I'm thinking four weeks, which gives us buffer for code review and testing. Then phase two would be the frontend components.

[Speaker 2] And phase three?

[Speaker 1] Integration, performance testing, and the production rollout. We'd want at least two weeks for that.

[Speaker 2] Okay, so roughly ten weeks total?

[Speaker 1] Yes, with some slack built in. I'd rather over-promise and deliver early than the other way around.

Transcribed by Pixel"""


def test_real_repro_old_behavior():
    """Documents what the bug returned: only "I um" from truncated GetTranscription."""
    client = RecorderClient()
    
    # OLD BEHAVIOR: Parse GetTranscription gRPC response
    old_result = client._parse_transcript(REAL_RECORDING_ID, REAL_TRUNCATED_RESPONSE)
    
    assert old_result.recording_id == REAL_RECORDING_ID
    assert old_result.full_text == "I um"
    assert len(old_result.full_text) == 4  # Only 4 bytes
    assert len(old_result.segments) == 2  # Two words
    
    # All segments have no speaker labels (hardcoded None in old parser)
    assert all(seg.speaker is None for seg in old_result.segments)
    
    # For a 73-minute recording, this is clearly truncated
    words_per_second = len(old_result.full_text.split()) / REAL_DURATION_SECONDS
    assert words_per_second < 0.001  # Less than 1 word per 1000 seconds (broken!)


def test_real_repro_new_behavior():
    """Documents what the fix returns: full official transcript with speaker labels."""
    client = RecorderClient()
    
    # NEW BEHAVIOR: Parse official download (plain text with speaker labels)
    new_result = client._parse_official_transcript(
        REAL_RECORDING_ID, 
        SIMULATED_OFFICIAL_EXCERPT
    )
    
    assert new_result.recording_id == REAL_RECORDING_ID
    
    # Full text is much longer (excerpt here, real file is 50,970 bytes)
    assert len(new_result.full_text) > 800
    
    # Contains content from beginning to end
    assert "I um" in new_result.full_text  # Start
    assert "deliver early" in new_result.full_text  # Middle
    assert "other way around" in new_result.full_text  # End
    
    # Footer is stripped
    assert "Transcribed by Pixel" not in new_result.full_text
    
    # Speaker labels are present in full_text
    assert "[Speaker 1]" in new_result.full_text
    assert "[Speaker 2]" in new_result.full_text
    
    # Segments have speaker labels
    assert any(seg.speaker == "Speaker 1" for seg in new_result.segments)
    assert any(seg.speaker == "Speaker 2" for seg in new_result.segments)
    
    # Multiple speaker turns
    assert len(new_result.segments) >= 8


def test_endpoint_url_construction():
    """Verify the correct endpoint URL is constructed."""
    from recorder_cli.recorder import _TRANSCRIPT_BASE
    
    # The fix uses the official download endpoint
    expected_url = f"{_TRANSCRIPT_BASE}/{REAL_AUDIO_ID}"
    assert expected_url == f"https://usercontent.recorder.google.com/download/transcript/{REAL_AUDIO_ID}"
    
    # Same pattern as audio download (but different path)
    from recorder_cli.recorder import _AUDIO_BASE
    audio_url = f"{_AUDIO_BASE}/{REAL_AUDIO_ID}"
    assert audio_url == f"https://usercontent.recorder.google.com/download/playback/{REAL_AUDIO_ID}"
    
    # Both use audio_id (field [13] from GetRecordingList), not recording_id
    assert REAL_AUDIO_ID != REAL_RECORDING_ID


def test_id_mapping_documented():
    """Document the two-ID system: recording_id (CLI) vs audio_id (web/download)."""
    # From GetRecordingList response (real structure):
    # item[0] = recording_id (user-facing CLI ID)
    # item[13] = audio_id (internal ID for web URLs and downloads)
    
    # Example from real repro:
    cli_id = REAL_RECORDING_ID  # "6c75f5e7-a2ff-4c30-967c-48db9f896b6b"
    web_id = REAL_AUDIO_ID      # "80da17b9-29ac-4932-9579-c5bafe0daec9"
    
    # Web UI URL: https://recorder.google.com/{audio_id}
    web_url = f"https://recorder.google.com/{web_id}"
    assert web_url == "https://recorder.google.com/80da17b9-29ac-4932-9579-c5bafe0daec9"
    
    # Download URLs use audio_id
    transcript_url = f"https://usercontent.recorder.google.com/download/transcript/{web_id}"
    audio_url = f"https://usercontent.recorder.google.com/download/playback/{web_id}"
    
    # User provides recording_id to CLI, we map to audio_id internally
    assert cli_id != web_id


def test_size_comparison():
    """Compare file sizes: 4 bytes (bug) vs 50,970 bytes (official)."""
    client = RecorderClient()
    
    old = client._parse_transcript(REAL_RECORDING_ID, REAL_TRUNCATED_RESPONSE)
    new = client._parse_official_transcript(REAL_RECORDING_ID, SIMULATED_OFFICIAL_EXCERPT)
    
    # The real official transcript is 50,970 bytes
    # Our simulated excerpt is smaller but still proves the point
    assert len(new.full_text) > 800  # Much larger than 4
    
    # Size ratio
    ratio = len(new.full_text) / len(old.full_text)
    assert ratio > 200  # At least 200x larger
    
    # Real file would be even larger
    REAL_OFFICIAL_SIZE = 50970
    real_ratio = REAL_OFFICIAL_SIZE / 4
    assert real_ratio == 12742.5  # Real file is 12,742x larger!
