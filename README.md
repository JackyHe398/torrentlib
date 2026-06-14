# torrentlib

Python helpers for BitTorrent tracker queries, peer communication, and metadata inspection.

`torrentlib` is not a full BitTorrent client. It can:

- load `.torrent` metadata
- announce to HTTP and UDP trackers
- collect IPv4 and IPv6 peer lists
- connect to peers and download metadata
- process peer exchange (`ut_pex`) messages
- edit and rebuild `.torrent` files

It does not manage piece downloads/uploads for complete content transfer.

## Installation

```bash
pip install torrentlib
```

Supports Python 3.10 through 3.14.

## Public API

```python
from torrentlib import Torrent, TorrentMetaInfo, TorrentStatus, Peer
from torrentlib.Tracker import Check, Query
```

## Usage 

Please refer to the [Wiki](https://github.com/JackyHe398/torrentlib/wiki) for detailed usage examples and API reference.

## License
MIT. See [LICENSE](LICENSE).
