def test_import_models():
    from recorder_cli.models import Recording, Transcript, TranscriptSegment


def test_import_browser():
    from recorder_cli.browser import login, has_session, intercept_response


def test_import_recorder():
    from recorder_cli.recorder import RecorderClient


def test_import_cli():
    from recorder_cli.cli import main


def test_import_mcp():
    from recorder_cli.mcp_server import mcp, main
