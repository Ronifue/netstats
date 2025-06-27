import struct
import time
import hashlib
import json

class Packet:
    def __init__(self, sequence_number: int, data: bytes = b'', is_ack: bool = False, session_id: str = "0"): # Changed type and default
        self.session_id: str = str(session_id) # Ensure it's a string
        self.sequence_number = sequence_number
        self.timestamp = time.time() # Timestamp of creation (sender) or reception (receiver can overwrite)
        self.payload = data
        self.payload_size = len(data)
        self.is_ack = is_ack
        # Store the hash of the payload for integrity check
        self.payload_hash = self._calculate_hash(self.payload)

    def _calculate_hash(self, data: bytes) -> str:
        """Calculates MD5 hash of the data."""
        return hashlib.md5(data).hexdigest()

    def serialize(self) -> bytes:
        """Serializes the packet (metadata + payload) into bytes for sending."""
        metadata = {
            "sid": self.session_id,
            "sn": self.sequence_number,
            "ts": self.timestamp,
            "ps": self.payload_size,
            "ack": self.is_ack,
            "ph": self.payload_hash  # Hash of the payload
        }
        metadata_bytes = json.dumps(metadata, separators=(',', ':')).encode('utf-8')

        # Prepend metadata length (4 bytes, unsigned int, network byte order)
        metadata_len_bytes = struct.pack('!I', len(metadata_bytes))

        return metadata_len_bytes + metadata_bytes + self.payload

    @classmethod
    def deserialize_header(cls, metadata_bytes: bytes) -> dict | None:
        """Deserializes only the header part of the packet."""
        try:
            header = json.loads(metadata_bytes.decode('utf-8'))
            return header
        except json.JSONDecodeError as e:
            print(f"Error deserializing packet header: {e}")
            return None

    @classmethod
    def from_parts(cls, header: dict, payload_bytes: bytes) -> 'Packet | None':
        """Creates a Packet object from a deserialized header and payload bytes."""
        try:
            packet = cls(
                session_id=header["sid"],
                sequence_number=header["sn"],
                data=payload_bytes,
                is_ack=header.get("ack", False)
            )
            # Restore original timestamp and hash from the header
            packet.timestamp = header["ts"]
            packet.payload_hash = header["ph"] # The hash that was sent with the packet

            # It's crucial that the payload_size in the header matches len(payload_bytes)
            if header["ps"] != len(payload_bytes):
                print(f"Warning: Payload size mismatch. Header: {header['ps']}, Actual: {len(payload_bytes)}")
                # Depending on policy, might return None or raise an error
                # For now, we'll proceed but this is a sign of issues.

            return packet
        except KeyError as e:
            print(f"Error creating packet from parts, missing key: {e}")
            return None

    def verify_integrity(self) -> bool:
        """Verifies the integrity of the received payload against the hash in the header."""
        return self._calculate_hash(self.payload) == self.payload_hash

    def __repr__(self):
        return (f"Packet(SID={self.session_id}, Seq={self.sequence_number}, Time={self.timestamp:.3f}, "
                f"Size={self.payload_size}, ACK={self.is_ack}, SentHash='{self.payload_hash[:8]}...', "
                f"ActualHash='{self._calculate_hash(self.payload)[:8]}...')")

# Helper function to read exactly n bytes from a socket (typically for TCP)
def recv_all_from_socket(sock, n_bytes: int) -> bytes | None:
    """Reads exactly n_bytes from the socket. Returns None if connection is closed before all bytes are read."""
    data = bytearray()
    while len(data) < n_bytes:
        try:
            packet_chunk = sock.recv(n_bytes - len(data))
        except ConnectionResetError:
            print("Connection reset by peer during recv_all_from_socket.")
            return None
        except Exception as e:
            print(f"Socket error during recv_all_from_socket: {e}")
            return None

        if not packet_chunk: # Connection closed
            return None
        data.extend(packet_chunk)
    return bytes(data)

def read_packet_from_tcp_socket(sock) -> Packet | None:
    """Reads a complete packet (header + payload) from a TCP socket."""
    # 1. Read metadata length (4 bytes)
    metadata_len_bytes = recv_all_from_socket(sock, 4)
    if not metadata_len_bytes:
        return None # Connection closed or error

    try:
        metadata_len = struct.unpack('!I', metadata_len_bytes)[0]
    except struct.error as e:
        print(f"Error unpacking metadata length: {e}")
        return None

    # 2. Read metadata
    metadata_bytes = recv_all_from_socket(sock, metadata_len)
    if not metadata_bytes:
        return None # Connection closed or error

    header = Packet.deserialize_header(metadata_bytes)
    if not header:
        return None # Deserialization error

    # 3. Read payload based on payload_size from header
    payload_size = header.get("ps", 0)
    payload_bytes = b''
    if payload_size > 0:
        payload_bytes = recv_all_from_socket(sock, payload_size)
        if payload_bytes is None: # Check if None explicitly, as b'' is a valid empty payload
             print(f"Failed to read payload of size {payload_size} for packet SN: {header.get('sn')}")
             return None # Connection closed or error while reading payload
        if len(payload_bytes) != payload_size:
            print(f"Error: Expected payload of size {payload_size} but got {len(payload_bytes)} for SN: {header.get('sn')}")
            return None


    # 4. Construct the packet
    packet = Packet.from_parts(header, payload_bytes)
    if packet and not packet.verify_integrity():
        print(f"Integrity check failed for packet SID={packet.session_id}, SN={packet.sequence_number}")
        # Decide on policy: return None, or return packet and let caller handle bad integrity
        # For now, let's return it and the caller can check .verify_integrity()

    return packet
