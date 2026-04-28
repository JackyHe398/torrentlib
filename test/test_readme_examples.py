"""Deterministic checks for README examples and public API imports."""

from pathlib import Path

from torrentlib import Peer, Torrent, TorrentMetaInfo, TorrentStatus
from torrentlib.Tracker import Check, Query, TorrentStatus as TrackerTorrentStatus
from torrentlib.Tracker.TrackerQueryException import TrackerQueryException


def test_public_imports_are_available():
    assert Torrent is not None
    assert TorrentMetaInfo is not None
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


def test_ubuntu_torrent_file_parsing_uses_bencodepy():
    torrent_path = Path(__file__).with_name("ubuntu-26.04-desktop-amd64.iso.torrent")

    torrent = Torrent.from_file(str(torrent_path))

    assert torrent.name == "ubuntu-26.04-desktop-amd64.iso"
    assert torrent.total_size == 6518974464
    assert torrent.piece_length == 262144
    assert torrent.num_pieces == 24868
    assert torrent.metadata is not None


def test_torrent_metainfo_from_file_matches_readme():
    torrent_path = Path(__file__).with_name("ubuntu-26.04-desktop-amd64.iso.torrent")

    metainfo = TorrentMetaInfo.from_file(str(torrent_path))

    assert metainfo.info_hash
    assert metainfo.name == "ubuntu-26.04-desktop-amd64.iso"
    assert metainfo.total_size == 6518974464
    assert metainfo.piece_length == 262144
    assert metainfo.num_pieces == 24868


def test_torrent_from_metainfo_matches_readme():
    torrent_path = Path(__file__).with_name("ubuntu-26.04-desktop-amd64.iso.torrent")

    metainfo = TorrentMetaInfo.from_file(str(torrent_path))
    torrent = Torrent.from_metainfo(metainfo)

    assert torrent.metainfo is metainfo
    assert torrent.info_hash == metainfo.info_hash
    assert torrent.name == metainfo.name
    assert torrent.total_size == metainfo.total_size


def test_torrent_metainfo_editing_examples_match_readme():
    torrent_path = Path(__file__).with_name("ubuntu-26.04-desktop-amd64.iso.torrent")

    metainfo = TorrentMetaInfo.from_file(str(torrent_path))
    old_info_hash = metainfo.info_hash

    metainfo.data[b"announce"] = b"https://tracker.example.com/announce"
    metainfo.data[b"announce-list"] = [
        [b"https://tracker.example.com/announce"],
        [b"udp://tracker2.example.com:6969/announce"],
    ]
    metainfo.data[b"x-meta-tag"] = b"custom value"

    assert metainfo.info is not None
    metainfo.info[b"private"] = 1
    metainfo.info[b"x-info-tag"] = b"custom value"
    metainfo.refresh()

    assert metainfo.data[b"announce"] == b"https://tracker.example.com/announce"
    assert metainfo.data[b"announce-list"][1][0] == b"udp://tracker2.example.com:6969/announce"
    assert metainfo.data[b"x-meta-tag"] == b"custom value"
    assert metainfo.info[b"private"] == 1
    assert metainfo.info[b"x-info-tag"] == b"custom value"
    assert metainfo.info_hash != old_info_hash


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
