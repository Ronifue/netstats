import unittest
import time
import os
import sys
import struct

# Add src to path to allow direct import of src modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from packet_handler import Packet

class TestPacketHandler(unittest.TestCase):

    def test_packet_creation_and_serialization(self):
        p1 = Packet(sequence_number=1, data=b"hello", session_id="test_sid_123")
        self.assertEqual(p1.sequence_number, 1)
        self.assertEqual(p1.payload, b"hello")
        self.assertEqual(p1.session_id, "test_sid_123")
        self.assertFalse(p1.is_ack)
        self.assertIsNotNone(p1.timestamp)
        self.assertEqual(p1.payload_size, 5)
        self.assertIsNotNone(p1.payload_hash)

        serialized_data = p1.serialize()
        self.assertIsInstance(serialized_data, bytes)
        self.assertTrue(len(serialized_data) > p1.payload_size) # Header + payload

    def test_packet_deserialization_and_integrity(self):
        original_data = b"example data for integrity check"
        p_orig = Packet(sequence_number=10, data=original_data, session_id="integrity_test")

        serialized_full_packet = p_orig.serialize()

        # Simulate receiving this data (as done in read_packet_from_tcp_socket or UDP server)
        metadata_len = struct.unpack('!I', serialized_full_packet[:4])[0]
        metadata_bytes = serialized_full_packet[4 : 4 + metadata_len]
        payload_bytes_received = serialized_full_packet[4 + metadata_len:]

        header_info = Packet.deserialize_header(metadata_bytes)
        self.assertIsNotNone(header_info)
        self.assertEqual(header_info["sn"], 10)
        self.assertEqual(header_info["sid"], "integrity_test")
        self.assertEqual(header_info["ps"], len(original_data))

        p_new = Packet.from_parts(header_info, payload_bytes_received)
        self.assertIsNotNone(p_new)

        self.assertEqual(p_new.sequence_number, p_orig.sequence_number)
        self.assertEqual(p_new.payload, p_orig.payload)
        self.assertEqual(p_new.session_id, p_orig.session_id)
        # Compare the sent hash (from original packet's header) with the new packet's stored sent hash
        self.assertEqual(p_new.payload_hash, p_orig.payload_hash)

        self.assertTrue(p_new.verify_integrity())

    def test_packet_integrity_failure(self):
        original_data = b"good data"
        p_orig = Packet(sequence_number=20, data=original_data, session_id="integrity_fail_test")

        serialized_full_packet = p_orig.serialize()

        metadata_len = struct.unpack('!I', serialized_full_packet[:4])[0]
        metadata_bytes = serialized_full_packet[4 : 4 + metadata_len]
        # Tamper with payload after serialization (as if corrupted in transit)
        corrupted_payload_bytes = original_data + b"_corrupted"

        header_info = Packet.deserialize_header(metadata_bytes)
        self.assertIsNotNone(header_info)
        # header_info["ps"] would still be len(original_data) as per sender.
        # If a real corruption changed payload length, then from_parts might also fail if
        # it strictly checks header["ps"] against len(payload_bytes_received).
        # For this test, we assume payload length itself wasn't corrupted, only content.

        p_corrupted = Packet.from_parts(header_info, corrupted_payload_bytes)
        self.assertIsNotNone(p_corrupted)
        # p_corrupted.payload_hash is the hash from the *sender's original data* (from header_info).
        # verify_integrity() calculates hash of *corrupted_payload_bytes*.
        self.assertFalse(p_corrupted.verify_integrity())


    def test_ack_packet(self):
        p_ack = Packet(sequence_number=5, is_ack=True, session_id="ack_sid", data=b"ACK_D")
        self.assertTrue(p_ack.is_ack)
        self.assertEqual(p_ack.payload, b"ACK_D")

        serialized_ack = p_ack.serialize()

        metadata_len = struct.unpack('!I', serialized_ack[:4])[0]
        metadata_bytes = serialized_ack[4 : 4 + metadata_len]
        payload_bytes_ack = serialized_ack[4 + metadata_len:]

        header_info = Packet.deserialize_header(metadata_bytes)
        self.assertIsNotNone(header_info)
        self.assertTrue(header_info["ack"])

        p_new_ack = Packet.from_parts(header_info, payload_bytes_ack)
        self.assertIsNotNone(p_new_ack)
        self.assertTrue(p_new_ack.is_ack)
        self.assertEqual(p_new_ack.payload, b"ACK_D")
        self.assertTrue(p_new_ack.verify_integrity())

    def test_empty_payload_packet(self):
        p_empty = Packet(sequence_number=30, data=b"", session_id="empty_payload_test")
        self.assertEqual(p_empty.payload_size, 0)
        self.assertTrue(p_empty.verify_integrity()) # Hash of empty string should match

        serialized_empty = p_empty.serialize()
        metadata_len = struct.unpack('!I', serialized_empty[:4])[0]
        metadata_bytes = serialized_empty[4 : 4 + metadata_len]
        payload_bytes_empty = serialized_empty[4 + metadata_len:]

        self.assertEqual(len(payload_bytes_empty), 0)

        header_info = Packet.deserialize_header(metadata_bytes)
        self.assertIsNotNone(header_info)
        self.assertEqual(header_info["ps"], 0)

        p_new_empty = Packet.from_parts(header_info, payload_bytes_empty)
        self.assertIsNotNone(p_new_empty)
        self.assertEqual(p_new_empty.payload_size, 0)
        self.assertEqual(p_new_empty.payload, b"")
        self.assertTrue(p_new_empty.verify_integrity())


if __name__ == '__main__':
    unittest.main()
```
