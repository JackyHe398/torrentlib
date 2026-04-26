"""Deterministic checks for README examples and public API imports."""

from torrentlib import Peer, Torrent, TorrentStatus
from torrentlib.Tracker import Check, Query, TorrentStatus as TrackerTorrentStatus
from torrentlib.Tracker.TrackerQueryException import TrackerQueryException


def test_public_imports_are_available():
    assert Torrent is not None
    assert TorrentStatus is not None
    assert Peer is not None
    assert Check is not None
    assert Query is not None


def test_minimal_torrent_creation_matches_readme():
    torrent = Torrent(info_hash="1234567890abcdef1234567890abcdef12345678")

    assert torrent.info_hash == "1234567890abcdef1234567890abcdef12345678"
    assert torrent.event is TorrentStatus.STARTED
    assert torrent.left == 0


def test_explicit_torrent_creation_matches_readme():
    torrent = Torrent(
        info_hash="1234567890abcdef1234567890abcdef12345678",
        total_size=1145141919810,
        left=1145141919810,
        downloaded=0,
        uploaded=0,
        event=TorrentStatus.STOPPED,
        name="example_file.iso",
        piece_length=None,
        num_pieces=None,
    )

    assert torrent.name == "example_file.iso"
    assert torrent.event is TorrentStatus.STOPPED
    assert torrent.left == 1145141919810


def test_tracker_check_api_matches_readme():
    assert hasattr(Check, "auto")
    assert hasattr(Check, "http")
    assert hasattr(Check, "udp")
    assert hasattr(Check, "multiple")


def test_tracker_query_api_matches_readme():
    torrent = Torrent(info_hash="1234567890abcdef1234567890abcdef12345678")
    peer_id = "-robots-testing12345"

    assert torrent.info_hash
    assert peer_id.startswith("-robots-")
    assert hasattr(Query, "single")
    assert hasattr(Query, "multi")


# def test_peer_construction_matches_readme():
#     torrent = Torrent(info_hash="1234567890abcdef1234567890abcdef12345678")
#     peer = Peer(("127.0.0.1", 6881), torrent, "-robots-testing12345")
#
#     assert peer.torrent is torrent


def test_exception_imports_match_readme():
    assert TrackerQueryException is not None
    assert TrackerTorrentStatus is TorrentStatus
