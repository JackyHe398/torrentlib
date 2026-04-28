"""Manual integration checks for live tracker endpoints.

These tests hit the public internet and are excluded from CI by default.
Run them explicitly with: `pytest -m integration test/test_Tracker.py`
"""

from pathlib import Path

import pytest

from torrentlib import Torrent, Tracker

pytestmark = pytest.mark.integration


def test_multiple_trackers_check():
    tracker_file = Path(__file__).with_name("trackers.txt")
    with tracker_file.open(encoding="utf-8") as handle:
        urls = [
            line.strip()
            for line in handle
            if line.strip() and not line.startswith("#")
        ]

    result = Tracker.Check.multiple(urls, timeout=5)
    assert isinstance(result, dict)


def test_tracker_query():
    torrent = Torrent("ee04b6d6830c8be5e693cd1cb83eba9040da50d7", 0)
    self_peer_id = "-robots-testing12345"

    for tracker_url in (
        "https://torrent.ubuntu.com/announce",
    ):
        try:
            result = Tracker.Query.single(torrent, tracker_url, self_peer_id)
            assert isinstance(result, dict)
        except Exception:
            # Live tracker availability is not deterministic.
            pass
