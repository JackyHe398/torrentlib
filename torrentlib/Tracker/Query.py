import requests
import struct
import random
import socket
import bencodepy as bec
import builtins
from typing import Dict, Any
from urllib.parse import urlparse

from ..Torrent import Torrent, TorrentStatus
from .TrackerQueryException import (
    TrackerQueryException,
    TimeoutError,
    BadRequestError, 
    InvalidResponseError,
    UnexpectedError
)

# example_hash = '8a19577fb5f690970ca43a57ff1011ae202244b8'
# example_peer_id = '-robots-testing12345'


def _get_peer_from_bytes(response: bytes) -> list[tuple]:
    """
    Extracts peer information from the UDP response.
    """
    result = []
    offset = 0
    
    while offset + 6 <= len(response):
        peer_bytes = response[offset:offset + 6]
        ip_packed, port = struct.unpack("!4sH", peer_bytes)
        ip = socket.inet_ntoa(ip_packed)
        result.append((ip, port))
        offset += 6
    
    return result

def _get_peer6_from_bytes(response: bytes) -> list[tuple]:
    """
    Extracts peer information from the UDP response for IPv6.
    """
    result = []
    offset = 0
    
    while offset + 18 <= len(response):
        peer_bytes = response[offset:offset + 18]
        ip_packed, port = struct.unpack("!16sH", peer_bytes)
        ip = socket.inet_ntop(socket.AF_INET6, ip_packed)
        result.append((ip, port))
        offset += 18
    
    return result


def _parse_http_tracker_response(response_bdecode: dict[bytes, Any]) -> Dict[str, Any]:
    """
    Parse bencode response and decode all byte strings.
    """
    response = response_bdecode.copy()  # Don't mutate input
    try: 
        response[b"peers"] = _get_peer_from_bytes(response[b"peers"])
    except KeyError: # handle missing keys, not standard BEP behavior
        response[b"peers"] = []
    if b"peers6" in response:
        response[b"peers6"] = _get_peer6_from_bytes(response[b"peers6"])

    response_decoded = {}
    for k, v in response.items():
        if b'ip' in k:  # if the key contains 'ip', decode with inet_ntoa
            # Check if it's IPv4 (4 bytes) or IPv6 (16 bytes)
            if len(v) == 4:
                v = socket.inet_ntoa(v)
            elif len(v) == 16:
                v = socket.inet_ntop(socket.AF_INET6, v)
        try:
            response_decoded[k.decode()] = v.decode() if isinstance(v, bytes) else v
        except (UnicodeDecodeError, AttributeError):
            response_decoded[k.decode()] = v

    return response_decoded


def _validate_udp_connect_response(response: bytes, transaction_id: int, url: str) -> int:
    """
    Validate UDP connect response and return connection ID.
    """
    if len(response) < 16:
        raise InvalidResponseError(url=url, message="UDP connect response too short")
    action, resp_transaction_id, connection_id = struct.unpack("!iiq", response[:16])
    if action != 0 or resp_transaction_id != transaction_id:
        raise InvalidResponseError(url=url)
    return connection_id


def _parse_udp_announce_response(response: bytes, expected_transaction_id: int) -> Dict[str, Any]:
    """
    Parse UDP announce response.
    """
    if len(response) < 20:
        raise InvalidResponseError(message="UDP announce response too short")
    header = response[:20]
    peer_bytes = response[20:]
    
    action, transaction_id, interval, leechers, seeders = struct.unpack("!iiiii", header)
    if action != 1:
        raise InvalidResponseError(
            message=f"Invalid action: expected 1 (announce), got {action}"
        )
    if transaction_id != expected_transaction_id:
        raise InvalidResponseError(
            message=f"Transaction ID mismatch: expected {expected_transaction_id}, got {transaction_id}"
        )
    
    return {
        "interval": interval,
        "leechers": leechers,
        "seeders": seeders,
        "peers": _get_peer_from_bytes(peer_bytes)  # no ipv6 peer in udp
    }


def _format_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Standardize tracker response format.
    """
    if "failure reason" in result:
        return result
    
    # Create clean output without mutating input
    formatted = {
        "interval": result.get("interval"),
        "min interval": result.get("min interval"),
        "leechers": result.get("incomplete") or result.get("leechers"),
        "seeders": result.get("complete") or result.get("seeders"),
        "peers": result.get("peers"),
        "peers6": result.get("peers6")
    }
    
    # Include any other keys not already handled
    for key in result:
        if key not in ("complete", "incomplete", "interval", "min interval", "leechers", "seeders", "peers", "peers6"):
            formatted[key] = result[key]
    
    return formatted


class Query:
    @staticmethod
    def http(torrent: Torrent,
            url: str,
            peer_id: str,
            ip_addr: str|None = None,
            num_want: int|None = None, key: int = 0,
            port: int = 6881, headers: dict|None = None,
            timeout: int = 5) -> Dict[str, Any]:
        """
        Query HTTP/HTTPS tracker.
        """
        # Build request parameters
        info_hash_bytes = bytes.fromhex(torrent.info_hash)

        headers = headers or {
            "User-Agent": "qBittorrent/4.5.2",
            "Accept": "*/*",
            "Connection": "close"
        }

        params = {
            'info_hash': info_hash_bytes,
            'peer_id': peer_id,
            'port': str(port),
            'left': str(torrent.left),
            'downloaded': str(torrent.downloaded),
            'uploaded': str(torrent.uploaded),
            'event': torrent.event.name.lower(),  # Convert TorrentStatus to string
        }

        if ip_addr: params['ip'] = ip_addr
        if num_want: params['numwant'] = str(num_want)
        if key: params['key'] = str(key)

        # Make request
        try:
            response = requests.get(url,
                                    headers=headers,
                                    params=params,
                                    allow_redirects=True,
                                    timeout=timeout)
            
            status_code = response.status_code // 100 * 100  # Get the first digit of the status code
            if status_code == 200:
                try:
                    decoded_response = bec.decode(response.content)
                except Exception as e:
                    raise InvalidResponseError(url=url, message="Failed to decode tracker response") from e

                if not isinstance(decoded_response, dict):
                    raise InvalidResponseError(url=url, message="Tracker response is not a dictionary")

                response_bdecode = dict(decoded_response)
                response_decode = _parse_http_tracker_response(response_bdecode)
                
                # Update torrent with peers
                if "peers" in response_decode:
                    torrent.peers |= {i: {} for i in response_decode["peers"]}
                if "peers6" in response_decode:
                    torrent.peers6 |= {i: {} for i in response_decode["peers6"]}
                    
                return _format_result(response_decode)
            elif status_code == 300:
                raise UnexpectedError(url=url, message="Redirection not supported")
            elif status_code == 400:
                raise BadRequestError(url=url)
            else:
                raise InvalidResponseError(url=url)
        except (requests.exceptions.Timeout, builtins.TimeoutError) as e:
            # Catch both requests timeout and built-in socket timeout
            raise TimeoutError(url=url) from e
        except InvalidResponseError:
            raise
        except requests.exceptions.RequestException as e:
            raise UnexpectedError(url=url, e=e)


    @staticmethod
    def udp(torrent: Torrent,
            url: str,
            peer_id: str,
            ip_addr: str = "0.0.0.0",
            num_want: int = 50, key: int = 0,
            port: int = 6881,
            timeout: int = 5) -> Dict[str, Any]:
        """
        Query UDP tracker.
        """
        # region - define constants and params
        parsed = urlparse(url)
        HOSTNAME = parsed.hostname
        PORT = parsed.port

        PROTOCOL_ID = 0x41727101980    # 8-byte magic number
        TRANSACTION_ID = random.randint(0, 0xFFFF)  # Random 4-byte integer
        
        
        ip_bytes = socket.inet_aton(ip_addr)
        # endregion

        # Create packet: ! means network byte order (big-endian)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)

        try:
            # region - initialize connection
            packet = struct.pack("!qii", PROTOCOL_ID, 0, TRANSACTION_ID)  # ACTION: connect
            s.sendto(packet, (HOSTNAME, PORT))
            response, addr = s.recvfrom(1024)
            CONNECTION_ID = _validate_udp_connect_response(response, TRANSACTION_ID, url)
            # endregion

            # region - announce query
            packet = struct.pack(
                "!qii20s20sqqqi4siiH",
                CONNECTION_ID,
                1,  # ACTION: announce
                TRANSACTION_ID,
                bytes.fromhex(torrent.info_hash),
                peer_id.encode("utf-8")[:20].ljust(20, b"-"),
                torrent.downloaded,
                torrent.left,
                torrent.uploaded,
                torrent.event.value, 
                ip_bytes,
                key,
                num_want,
                port or 6881
            )
            s.sendto(packet, (HOSTNAME, PORT))
            response, addr = s.recvfrom(1024)
            # endregion
            
        except socket.timeout:
            raise TimeoutError(url=url)
        except socket.error as e:
            raise UnexpectedError(url=url, e=e)
        finally:
            s.close()
        
        # Parse response and update torrent
        parsed_response = _parse_udp_announce_response(response, TRANSACTION_ID)
        
        if "peers" in parsed_response:
            torrent.peers |= {i: {} for i in parsed_response["peers"]}
            
        return _format_result(parsed_response)

    @staticmethod
    def single(torrent: Torrent,
                url: str,
                peer_id: str,  
                ip_addr: str|None = None,
                num_want = None, key = None,
                port: int|None = None, headers = None,
                timeout: int|None = None) -> Dict[str, Any]:

        # region - arguement preparing
        args: Dict[str, Any] = {
            "torrent": torrent,
            "url": url,
            "peer_id": peer_id
        }

        if ip_addr is not None: args["ip_addr"] = ip_addr
        if num_want is not None: args["num_want"] = num_want
        if key is not None: args["key"] = key
        if port is not None: args["port"] = port
        if timeout is not None: args["timeout"] = timeout
        # endregion
            
        if url.startswith("http"):
            if headers is not None: args["headers"] = headers
            return Query.http(**args)
        elif url.startswith("udp"):
            return Query.udp(**args)
        else:
            raise TrackerQueryException(message="Unsupported URL scheme", url=url)
    
    @staticmethod
    def multi(torrent: Torrent,
                urls: list[str],
                peer_id: str,  
                ip_addr: str|None = None,
                num_want = None, key = None,
                port: int|None = None, headers = None,
                timeout: int|None = None, max_threads: int = 50) -> Dict[str, Dict[str, Any]]:
        import threading
        semaphore = threading.Semaphore(max_threads)
        result = {}
        result_lock = threading.Lock()  # Thread-safe writes
        threads = []  # Keep track of threads
        
        def threaded_check(url):
            with semaphore:
                try:
                    response = Query.single(torrent, url, peer_id,
                                       ip_addr=ip_addr,
                                       num_want=num_want, key=key, port=port, headers=headers, timeout=timeout)
                    with result_lock:
                        result[url] = response
                except Exception as e:
                    with result_lock:
                        result[url] = {"error": str(e)}  # Store error in result instead of printing

        for url in urls:
            threaded = threading.Thread(target=threaded_check, args=(url,))
            threaded.start()
            threads.append(threaded)  # Keep track of the thread
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
            
        return result
