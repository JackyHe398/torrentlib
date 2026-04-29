from pathlib import Path

from torrentlib import TorrentMetaInfo


def test_torrent_metainfo_export_round_trip(tmp_path):
    torrent_path = Path(__file__).with_name("ubuntu-26.04-desktop-amd64.iso.torrent")
    export_path = tmp_path / "example-private.torrent"

    metainfo = TorrentMetaInfo.from_file(str(torrent_path))
    old_info_hash = metainfo.info_hash

    metainfo.data[b"announce"] = b"https://tracker.example.com/announce"
    metainfo.data[b"announce-list"] = [
        [b"https://tracker.example.com/announce"],
        [b"udp://tracker2.example.com:6969/announce"],
    ]
    metainfo.info[b"private"] = 1
    metainfo.info[b"x-info-tag"] = b"custom value"
    metainfo.refresh()
    metainfo.to_file(str(export_path))

    exported = TorrentMetaInfo.from_file(str(export_path))

    assert exported.info_hash == metainfo.info_hash
    assert exported.info_hash != old_info_hash
    assert exported.data[b"announce"] == b"https://tracker.example.com/announce"
    assert exported.data[b"announce-list"][1][0] == b"udp://tracker2.example.com:6969/announce"
    assert exported.info[b"private"] == 1
    assert exported.info[b"x-info-tag"] == b"custom value"
