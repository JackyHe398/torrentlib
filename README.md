# torrentlib

Python helpers for BitTorrent tracker queries, peer communication, and metadata inspection.

`torrentlib` is not a full BitTorrent client. It can:

- load `.torrent` metadata
- announce to HTTP and UDP trackers
- collect IPv4 and IPv6 peer lists
- connect to peers that support the extension protocol
- download torrent metadata from peers via `ut_metadata`
- process peer exchange (`ut_pex`) messages

It does not manage piece downloads/uploads for complete content transfer.

## Installation

```bash
pip install torrentlib
```

Supports Python 3.10 through 3.14.

## Public API

```python
from torrentlib import Torrent, TorrentStatus, Peer
from torrentlib.Tracker import Check, Query
```

## Working With Torrents

Create a `Torrent` from a `.torrent` file when you already have metadata:

```python
from torrentlib import Torrent

torrent = Torrent.from_file("example.torrent")

print(torrent)
print(torrent.name)
print(torrent.info_hash)
print(torrent.total_size)
print(torrent.piece_length)
print(torrent.num_pieces)

files = torrent.get_files_info()
if files:
    for file_hash, file_info in files.items():
        print(file_hash, file_info["name"], file_info["length"])
```

Create a minimal `Torrent` when you only have an info hash, for example from a magnet link:

```python
from torrentlib import Torrent, TorrentStatus

torrent = Torrent(
    info_hash="1234567890abcdef1234567890abcdef12345678"
)

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
```

## Tracker Health Checks

`Check` provides simple tracker reachability checks. Use `Check.auto()` when you want protocol detection from the URL scheme.

```python
from torrentlib.Tracker import Check

print(Check.auto("http://tracker.example.com:8080/announce", timeout=5))
print(Check.auto("udp://tracker.example.com:6969/announce", timeout=5))

print(Check.http("http://tracker.example.com:8080/announce", timeout=5))
print(Check.udp("udp://tracker.example.com:6969/announce", timeout=5))

trackers = [
    "http://tracker1.example.com:8080/announce",
    "udp://tracker2.example.com:6969/announce",
]

results = Check.multiple(trackers, timeout=5)
for url, is_online in results.items():
    print(url, is_online)
```

## Tracker Queries

Tracker queries operate on a `Torrent` object, not a raw `info_hash`. The library reads `torrent.left`, `torrent.downloaded`, `torrent.uploaded`, and `torrent.event` from that object.

`Query.single()` chooses HTTP or UDP based on the tracker URL:

```python
from torrentlib import Torrent, TorrentStatus
from torrentlib.Tracker import Query

torrent = Torrent(
    info_hash="1234567890abcdef1234567890abcdef12345678",
    event=TorrentStatus.STARTED,
)
peer_id = "-robots-testing12345"

response = Query.single(
    torrent=torrent,
    url="udp://tracker.opentrackr.org:1337/announce",
    peer_id=peer_id,
    port=6881,
    timeout=10,
)

print(response["interval"])
print(response.get("seeders"))
print(response.get("leechers"))
print(len(response.get("peers", [])))
print(len(response.get("peers6", [])))
```

You can also query multiple trackers concurrently:

```python
from torrentlib.Tracker import Query

responses = Query.multi(
    torrent=torrent,
    urls=[
        "udp://tracker.opentrackr.org:1337/announce",
        "http://tracker.example.com:8080/announce",
    ],
    peer_id=peer_id,
    port=6881,
    timeout=10,
)

for url, result in responses.items():
    if "error" in result:
        print(url, result["error"])
    else:
        print(url, len(result.get("peers", [])))
```

Successful tracker queries automatically merge returned peers into:

- `torrent.peers` for IPv4 peers
- `torrent.peers6` for IPv6 peers

## Peer Communication

Use `Peer` as a context manager. Connecting performs the BitTorrent handshake. If the remote peer supports extensions, the library also sends an extension handshake and reads the initial extension messages.

```python
from time import sleep
from torrentlib import Peer, Torrent

torrent = Torrent(info_hash="1234567890abcdef1234567890abcdef12345678")
peer_id = "-robots-testing12345"
peer_addr = ("127.0.0.1", 6881)

with Peer(peer_addr, torrent, peer_id) as peer:
    print(peer)
    print(peer.peer_supports_extensions)
    print(peer.peer_extension_ids)

    sleep(2)
    peer.read_all()

    print(len(torrent.peers))
    print(len(torrent.peers6))
```

To keep long-lived connections open, call `send_keep_alive()` periodically yourself:

```python
import threading
from time import sleep
from torrentlib import Peer, Torrent
from torrentlib.Peer.PeerCommunicationException import SocketClosedException

def keep_alive_loop(peer: Peer, stop_event: threading.Event, interval: int = 120):
    while not stop_event.is_set():
        sleep(interval)
        try:
            peer.send_keep_alive()
        except SocketClosedException:
            break

torrent = Torrent(info_hash="1234567890abcdef1234567890abcdef12345678")
peer_id = "-robots-testing12345"
peer_addr = ("127.0.0.1", 6881)
stop_event = threading.Event()

try:
    with Peer(peer_addr, torrent, peer_id) as peer:
        thread = threading.Thread(
            target=keep_alive_loop,
            args=(peer, stop_event),
            daemon=True,
        )
        thread.start()
        peer.read_all()
finally:
    stop_event.set()
```

## Metadata Download

If you start with only an info hash, you can fetch metadata from a peer that supports `ut_metadata`. Once the full metadata is assembled and verified, the library updates the existing `Torrent` object in place.

```python
from torrentlib import Peer, Torrent

torrent = Torrent(info_hash="1234567890abcdef1234567890abcdef12345678")
peer_id = "-robots-testing12345"
peer_addr = ("127.0.0.1", 6881)

with Peer(peer_addr, torrent, peer_id) as peer:
    if peer.metadata_size is not None:
        peer.request_all_metadata()
        peer.read_all()

    if torrent.metadata is not None:
        print("Metadata downloaded")
        print(torrent.name)
        print(torrent.total_size)

        files = torrent.get_files_info()
        if files:
            for file_hash, file_info in files.items():
                print(file_hash, file_info["name"], file_info["length"])
```

## Magnet To Metadata Example

```python
from torrentlib import Peer, Torrent, TorrentStatus
from torrentlib.Tracker import Query

info_hash = "1234567890abcdef1234567890abcdef12345678"
tracker_url = "udp://tracker.opentrackr.org:1337/announce"
peer_id = "-robots-testing12345"

torrent = Torrent(info_hash=info_hash, event=TorrentStatus.STARTED)

response = Query.single(
    torrent=torrent,
    url=tracker_url,
    peer_id=peer_id,
    port=6881,
)

for peer_addr in response.get("peers", [])[:5]:
    try:
        with Peer(peer_addr, torrent, peer_id) as peer:
            if peer.metadata_size is None:
                continue

            peer.request_all_metadata()
            peer.read_all()

            if torrent.metadata is not None:
                print(torrent)
                files = torrent.get_files_info()
                if files:
                    for _, file_info in files.items():
                        print(file_info["name"], file_info["length"])
                break
    except Exception:
        continue
```

## Error Handling

Tracker exceptions live in `torrentlib.Tracker.TrackerQueryException`:

```python
from torrentlib import Torrent, TorrentStatus
from torrentlib.Tracker import Query
from torrentlib.Tracker.TrackerQueryException import (
    TrackerQueryException,
    TimeoutError,
    BadRequestError,
    InvalidResponseError,
    UnexpectedError,
)

torrent = Torrent(
    info_hash="1234567890abcdef1234567890abcdef12345678",
    event=TorrentStatus.STARTED,
)

try:
    Query.single(
        torrent=torrent,
        url="http://tracker.example.com/announce",
        peer_id="-robots-testing12345",
    )
except TimeoutError:
    print("Tracker request timed out")
except BadRequestError:
    print("Tracker rejected the request")
except InvalidResponseError:
    print("Tracker returned malformed data")
except UnexpectedError as exc:
    print(f"Unexpected tracker error: {exc}")
except TrackerQueryException as exc:
    print(f"Tracker error: {exc}")
```

Peer communication exceptions live in `torrentlib.Peer.PeerCommunicationException`:

```python
from torrentlib.Peer.PeerCommunicationException import (
    PeerCommunicationException,
    SocketClosedException,
    InvalidResponseException,
)
```

## Notes

- `TorrentStatus` currently provides `COMPLETED`, `STARTED`, and `STOPPED`.
- `Torrent.get_files_info()` returns `None` until metadata is available.
- `Torrent.update_from_metadata()` verifies that received metadata matches the original info hash.
- `Query.single()` and `Query.multi()` update the `Torrent` peer caches automatically.

## License

MIT. See [LICENSE](LICENSE).
