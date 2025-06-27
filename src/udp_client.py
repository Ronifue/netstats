import socket
import time
import struct
from .packet_handler import Packet
from .utils import generate_session_id # Added import

class UDPClient:
    def __init__(self, host: str, port: int, local_port: int = 0, session_id: str = None): # Added session_id
        self.server_address = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.session_id = session_id if session_id else generate_session_id() # Use provided or generate

        if local_port != 0:
            try:
                self.sock.bind(('', local_port)) # Bind to a specific local port if provided
                print(f"UDP Client bound to local port {local_port}")
            except socket.error as e:
                print(f"UDP Client: Failed to bind to local port {local_port}: {e}")
                # Decide if this is fatal or if it should proceed without binding
                # For now, let it proceed, OS will assign an ephemeral port if not bound.

        # Consider SO_RCVBUF and SO_SNDBUF if high throughput is needed
        # self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        # self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)

    # send_packet(self, packet: Packet) is the original method that takes a Packet object
    # For bandwidth test, we might want a send_packet_raw to avoid re-serializing if already done.

    def send_packet(self, packet: Packet) -> bool: # Original method
        try:
            serialized_packet = packet.serialize()
            self.sock.sendto(serialized_packet, self.server_address)
            return True
        except socket.error as e:
            print(f"UDP Client send error (send_packet) to {self.server_address}: {e}")
            return False

    def receive_packet(self, timeout: float = 1.0) -> tuple[Packet | None, tuple | None]: # Original method
        """Receives a packet. Returns (Packet, address_from) or (None, None) on timeout/error."""
        self.sock.settimeout(timeout)
        try:
            raw_data, addr = self.sock.recvfrom(65535) # Max UDP packet size (IP MTU considerations for real world)

            # For UDP, the entire datagram is one "packet" from socket's perspective
            # We need to parse it using our packet_handler logic

            # 1. Read metadata length (4 bytes)
            if len(raw_data) < 4:
                # print(f"UDP Client: Received data from {addr} too short for metadata length.")
                return None, addr

            metadata_len_bytes = raw_data[:4]
            try:
                metadata_len = struct.unpack('!I', metadata_len_bytes)[0]
            except struct.error: # Removed 'as e'
                # print(f"UDP Client: Error unpacking metadata length from {addr}")
                return None, addr

            # 2. Extract metadata and payload
            header_end = 4 + metadata_len
            if len(raw_data) < header_end:
                # print(f"UDP Client: Received data from {addr} too short for metadata (expected {metadata_len}).")
                return None, addr

            metadata_bytes = raw_data[4:header_end]
            payload_bytes = raw_data[header_end:]

            header = Packet.deserialize_header(metadata_bytes)
            if not header:
                # print(f"UDP Client: Failed to deserialize header from {addr}.")
                return None, addr

            expected_payload_size = header.get("ps", 0)
            if len(payload_bytes) != expected_payload_size:
                # print(f"UDP Client: Payload size mismatch from {addr}. Header: {expected_payload_size}, Actual: {len(payload_bytes)} for SN: {header.get('sn')}")
                return None, addr

            packet = Packet.from_parts(header, payload_bytes)
            # if packet:
            #     print(f"UDP Client Received from {addr}: {packet}, Integrity: {packet.verify_integrity()}")
            #     if not packet.verify_integrity():
            #         print(f"UDP Client: Packet SN {packet.sequence_number} from {addr} failed integrity check.")

            return packet, addr

        except socket.timeout:
            # This is an expected outcome, not necessarily an error.
            # print(f"UDP Client: Receive timeout from {self.server_address}.")
            return None, None
        except socket.error as e: # Other socket errors
            print(f"UDP Client receive socket error from {self.server_address}: {e}")
            return None, None
        except Exception as e: # Catch-all for other unexpected errors during parsing
            print(f"UDP Client unexpected error during receive from {self.server_address}: {e}")
            return None, None
        finally:
            # It's good practice to reset timeout if the socket is reused for other blocking operations later,
            # but for a dedicated client method like this, it might not be strictly necessary if each call sets its own.
            self.sock.settimeout(None)


    def close(self):
        if self.sock:
            print("Closing UDP client socket.")
            self.sock.close()
            self.sock = None

    def run_bandwidth_test(self, duration: int, packet_size: int, tickrate: int, ack_timeout: float = 0.1) -> dict:
        """
        Runs a UDP bandwidth and quality test towards the server.
        It expects ACKs from the server to calculate loss and RTT.
        """
        if tickrate <= 0:
            return {"error": "Tickrate must be positive.", "status": "failure"}
        if packet_size <= 0:
            return {"error": "Packet size must be positive.", "status": "failure"}
        if duration <= 0:
            return {"error": "Duration must be positive.", "status": "failure"}
        if ack_timeout <= 0:
            return {"error": "ACK timeout must be positive.", "status": "failure"}

        results = {
            "test_type": "udp_bandwidth_quality",
            "status": "running",
            "duration_configured_sec": duration,
            "packet_size_payload_bytes": packet_size,
            "tickrate_hz": tickrate,
            "ack_timeout_sec": ack_timeout,
            "total_packets_sent": 0,
            "total_bytes_payload_sent": 0,
            "total_bytes_protocol_sent": 0,
            "packets_acked": 0,
            "bytes_payload_acked": 0,
            "bytes_protocol_acked": 0,
            "packets_lost": 0,
            "loss_rate_percent": 0,
            "rtt_samples_ms": [],
            "avg_rtt_ms": 0,
            "min_rtt_ms": 0,
            "max_rtt_ms": 0,
            "jitter_ms": 0,
            "actual_duration_sec": 0,
            "send_errors": 0,
            "receive_errors": 0,
            "bandwidth_payload_acked_mbps": 0,
            "bandwidth_protocol_acked_mbps": 0,
            "start_time_unix": time.time(),
            "end_time_unix": 0,
            "events": [],
            "sent_packet_info": {},
            "session_id": self.session_id # Ensure session_id is in results
        }

        interval = 1.0 / tickrate
        start_time_monotonic = time.monotonic()
        end_time_expected_monotonic = start_time_monotonic + duration

        sequence_number = 0

        try:
            while time.monotonic() < end_time_expected_monotonic:
                loop_start_time_monotonic = time.monotonic()

                payload = b'Y' * packet_size
                current_packet_to_send = Packet(sequence_number=sequence_number, data=payload, session_id=self.session_id)
                serialized_packet_data = current_packet_to_send.serialize()

                send_time_unix = time.time()
                send_time_monotonic = time.monotonic()

                if self.send_packet_raw_udp(serialized_packet_data, self.server_address): # Use specific name
                    results["total_packets_sent"] += 1
                    results["total_bytes_payload_sent"] += current_packet_to_send.payload_size
                    results["total_bytes_protocol_sent"] += len(serialized_packet_data)
                    results["sent_packet_info"][sequence_number] = {
                        "send_time_unix": send_time_unix,
                        "send_time_monotonic": send_time_monotonic,
                        "payload_size": current_packet_to_send.payload_size,
                        "protocol_size": len(serialized_packet_data),
                        "acked": False
                    }

                    ack_packet, server_addr = self.receive_ack_packet(timeout=ack_timeout)

                    if ack_packet:
                        if ack_packet.is_ack and ack_packet.session_id == self.session_id and \
                           ack_packet.sequence_number in results["sent_packet_info"]: # check if SN is one we sent

                            original_sent_info = results["sent_packet_info"].get(ack_packet.sequence_number)

                            if original_sent_info and not original_sent_info["acked"]: # Process only if not already acked
                                original_sent_info["acked"] = True
                                results["packets_acked"] += 1
                                results["bytes_payload_acked"] += original_sent_info["payload_size"]
                                results["bytes_protocol_acked"] += original_sent_info["protocol_size"]

                                ack_receive_time_monotonic = time.monotonic() # Capture ACK receive time
                                rtt_ms = (ack_receive_time_monotonic - original_sent_info["send_time_monotonic"]) * 1000
                                results["rtt_samples_ms"].append(rtt_ms)
                            # else: duplicate ACK, already processed. Log if needed.
                            #    results["events"].append({"time": time.time(), "type": "duplicate_ack", "seq": ack_packet.sequence_number})
                        else: # Malformed/unexpected ACK (wrong SN, not an ACK, wrong session)
                           results["events"].append({"time": time.time(), "type": "malformed_ack", "details": f"SN: {ack_packet.sequence_number}, Expected SN from sent list, IsAck: {ack_packet.is_ack}, SID: {ack_packet.session_id}, Expected SID: {self.session_id}"})
                    elif server_addr is not None and ack_packet is None : # Got some data, but couldn't parse into Packet
                        results["receive_errors"] +=1
                        results["events"].append({"time": time.time(), "type": "malformed_server_packet", "details": f"Received unparseable data from {server_addr}"})
                    # If ack_packet is None and server_addr is None: timeout, considered a lost ACK (and thus lost packet for now)

                    sequence_number += 1
                else:
                    results["send_errors"] += 1
                    results["events"].append({"time": time.time(), "type": "send_error", "seq": sequence_number, "message": "send_packet_raw_udp returned false"})

                loop_end_time_monotonic = time.monotonic()
                elapsed_this_tick = loop_end_time_monotonic - loop_start_time_monotonic
                sleep_time = interval - elapsed_this_tick
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("Client UDP: Bandwidth test interrupted by user.")
            results["events"].append({"time": time.time(), "type": "interrupt", "message": "User interrupted test"})
            results["status"] = "interrupted"
        except Exception as e:
            print(f"Client UDP: Exception during bandwidth test: {e}")
            results["events"].append({"time": time.time(), "type": "exception", "message": str(e), "error_type": type(e).__name__})
            results["status"] = "error_exception"
        finally:
            results["end_time_unix"] = time.time()
            results["actual_duration_sec"] = time.monotonic() - start_time_monotonic

            if results["status"] == "running":
                results["status"] = "completed"

            results["packets_lost"] = results["total_packets_sent"] - results["packets_acked"]
            if results["total_packets_sent"] > 0:
                results["loss_rate_percent"] = (results["packets_lost"] / results["total_packets_sent"]) * 100 if results["total_packets_sent"] > 0 else 0

            rtt_samples = sorted(results["rtt_samples_ms"]) # Sort for easier min/max/percentile later
            results["rtt_samples_ms"] = rtt_samples # Store sorted
            if rtt_samples:
                results["avg_rtt_ms"] = sum(rtt_samples) / len(rtt_samples)
                results["min_rtt_ms"] = rtt_samples[0]
                results["max_rtt_ms"] = rtt_samples[-1]
                if len(rtt_samples) > 1:
                    # Jitter: Mean of absolute differences between consecutive RTTs
                    # sum_of_diffs_abs = sum(abs(rtt_samples[i] - rtt_samples[i-1]) for i in range(1, len(rtt_samples)))
                    # results["jitter_ms"] = sum_of_diffs_abs / (len(rtt_samples) - 1)

                    # More standard jitter calculation (RFC 3550 style for inter-arrival jitter, adapted for RTTs)
                    # D(i,j) = (Rj - Ri) - (Sj - Si) = (Rj - Sj) - (Ri - Si) where R is arrival, S is send time.
                    # This is equivalent to jitter of RTTs: J(i) = J(i-1) + (|delta(RTT)| - J(i-1))/16
                    # Simpler: standard deviation of RTTs or mean deviation.
                    # For now, let's use a simple mean of absolute differences of consecutive RTTs.
                    diffs = [abs(rtt_samples[i] - rtt_samples[i-1]) for i in range(1, len(rtt_samples))]
                    if diffs:
                         results["jitter_ms"] = sum(diffs) / len(diffs)
                    else: # only one RTT sample
                        results["jitter_ms"] = 0


            if results["actual_duration_sec"] > 0.001:
                bits_payload_acked = results["bytes_payload_acked"] * 8
                results["bandwidth_payload_acked_mbps"] = (bits_payload_acked / results["actual_duration_sec"]) / (1000 * 1000)

                bits_protocol_acked = results["bytes_protocol_acked"] * 8
                results["bandwidth_protocol_acked_mbps"] = (bits_protocol_acked / results["actual_duration_sec"]) / (1000 * 1000)
            else:
                results["bandwidth_payload_acked_mbps"] = 0
                results["bandwidth_protocol_acked_mbps"] = 0
                if results["status"] == "completed":
                     results["events"].append({"time": time.time(), "type": "warning", "message": "Test duration too short for meaningful bandwidth calculation."})

        # Decide how to handle sent_packet_info (it can be large)
        # Option: remove it from results, or summarize non-acked packets.
        # results["non_acked_sequences"] = [seq for seq, info in results["sent_packet_info"].items() if not info["acked"]]
        # For now, keep it for potential later analysis, but be mindful of size.
        # If printing, only print a summary.
        if len(results.get("sent_packet_info", {})) > 100 and "sent_packet_info" in results:
             results["events"].append({"time":time.time(), "type":"info", "message": f"Full sent_packet_info for {len(results['sent_packet_info'])} packets not shown in summary, but available in data."})
             # To make results smaller for printing:
             # results["sent_packet_info_summary"] = { "total_sent_for_info": len(results["sent_packet_info"]),
             #                                        "example_non_acked": [seq for seq, info in results["sent_packet_info"].items() if not info["acked"]][:5]}
             # del results["sent_packet_info"]


        return results

    def send_packet_raw_udp(self, data: bytes, server_addr: tuple) -> bool: # Renamed
        """Helper to send raw UDP bytes."""
        try:
            self.sock.sendto(data, server_addr)
            return True
        except socket.error: # Removed 'as e'
            # print(f"UDP Client send_packet_raw_udp error")
            return False

    def receive_ack_packet(self, timeout: float) -> tuple[Packet | None, tuple | None]:
        """Receives and parses a packet, typically an ACK."""
        return self.receive_packet(timeout=timeout) # Reuses existing general receive_packet


if __name__ == '__main__':
    from .utils import save_results_to_json # Relative import
    # try:
    #     from .utils import save_results_to_json
    # except ImportError:
    #     from utils import save_results_to_json # Fallback for direct script run

    print("UDP Client Example with Bandwidth Test")
    client = UDPClient("127.0.0.1", 9998)
    test_results = None # Initialize
    try:
        print("Starting UDP bandwidth & quality test for 5 seconds...")
        test_results = client.run_bandwidth_test(duration=5, packet_size=512, tickrate=20, ack_timeout=0.2)

        print("\n--- UDP Bandwidth/Quality Test Results (Client-Side) ---")
        results_to_print = dict(test_results)

        if "sent_packet_info" in results_to_print and isinstance(results_to_print["sent_packet_info"], dict) and len(results_to_print["sent_packet_info"]) > 10:
            print(f"sent_packet_info: Contains {len(results_to_print['sent_packet_info'])} entries. Example first 3:")
            for i, (k,v) in enumerate(list(results_to_print["sent_packet_info"].items())[:3]):
                print(f"  SN {k}: {v}")
            del results_to_print["sent_packet_info"]

        if "rtt_samples_ms" in results_to_print and isinstance(results_to_print["rtt_samples_ms"], list) and len(results_to_print["rtt_samples_ms"]) > 10:
            rtt_s = results_to_print["rtt_samples_ms"]
            print(f"rtt_samples_ms: {len(rtt_s)} samples. First 5: {rtt_s[:5]}...")
            del results_to_print["rtt_samples_ms"]

        for key, value in results_to_print.items():
            if key == "events" and isinstance(value, list) and value:
                print(f"Events ({len(value)}):")
                for item_idx, item in enumerate(value[:min(5, len(value))]):
                    print(f"  - {item}")
                if len(value) > 5:
                    print(f"    ... and {len(value) - 5} more.")
            elif isinstance(value, float):
                print(f"{key}: {value:.4f}")
            else:
                print(f"{key}: {value}")

    finally:
        print("Client: Closing UDP socket.")
        client.close()
        if test_results and test_results.get("status") != "failure":
            print(f"Client: Saving UDP test results for session {client.session_id}...")
            save_results_to_json(
                data=test_results,
                base_filename=f"udp_client_{client.server_address[0].replace('.', '_')}_{client.server_address[1]}",
                session_id_override=str(client.session_id)
            )
        elif test_results:
            print(f"Client: UDP Test results not saved due to status: {test_results.get('status')}")
