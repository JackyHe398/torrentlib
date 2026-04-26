import requests
import struct
import random
import socket
import logging
from bencodepy import decode as bdecode, exceptions as bexceptions
from urllib.parse import urlparse
from collections.abc import Iterable


class Check:
    @staticmethod
    def http(url: str, timeout: int = 5) -> bool:
        """
        Check if a given HTTP tracker URL is reachable and returns a status code.
        """
        info_hash_hex = '8a19577fb5f690970ca43a57ff1011ae202244b8'
        info_hash_bytes = bytes.fromhex(info_hash_hex)

        headers = {
            "User-Agent": "qBittorrent/4.5.2",  # Mimic a known client
            "Accept": "*/*",
            "Connection": "close"
        }

        params = {
            'info_hash': info_hash_bytes,
            'peer_id': '-robots-testing12345',
            'left': '0',
            'port': '6881',
            'downloaded': '0',
            'uploaded': '0',
            'event': 'stopped',
        }

        try:
            response = requests.get(url,
                                    headers=headers,
                                    params=params,
                                    allow_redirects=True,
                                    timeout=timeout)
        except requests.exceptions.Timeout as e:
            logging.debug(f"❌ {url}: Timeout - {e}")
            return False
        except requests.exceptions.RequestException as e:
            logging.debug(f"❌ {url}: Unexpected error - {e}")
            return False
        
        sc = response.status_code
        if sc == 200:
            logging.debug(f"✅ {url}: Active")
            try: 
                bdecode(response.content)
                return True
            except bexceptions.DecodingError as e:
                logging.debug(f"❌ {url}: Invalid response format - {e}")
                return False
        elif sc == 400: 
            logging.debug(f"⚠️ {url}: Active, (400) Bad Request")
            return False
        else:
            logging.debug(f"⚠️ Responded but not valid: {url} ({response.status_code})")
            return False

    @staticmethod
    def udp(url: str, timeout: int = 5) -> bool:
        """
        Check if a given UDP tracker URL is reachable and responds correctly.
        """
        def response_validator(response, id)-> bool:
            if len(response) < 16:
                logging.debug(f"❌ {url}: Response too short")
                return False
            action, transaction_id, connection_id = struct.unpack("!iiq", response[:16])
            if action == ACTION and transaction_id == id:
                logging.debug(f"✅ {url}: Active")
                return True
            else:
                logging.debug(f"❌ {url}: Invalid response")
                return False
            
        parsed = urlparse(url)
        HOSTNAME = parsed.hostname
        PORT = parsed.port

        # Constants
        PROTOCOL_ID = 0x41727101980    # 8-byte magic number
        ACTION = 0                     # Connect = 0
        id = random.randint(0, 0xFFFF)  # Random 4-byte integer

        # Create packet: ! means network byte order (big-endian)
        packet = struct.pack("!qii", PROTOCOL_ID, ACTION, id)

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)  # Optional: wait up to 5 seconds

        try:
            s.sendto(packet, (HOSTNAME, PORT))
            response, addr = s.recvfrom(1024)  # buffer size can be adjusted
            # You can unpack the response here depending on expected format
            return response_validator(response, id)
        except socket.timeout:
            print(f"❌ {url}: Request timed out")
            return False
        finally:
            s.close()

    @staticmethod
    def auto(url: str, timeout: int = 5) -> bool:
        """
        Check tracker URL based on its scheme (http or udp).
        """
        if url.startswith("http"):
            return Check.http(url, timeout=timeout)
        elif url.startswith("udp"):
            return Check.udp(url, timeout=timeout)
        else:
            logging.debug(f"❌ Unsupported scheme: {url}")
            return False
        
    @staticmethod
    def multiple(urls: Iterable, max_threads=50, timeout: int = 5):
        """
        Check multiple tracker status concurrently
        """
        import threading
        semaphore = threading.Semaphore(max_threads)
        def threaded_check(url):
            with semaphore:
                result = Check.auto(url, timeout=timeout)
                results[url] = result

        results = {}
        threads = []

        for url in urls:
            t = threading.Thread(target=threaded_check, args=(url,))
            t.start()
            threads.append(t)

        for t in threads:
            t.join()


        # Final list of active trackers
        logging.info("\n\n\n🧲 Active Trackers List:")
        for url, status in results.items():
            if status:
                logging.info(url)
        
        return results
