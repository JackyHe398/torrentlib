"""Peer integration tests are currently disabled."""

# from datetime import datetime, timedelta
# from time import sleep
#
# import pytest
#
# from torrentlib import Peer, Torrent
#
# pytestmark = pytest.mark.integration
#
#
# def test_peer_connect_and_read():
#     torrent = Torrent("95eac181669f6e2e26a2513f9b2c9f6d3d4e0ec1", 0)
#     self_peer_id = "-robots-testing12345"
#     peer = Peer(("192.168.0.150", 50413), torrent, self_peer_id)
#
#     try:
#         peer.connect()
#         timeout = datetime.now() + timedelta(seconds=30)
#         while datetime.now() < timeout and not torrent.peers:
#             peer.read_all()
#             sleep(5)
#     finally:
#         peer.close()
#
#     assert peer is not None
