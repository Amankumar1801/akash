import httpx
import pytest
from akash_data.testing import RecordingTransport, ReplayTransport


def test_record_then_replay_roundtrip(tmp_path):
    inner = httpx.MockTransport(lambda r: httpx.Response(200, json={"hello": "archive"}))
    rec = httpx.Client(transport=RecordingTransport(tmp_path, inner))
    live = rec.post("http://archive/tap", data={"query": "select 1"}).json()

    rep = httpx.Client(transport=ReplayTransport(tmp_path))
    assert rep.post("http://archive/tap", data={"query": "select 1"}).json() == live


def test_replay_missing_fixture_fails_loudly(tmp_path):
    with pytest.raises(AssertionError, match="no recorded fixture"):
        httpx.Client(transport=ReplayTransport(tmp_path)).get("http://nope")
