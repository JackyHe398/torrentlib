import base64

import pytest

from torrentlib import Torrent, TorrentStatus
from torrentlib.MagnetParser import MagnetParser


def test_from_magnet_parses_hex_hash_and_hints():
    info_hash = "0123456789abcdef0123456789abcdef01234567"
    torrent = Torrent.from_magnet(
        "magnet:?xt=urn:btih:" + info_hash.upper()
        + "&dn=Example%20File&xl=1234"
        + "&tr=udp%3A%2F%2Ftracker.example%3A80%2Fannounce"
        + "&tr=https%3A%2F%2Ftracker2.example%2Fannounce",
        downloaded=34,
        event=TorrentStatus.STOPPED,
    )

    assert torrent.info_hash == info_hash
    assert torrent.name == "Example File"
    assert torrent.total_size == 1234
    assert torrent.left == 1200
    assert torrent.event is TorrentStatus.STOPPED
    assert torrent.metainfo.data[b"announce"] == b"udp://tracker.example:80/announce"
    assert torrent.metainfo.data[b"announce-list"] == [
        [b"udp://tracker.example:80/announce"],
        [b"https://tracker2.example/announce"],
    ]


def test_from_magnet_converts_base32_hash():
    raw_hash = bytes.fromhex("0123456789abcdef0123456789abcdef01234567")
    encoded_hash = base64.b32encode(raw_hash).decode("ascii").lower()

    torrent = Torrent.from_magnet(f"magnet:?xt=urn:btih:{encoded_hash}")

    assert torrent.info_hash == raw_hash.hex()


def test_magnet_parser_retains_unknown_parameters():
    magnet = MagnetParser.parse(
        "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
        "&x.custom=one&x.custom=two"
    )

    assert magnet.parameters["x.custom"] == ("one", "two")


def test_from_magnet_adds_peer_endpoints():
    torrent = Torrent.from_magnet(
        "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
        "&x.pe=192.0.2.1%3A6881"
        "&x.pe=%5B2001%3Adb8%3A%3A1%5D%3A6882"
        "&x.pe=peer.example%3A6883"
        "&x.pe=invalid"
    )

    assert torrent.peers == {
        ("192.0.2.1", 6881): {},
        ("peer.example", 6883): {},
    }
    assert torrent.peers6 == {("2001:db8::1", 6882): {}}


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.com/file",
        "magnet:?dn=no-hash",
        "magnet:?xt=urn:btih:not-a-valid-hash",
    ],
)
def test_from_magnet_rejects_invalid_uri(uri):
    with pytest.raises(ValueError):
        Torrent.from_magnet(uri)


@pytest.mark.parametrize("size", ["abc", "-1"])
def test_from_magnet_rejects_invalid_size(size):
    with pytest.raises(ValueError, match="non-negative integer"):
        Torrent.from_magnet(
            "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
            f"&xl={size}"
        )
