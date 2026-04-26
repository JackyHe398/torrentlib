import socket
import bencodepy
import struct
from datetime import datetime
from typing import Optional, Any
from ..Torrent import Torrent
from .PeerCommunicationException import *

METADATA_PIECE_SIZE = 16384  # 16KB per piece (BEP 9 standard)


def _find_bencode_end(data: bytes, start: int = 0) -> int:
    """
    Return the index immediately after the first complete bencoded value.

    This is used for ut_metadata messages, which are framed as:
    <bencoded dict><raw metadata bytes>
    """
    def _parse_at(i: int) -> int:
        if i >= len(data):
            raise ValueError("Unexpected end of bencoded data")

        token = data[i:i + 1]

        if token == b'i':
            end = data.find(b'e', i + 1)
            if end == -1:
                raise ValueError("Unterminated bencode integer")
            return end + 1

        if token == b'l':
            i += 1
            while True:
                if i >= len(data):
                    raise ValueError("Unterminated bencode list")
                if data[i:i + 1] == b'e':
                    return i + 1
                i = _parse_at(i)

        if token == b'd':
            i += 1
            while True:
                if i >= len(data):
                    raise ValueError("Unterminated bencode dictionary")
                if data[i:i + 1] == b'e':
                    return i + 1
                i = _parse_at(i)  # key
                i = _parse_at(i)  # value

        if b'0' <= token <= b'9':
            colon = data.find(b':', i)
            if colon == -1:
                raise ValueError("Invalid bencode string length")
            try:
                strlen = int(data[i:colon])
            except ValueError as e:
                raise ValueError("Invalid bencode string length") from e
            end = colon + 1 + strlen
            if end > len(data):
                raise ValueError("Bencode string exceeds available data")
            return end

        raise ValueError(f"Invalid bencode token at offset {i}: {token!r}")

    return _parse_at(start)

def parse_pex_message(payload: bytes, peer_addr: Optional[tuple[str, int]] = None) -> dict:
    """
    Parse a PEX (Peer Exchange) message and extract peer lists.
    
    Args:
        payload: Bencoded PEX message payload
        peer_addr: Optional peer address (ip, port) for error messages
    
    Returns:
        Dictionary with 'added', 'added6', 'dropped', 'dropped6' peer lists.
        Each peer is a dict with 'ip', 'port', and optionally flags.
    """
    try:
        pex_data: dict[bytes, Any] = bencodepy.decode(payload) #type: ignore
        result = {'added': [], 'added6': [], 'dropped': [], 'dropped6': []}
        
        # Parse added peers (IPv4)
        if b'added' in pex_data:
            added_bytes = pex_data[b'added']
            flags_bytes = pex_data.get(b'added.f', b'')
            
            # Each peer is 6 bytes
            for offset in range(0, len(added_bytes), 6):
                if not(offset + 6 <= len(added_bytes)):
                    break
                peer_bytes = added_bytes[offset:offset + 6]
                flags = flags_bytes[offset//6] if offset//6 < len(flags_bytes) else 0 # Extract flags if available
                
                ip_packed, port = struct.unpack("!4sH", peer_bytes)
                # Extract IP (4 bytes)
                ip = socket.inet_ntoa(ip_packed)
                
                # build up peer info
                peer_info = {
                    'ip':  ip,
                    'port':  port,
                }
                
                if flags:
                    peer_info |= {
                        'encrypted': bool(flags & 0x01),
                        'seed': bool(flags & 0x02),
                        'utp': bool(flags & 0x04),
                        'holepunch': bool(flags & 0x08),
                        'outgoing': bool(flags & 0x10),
                    }
                
                result['added'].append(peer_info)
        
        # Parse IPv6 peers (18 bytes each) if present
        if b'added6' in pex_data:
            added6_bytes = pex_data[b'added6']
            flags6_bytes = pex_data.get(b'added6.f', b'')
            for offset in range(0, len(added6_bytes), 18):
                if not (offset + 18 <= len(added6_bytes)):
                    break
                peer_bytes = added6_bytes[offset:offset + 18]
                flags = flags6_bytes[offset//18] if offset//18 < len(flags6_bytes) else 0 # Extract flags if available
                
                ip_packed, port = struct.unpack("!16sH", peer_bytes)
                # Extract IPv6 address (16 bytes)
                ip = socket.inet_ntop(socket.AF_INET6, ip_packed)
                
                
                result['added6']. append({'ip': ip, 'port': port})
        
        # Parse dropped peers (IPv4)
        if b'dropped' in pex_data: 
            dropped_bytes = pex_data[b'dropped']
            
            for i in range(0, len(dropped_bytes), 6):
                if i + 6 <= len(dropped_bytes):
                    peer_data = dropped_bytes[i:i+6]
                    ip = '.'.join(str(b) for b in peer_data[0:4])
                    port = int.from_bytes(peer_data[4:6], 'big')
                    
                    result['dropped'].append({'ip': ip, 'port':  port})
        
        # Parse dropped IPv6 peers (18 bytes each)
        if b'dropped6' in pex_data:
            dropped6_bytes = pex_data[b'dropped6']
            for i in range(0, len(dropped6_bytes), 18):
                if i + 18 <= len(dropped6_bytes):
                    peer_data = dropped6_bytes[i:i+18]
                    # IPv6 address (16 bytes)
                    ipv6_bytes = peer_data[0:16]
                    ipv6 = ':'.join(f'{b:02x}' for b in ipv6_bytes)
                    port = int.from_bytes(peer_data[16:18], 'big')
                    
                    result['dropped6'].append({'ip': ipv6, 'port': port})
        
        return result
        
    except Exception as e:
        raise InvalidResponseException(peer_addr or ("unknown", 0), f"Failed to parse PEX message: {e}") from e

class Peer():
    def __init__(self, peer: tuple[str, int], torrent: Torrent, self_peer_id: str):
        # self status
        self.peer = peer
        self.torrent = torrent
        self.self_peer_id = self_peer_id
        self.last_keep_alive_sent: float = 0 # timestamp of last keep-alive sent
        
        # peer status
        self.peer_id: Optional[bytes] = None
        self.bitfield: Optional[bytes] = None
        self.peer_supports_extensions: Optional[bool] = None
        self.peer_extension_ids: dict[str, int] = {}
        
        # metadata tracking for multi-piece downloads
        self.metadata_size: Optional[int] = None  # Total metadata size in bytes
        self.metadata_pieces: dict[int, bytes] = {}  # {piece_index: piece_data}
        
        # constant
        self.TIMEOUT = 5  # seconds
        self.LOCAL_EXTENSIONS_IDS = {
            'ut_pex': 1,
            'ut_metadata': 2,
        }
        
        self.s: Optional[socket.socket] = None
        
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False
    
    def __repr__(self):
        status = "connected" if self._is_connected else "disconnected"
        return f"Peer({self.peer[0]}:{self.peer[1]}, {status})"

    def _is_connected(self) -> bool:        
        return self.s is not None and self.s.fileno() != -1
    
    # region - connect and disconnect
    def connect(self):
        """
        Connect to the peer and perform handshake.
        """
        if self._is_connected():
            return
        
        try:
            # Create and connect socket
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.s.settimeout(5)
            self.s.connect(self.peer)
            
            # Send handshake
            msg = b'\x13BitTorrent protocol'
            reserved = bytearray(8)
            reserved[5] |= 0x10
            msg += bytes(reserved)
            msg += bytes.fromhex(self.torrent.info_hash)
            msg += self.self_peer_id.encode('utf-8')
            self.sendall(msg)
            
            # Receive handshake response
            response = self.s.recv(68)
            
            # Validate response
            if len(response) < 68:
                raise InvalidResponseException(self.peer, "Incomplete handshake response")
            
            if response[0:20] != b'\x13BitTorrent protocol':
                raise InvalidResponseException(self.peer, "Invalid protocol")
            
            if response[28:48] != bytes. fromhex(self.torrent.info_hash):
                raise InvalidResponseException(self.peer, "Info hash mismatch")
            
            self.peer_id = response[48:68]
            reserved_bytes = response[20:28]
            self.peer_supports_extensions = bool(reserved_bytes[5] & 0x10)
            self.last_keep_alive = datetime.now().timestamp()
            
            if self.peer_supports_extensions:
                self.send_extension_handshake()
                self.read_all()

        except socket.timeout as e:
            self.close()
            raise ConnectionError(f"Connection to {self.peer} timed out")
        except socket.error as e:
            self.close()
            raise ConnectionError(f"Socket error connecting to {self.peer}:  {e}")
        except (InvalidResponseException, Exception) as e:
            self.close()
            raise
       
    def close(self):
        """Close connection to peer."""
        if self.s:
            try:
                self.s.close()
            except:
                pass
            finally:
                self.s = None
    # endregion
    
    # region - send messages and handshakes
    def sendall(self, data: bytes):
        assert self.s is not None, "Socket is not connected"
        self.last_keep_alive_sent = datetime.now().timestamp()
        self.s.sendall(data)
        
    def send_extension_handshake(self):
        """Send extension handshake with PEX support."""
        if not self._is_connected():
            raise SocketClosedException(self.peer)
        assert self.s is not None, "Socket is not connected" # just for type checker
        
        if not self.peer_supports_extensions:
            raise Exception("Peer doesn't support extensions")
        
        # Build extension handshake
        handshake_dict = {
            b'm': {k.encode(): v for k, v in self.LOCAL_EXTENSIONS_IDS.items()},
            b'v': b'MyTorrentLib 1.0',
        }
        
        # Bencode it
        payload = bencodepy.encode(handshake_dict)
        
        self.send_extended_msg(payload, 0)  # Extended ID 0 for handshake
        
    def request_metadata(self, piece: int = 0):
        """
        Request a specific metadata piece from peer using ut_metadata extension.
        
        Args:
            piece: Piece index to request (default: 0)
        """
        if not self._is_connected():
            raise SocketClosedException(self.peer)
        assert self.s is not None, "Socket is not connected" # just for type checker
        
        if 'ut_metadata' not in self.peer_extension_ids:
            print(self.peer_extension_ids)
            raise Exception("Peer doesn't support ut_metadata extension")
        
        # Build request message
        request_dict = {
            b'msg_type': 0,  # request
            b'piece': piece,
        }
        
        payload = bencodepy.encode(request_dict)
        
        # Send as Extended message (ID 20, extended ID for ut_metadata)
        extended_id = self.peer_extension_ids['ut_metadata']
        self.send_extended_msg(payload, extended_id)
    
    def request_all_metadata(self):
        """
        Request all metadata pieces from peer.
        Must be called after receiving extension handshake with metadata_size.
        """
        if self.metadata_size is None:
            raise Exception("Metadata size unknown. Wait for extension handshake.")
        
        # Calculate number of pieces needed
        num_pieces = (self.metadata_size + METADATA_PIECE_SIZE - 1) // METADATA_PIECE_SIZE
        
        # Request each piece
        for piece_idx in range(num_pieces):
            self.request_metadata(piece_idx)
        
    
    def send_extended_msg(self, payload: bytes, extended_id):
        assert self.s is not None, "Socket is not connected"
        
        # Send as Extended message (ID 20, with specified extended ID)
        length = 1 + 1 + len(payload)
        message = length.to_bytes(4, 'big')
        message += bytes([20])   # Message ID:  Extended
        message += bytes([extended_id])    # Extended ID (0 for handshake, or extension-specific ID)
        message += payload
        
        self.sendall(message)
        
    def send_keep_alive(self):
        """
        Send a keep-alive message to the peer (length prefix 0).
        """
        if not self._is_connected():
            raise SocketClosedException(self.peer)
        assert self.s is not None, "Socket is not connected"
        
        # Keep-alive message: <len=0000>
        message = (0).to_bytes(4, 'big')
        self.sendall(message)
        
    def send_piece_msg(self, index: int, begin: int, block: bytes):
        """
        Send a piece message to the peer (message ID 7).
        
        Args:
            index: Piece index (which piece)
            begin: Byte offset within the piece (where this block starts)
            block: The actual data block to send
        """
        assert self.s is not None, "Socket is not connected"
        
        # Message format: <len=0009+X><id=7><index><begin><block>
        length = 1 + 4 + 4 + len(block)  # id + index + begin + block
        message = length.to_bytes(4, 'big')
        message += bytes([7])  # Message ID: Piece
        message += index.to_bytes(4, 'big')
        message += begin.to_bytes(4, 'big')
        message += block
        
        self.sendall(message)
    # endregion
    

    # region - receive and parse messages
    def _receive_msg(self):
        """
        Receive exactly one message from the peer.
        
        Returns:
            A dictionary representing the message received.
            the change to status will be reflected on the Peer object.
        """
        def _recv_exact(num_bytes:  int) -> bytes:
            nonlocal self
            """
            Receive exactly num_bytes from the socket.
            
            Returns:
                Bytes received, or None if connection closed
                
            Raises:
                socket.timeout: If timeout expires
            """
            data = b''
            while len(data) < num_bytes:
                chunk = self.s.recv(num_bytes - len(data)) # type: ignore
                if not chunk:
                    # Connection closed by peer
                    raise SocketClosedException(self.peer)
                data += chunk
            return data
        if not self._is_connected():
            raise SocketClosedException(self.peer)
        assert self.s is not None, "Socket is not connected" # just for type checker
        
        length_data = _recv_exact(4)
        self.s.settimeout(self.TIMEOUT) # reset timeout due to <def _read_all()>
        length = int.from_bytes(length_data, byteorder='big')
        
        if length == 0:
            return {'type': 'keep-alive'}
        
        msg_id = _recv_exact(1)
        payload = _recv_exact(length - 1)
        
        if msg_id == b'\x00':
            return {'type': 'choke'}
        elif msg_id == b'\x01':
            return {'type': 'unchoke'}
        elif msg_id == b'\x02':
            return {'type': 'interested'}
        elif msg_id == b'\x03':
            return {'type': 'not_interested'}
        elif msg_id == b'\x04' and length == 5:
            index = int.from_bytes(payload[0:4], byteorder='big')
            self._update_bitfield(have_index=index)
            return {'type': 'have', 'index': index}
        elif msg_id == b'\x05':
            bitfield = payload
            self._update_bitfield(bitfield=bitfield)
            return {'type': 'bitfield', 'bitfield': bitfield}
        # this library is not serving as a full client, msg_id 6-8 will not be implemented
        elif msg_id == b'\x06':
            return { 'type': 'request'} 
        elif msg_id == b'\x07':
            return { 'type': 'piece'}
        elif msg_id == b'\x08':
            return { 'type': 'cancel'}
        elif msg_id == b'\x09':
            return { 'type': 'port'}   # TODO: Implement DHT port messages
        elif msg_id == b'\x14':  # 20 decimal = 0x14 hex (Extended message)
            self._handle_extended_message(payload=payload)
            return { 'type': 'extend'}
        
        raise InvalidResponseException(self.peer, f"Unknown message ID: {msg_id.hex()}")
    
    def _handle_extended_message(self, payload: bytes):
        """Handle extended messages (PEX, metadata, etc.)."""
        print("_handle_extended_message called")
        if not payload:
            raise InvalidResponseException(self.peer, "Empty extended message payload")
        extended_id = payload[0]
        payload = payload[1:]
        
        # Check if this is extension handshake
        if extended_id == 0:
            # Parse extension handshake
            ext_handshake: dict[bytes, Any] = bencodepy.decode(payload) #type: ignore
            
            # Check for supported extensions
            if b'm' in ext_handshake:
                m_dict: dict[bytes, int] = ext_handshake[b'm']
                for name, ext_id in m_dict.items():
                    name_str = name.decode('utf-8')
                    if name_str not in self.peer_extension_ids:
                        self.peer_extension_ids[name_str] = ext_id
            
            # Extract metadata_size if present (BEP 9)
            if b'metadata_size' in ext_handshake:
                self.metadata_size = ext_handshake[b'metadata_size']
                print(f"Peer has metadata: {self.metadata_size} bytes")
        
        # Check if this is PEX
        elif extended_id == self.LOCAL_EXTENSIONS_IDS.get('ut_pex'):
            pex_result = parse_pex_message(payload, self.peer)
            
            # Thread-safe peer dict modifications
            with self.torrent._peers_lock:
                for peer_info in pex_result['added']:
                    meta_data = {k: v for k, v in peer_info.items() if k not in ('ip', 'port')}
                    self.torrent.peers[(peer_info['ip'], peer_info['port'])] = meta_data
                    
                for peer_info in pex_result['added6']:
                    meta_data = {k: v for k, v in peer_info.items() if k not in ('ip', 'port')}
                    self.torrent.peers6[(peer_info['ip'], peer_info['port'])] = meta_data
                
                for peer_info in pex_result['dropped']:
                    ip = peer_info['ip']
                    port = peer_info['port']
                    if (ip, port) in self.torrent.peers:
                        del self.torrent.peers[(ip, port)]
                
                for peer_info in pex_result['dropped6']:
                    ip = peer_info['ip']
                    port = peer_info['port']
                    if (ip, port) in self.torrent.peers6:
                        del self.torrent.peers6[(ip, port)]
        
        # Check if this is metadata
        elif extended_id == self.LOCAL_EXTENSIONS_IDS.get('ut_metadata'): 
            self._handle_metadata_message(payload)
        
        else:
            return # TODO unsupported extended message
    
    def _handle_metadata_message(self, payload: bytes):
        """
        Handle ut_metadata message response and reassemble multiple pieces.
        
        The payload format is:
        - Bencoded dict with msg_type, piece, (optionally total_size)
        - Followed by actual metadata bytes if msg_type=1
        """
        print("handle_metadata_message called")

        try:
            # slice message
            dict_end = _find_bencode_end(payload)
            bencoded_dict = payload[:dict_end]
            metadata_bytes = payload[dict_end:]
            
            msg_dict: dict[bytes, Any] = bencodepy.decode(bencoded_dict)  # type: ignore
            msg_type = msg_dict.get(b'msg_type', -1)
            piece = msg_dict.get(b'piece', 0)
            
            if msg_type == 1:  # data
                # Successfully received metadata piece
                total_size = msg_dict.get(b'total_size')
                if total_size and self.metadata_size is None:
                    self.metadata_size = total_size
                
                # Store the piece
                if metadata_bytes:
                    self.metadata_pieces[piece] = metadata_bytes
                    print(f"Received metadata piece {piece}: {len(metadata_bytes)} bytes")
                    
                    # Check if we have all pieces
                    if self._is_metadata_complete():
                        self._assemble_metadata()
                    
            elif msg_type == 2:  # reject
                # Peer rejected our metadata request
                pass
                
            elif msg_type == 0:  # request
                def reject():
                    nonlocal self
                    response_payload = bencodepy.encode({b'msg_type': 2, b'piece': piece})
                    extended_id = self.peer_extension_ids.get('ut_metadata')
                    if extended_id is not None:
                        self.send_extended_msg(response_payload, extended_id)
                if self.torrent.metadata is None:
                    reject()
                    return
                # Peer is requesting metadata piece from us
                piece_offset = piece * METADATA_PIECE_SIZE
                piece_data = self.torrent.metadata[piece_offset:piece_offset + METADATA_PIECE_SIZE]
                
                # Only send if piece exists (valid range)
                if piece_data:
                    # Build response message
                    response_dict = {
                        b'msg_type': 1,  # data
                        b'piece': piece,
                        b'total_size': len(self.torrent.metadata),  # Include total size (BEP 9 recommended)
                    }
                    response_payload = bencodepy.encode(response_dict) + piece_data
                    
                    # Send response
                    extended_id = self.peer_extension_ids.get('ut_metadata')
                    if extended_id is not None:
                        self.send_extended_msg(response_payload, extended_id)
                else:
                    # Reject: piece out of range
                    reject()
                
        except Exception as e:
            raise InvalidResponseException(self.peer, f"Failed to parse metadata message: {e}") from e
    # endregion

    def _update_bitfield(self, bitfield: Optional[bytes] = None, have_index: Optional[int] = None):
        """Update the peer's bitfield."""
        if bitfield is not None:
            self.bitfield = bitfield
            
        if have_index is not None and self.bitfield is not None:
            byte_index = have_index // 8
            bit_index = have_index % 8
            
            if byte_index < len(self.bitfield):
                self.bitfield = (self.bitfield[:byte_index] +
                                 bytes([self.bitfield[byte_index] | (1 << (7 - bit_index))]) +
                                 self.bitfield[byte_index + 1:])
                
    
    
    def _is_metadata_complete(self) -> bool:
        """Check if all metadata pieces have been received."""
        if self.metadata_size is None:
            return False
        
        num_pieces = (self.metadata_size + METADATA_PIECE_SIZE - 1) // METADATA_PIECE_SIZE
        
        # Check if we have all pieces
        for i in range(num_pieces):
            if i not in self.metadata_pieces:
                return False
        
        return True
    
    def _assemble_metadata(self):
        """
        Reassemble metadata pieces into complete metadata and verify hash.
        """
        if not self._is_metadata_complete():
            raise Exception("Cannot assemble: metadata incomplete")
        
        # Sort pieces by index and concatenate
        sorted_pieces = sorted(self.metadata_pieces.items())
        full_metadata = b''.join(piece_data for _, piece_data in sorted_pieces)
        
        # Trim to exact size (last piece might be padded)
        if self.metadata_size:
            full_metadata = full_metadata[:self.metadata_size]
        
        # Update torrent with metadata (thread-safe, includes hash verification)
        try:
            self.torrent.update_from_metadata(full_metadata)
            import hashlib
            computed_hash = hashlib.sha1(full_metadata).hexdigest()
            print(f"Metadata assembled and verified: {len(full_metadata)} bytes, hash: {computed_hash[:16]}...")
        except ValueError as e:
            raise InvalidResponseException(self.peer, str(e)) from e
        
        # Clear pieces to free memory
        self.metadata_pieces.clear()
    

    def read_all(self):
        """Read all available data from the socket."""
        if not self._is_connected():
            raise SocketClosedException(self.peer)
        assert self.s is not None, "Socket is not connected"
        
        try:
            while True:
                # long timeout will be applied in the middle of _receive_msg
                self._receive_msg()
                self.s.settimeout(0.1) # short timeout from second receive for shorter blocks
        except socket.timeout:
            # Finish reading
            pass
        finally:
            self.s.settimeout(self.TIMEOUT)
