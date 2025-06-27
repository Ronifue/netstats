import socket
import threading
import struct # For unpacking metadata length
import time
from .packet_handler import Packet
from .utils import save_results_to_json # Added

class UDPServer:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._running = threading.Event()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.client_sessions = {}
        self.client_sessions_lock = threading.Lock()


    def _get_or_create_client_session(self, client_addr_str: str, session_id_from_packet: int) -> dict:
        with self.client_sessions_lock:
            session = self.client_sessions.get(client_addr_str)
            if not session or (session.get("session_id") != session_id_from_packet and session_id_from_packet is not None):
                if session:
                    print(f"UDP Server: New session ID {session_id_from_packet} from {client_addr_str}. Previous SID was {session.get('session_id')}. Archiving old & starting new.")
                    # Save the old session before replacing it
                    old_session_data = session.copy() # Make a copy to avoid modification issues
                    old_session_data["end_time_unix"] = time.time() # Mark its end time
                    old_session_data["events"].append({"time": old_session_data["end_time_unix"], "type":"info", "message": "Session superseded by new SID."})
                    if old_session_data.get("total_packets_received", 0) > 0:
                         save_results_to_json(
                            data=old_session_data,
                            base_filename=f"udp_server_session_{client_addr_str.replace(':','_').replace('.','_')}_superseded",
                            session_id_override=str(old_session_data.get("session_id"))
                        )

                session = {
                    "client_address": client_addr_str,
                    "session_id": session_id_from_packet,
                    "start_time_unix": time.time(),
                    "end_time_unix": 0, # Updated when session ends or server stops
                    "total_packets_received": 0,
                    "total_bytes_payload_received": 0,
                    "total_bytes_protocol_received": 0,
                    "expected_sequence_number": 0,
                    "lost_packets_inferred": 0,
                    "out_of_order_packets": 0,
                    "duplicate_packets_detected_on_server": 0, # Based on SNs server has seen
                    "corrupted_packets": 0,
                    "received_packet_details": [], # (client_ts, server_ts, seq, payload_size, integrity_ok, one_way_latency_ms)
                    "events": [],
                    "last_packet_time_unix": time.time(),
                    "first_packet_sn": None,
                    "received_sn_set": set() # For duplicate detection
                }
                self.client_sessions[client_addr_str] = session
                print(f"UDP Server: Created new session for {client_addr_str} with SID {session_id_from_packet}")

            # Update last packet time for existing session
            session["last_packet_time_unix"] = time.time()
            return session

    def start(self): # Modified server loop
        if self._running.is_set():
            print("UDP Server is already running.")
            return

        try:
            self.sock.bind((self.host, self.port))
            self._running.set()
            print(f"UDP Server listening on {self.host}:{self.port}")
            self.sock.settimeout(1.0)

            while self._running.is_set():
                try:
                    raw_data, addr = self.sock.recvfrom(65535)
                    server_recv_time_unix = time.time()
                    client_addr_str = f"{addr[0]}:{addr[1]}"

                    # --- Packet Deserialization (from existing logic) ---
                    if len(raw_data) < 4:
                        continue
                    metadata_len_bytes = raw_data[:4]
                    try:
                        metadata_len = struct.unpack('!I', metadata_len_bytes)[0]
                    except struct.error:
                        continue

                    header_end = 4 + metadata_len
                    if len(raw_data) < header_end:
                        continue
                    metadata_bytes = raw_data[4:header_end]
                    payload_bytes = raw_data[header_end:]
                    header = Packet.deserialize_header(metadata_bytes)
                    if not header:
                        continue

                    expected_payload_size = header.get("ps", 0)
                    if len(payload_bytes) != expected_payload_size:
                        continue

                    packet = Packet.from_parts(header, payload_bytes)
                    if not packet:
                        continue
                    # --- End Packet Deserialization ---

                    # Get or create session for this client address and packet's session_id
                    session = self._get_or_create_client_session(client_addr_str, packet.session_id)

                    # If it's an ACK packet sent TO the server (unlikely for this design, but check)
                    if packet.is_ack:
                        session["events"].append({"time": server_recv_time_unix, "type": "info", "message": f"Received an ACK packet (SN:{packet.sequence_number}) from client, usually not expected by server."})
                        continue

                    # Initialize or reset expected_sequence_number based on first_packet_sn or SN 0
                    if session.get("first_packet_sn") is None:
                        session["first_packet_sn"] = packet.sequence_number
                        session["expected_sequence_number"] = packet.sequence_number
                        print(f"UDP Server: First data packet for SID {packet.session_id} from {addr}. SN {packet.sequence_number}. Aligning expected SN.")
                        session["received_sn_set"].clear() # Clear for new stream segment
                    elif packet.sequence_number == 0 and session["total_packets_received"] > 0 and \
                         (packet.sequence_number < session["expected_sequence_number"] or session["expected_sequence_number"] > 100): # Heuristic for reset
                        print(f"UDP Server: Detected SN reset to 0 from {addr} (SID {packet.session_id}). Re-aligning.")
                        session["events"].append({"time": server_recv_time_unix, "type": "info", "message": "Client SN reset to 0, re-aligning."})
                        session["expected_sequence_number"] = 0
                        session["first_packet_sn"] = 0 # Mark that new stream starts at 0
                        session["received_sn_set"].clear() # Clear for new stream segment

                    # Duplicate Check
                    if packet.sequence_number in session["received_sn_set"]:
                        session["duplicate_packets_detected_on_server"] += 1
                        session["events"].append({"time": server_recv_time_unix, "type": "duplicate_server", "seq": packet.sequence_number})
                        # Send ACK for duplicate as client might have missed the first ACK
                        ack_payload_dup = f"ACK_DUP_S{packet.session_id}_N{packet.sequence_number}".encode()
                        ack_packet_dup = Packet(sequence_number=packet.sequence_number, session_id=packet.session_id, is_ack=True, data=ack_payload_dup)
                        self.sock.sendto(ack_packet_dup.serialize(), addr)
                        continue  # Skip further processing for this duplicate

                    session["received_sn_set"].add(packet.sequence_number)
                    # Optional: Implement eviction for received_sn_set if it grows too large for very long tests
                    # e.g. if len(session["received_sn_set"]) > MAX_SET_SIZE: remove oldest items.

                    integrity_ok = packet.verify_integrity()
                    if not integrity_ok:
                        session["corrupted_packets"] += 1
                        session["events"].append({"time": server_recv_time_unix, "type": "integrity_error", "seq": packet.sequence_number})

                    # Count non-duplicate packets for these stats
                    session["total_packets_received"] += 1
                    session["total_bytes_payload_received"] += packet.payload_size
                    session["total_bytes_protocol_received"] += len(raw_data)

                    one_way_latency_ms = (server_recv_time_unix - packet.timestamp) * 1000
                    session["received_packet_details"].append({
                        "client_ts": packet.timestamp, "server_ts": server_recv_time_unix,
                        "seq": packet.sequence_number, "payload_size": packet.payload_size,
                        "integrity_ok": integrity_ok, "one_way_latency_ms": one_way_latency_ms
                    })

                    # Sequence number checking for non-duplicates
                    if packet.sequence_number == session["expected_sequence_number"]:
                        session["expected_sequence_number"] += 1
                    elif packet.sequence_number > session["expected_sequence_number"]:
                        lost_count = packet.sequence_number - session["expected_sequence_number"]
                        session["lost_packets_inferred"] += lost_count
                        session["events"].append({"time": server_recv_time_unix, "type": "loss_inferred_server", "expected": session["expected_sequence_number"], "received": packet.sequence_number, "count": lost_count})
                        session["expected_sequence_number"] = packet.sequence_number + 1
                    else: # packet.sequence_number < session["expected_sequence_number"] (and not a duplicate)
                        session["out_of_order_packets"] += 1
                        session["events"].append({"time": server_recv_time_unix, "type": "out_of_order_server", "expected": session["expected_sequence_number"], "received": packet.sequence_number})

                    ack_payload_content = f"ACK_S{packet.session_id}_N{packet.sequence_number}".encode()
                    ack_packet = Packet(
                        sequence_number=packet.sequence_number, # Acking this sequence number
                        session_id=packet.session_id,      # For this session
                        is_ack=True,
                        data=ack_payload_content # Small payload for ACK
                    )
                    serialized_ack = ack_packet.serialize()
                    self.sock.sendto(serialized_ack, addr)  # Send ACK to original sender addr

                except socket.timeout:
                    continue
                except ConnectionResetError as e:
                    # Safely use addr and client_addr_str if they were defined in the try block
                    addr_str_for_log = addr if 'addr' in locals() else 'unknown address'
                    client_addr_str_for_log = client_addr_str if 'client_addr_str' in locals() else 'unknown_client'
                    print(f"UDP Server: ConnectionResetError potentially related to {addr_str_for_log}: {e}.")

                    if 'client_addr_str' in locals() and client_addr_str: # Ensure client_addr_str was defined
                        with self.client_sessions_lock:
                            if client_addr_str in self.client_sessions:
                                session_to_save = self.client_sessions.pop(client_addr_str)
                                session_to_save["end_time_unix"] = time.time()
                                session_to_save["events"].append({"time":session_to_save["end_time_unix"], "type":"error", "message": f"Session for {client_addr_str_for_log} ended due to ConnectionResetError: {e}"})
                                print(f"UDP Server: Saving and removing session for {client_addr_str_for_log} due to ConnectionResetError.")
                                if session_to_save.get("total_packets_received", 0) > 0:
                                    save_results_to_json(
                                        data=session_to_save,
                                        base_filename=f"udp_server_session_{client_addr_str.replace(':','_').replace('.','_')}_connreset", # Use original client_addr_str for filename consistency
                                        session_id_override=str(session_to_save.get("session_id"))
                                    )
                except socket.error as e:  # Other socket errors
                    current_addr_for_log = addr if 'addr' in locals() else 'unknown_address'
                    if self._running.is_set():
                        print(f"UDP Server socket error: {e} for client {current_addr_for_log}")
                    if not self._running.is_set():
                        break  # Server is stopping
                except Exception as e:
                    if self._running.is_set():
                        print(f"UDP Server unexpected error: {e} ({type(e).__name__})")

        except socket.error as e:
            print(f"UDP Server bind error on {self.host}:{self.port}: {e}")
        finally:
            self._running.clear()
            # Log final summaries for all active sessions before closing
            self._log_all_session_summaries()
            if self.sock:
                print("UDP Server shutting down socket.")
                self.sock.close()
                self.sock = None

    def _log_all_session_summaries(self):
        print("\n--- UDP Server: Saving Final Session Summaries at Shutdown ---")
        with self.client_sessions_lock:
            if not self.client_sessions:
                print("No active UDP sessions to save at shutdown.")
                return

            active_sessions_at_shutdown = list(self.client_sessions.items()) # Iterate over a copy
            for addr_str, session_data in active_sessions_at_shutdown:
                session_data["end_time_unix"] = time.time()
                actual_duration = session_data["end_time_unix"] - session_data["start_time_unix"]
                if actual_duration > 0.001 and session_data.get("total_bytes_payload_received", 0) > 0:
                    payload_bps = (session_data["total_bytes_payload_received"] * 8) / actual_duration
                    session_data["bandwidth_payload_mbps_calc_server"] = payload_bps / (1000 * 1000)

                # Print summary before saving (optional, can be verbose)
                print(f"  Saving session for {addr_str} (SID: {session_data.get('session_id', 'N/A')}) Duration: {actual_duration:.2f}s, Packets: {session_data.get('total_packets_received')}")

                if session_data.get("session_id") is not None and session_data.get("total_packets_received", 0) > 0:
                    save_results_to_json(
                        data=session_data,
                        base_filename=f"udp_server_session_{addr_str.replace(':','_').replace('.','_')}_shutdown",
                        session_id_override=str(session_data.get("session_id"))
                    )
            self.client_sessions.clear() # Clear after saving all
        print("-----------------------------------------------------------\n")

    def stop(self):
        print("Attempting to stop UDP server...")
        self._running.clear()
        if self.sock:
            # Wake up recvfrom by sending a tiny packet to the server's own address if it's stuck
            # This is a common trick if socket.close() isn't immediately unblocking recvfrom on some OS.
            # However, the timeout on recvfrom should make this unnecessary.
            try:
                self.sock.sendto(b'stop', (self.host if self.host != "0.0.0.0" else "127.0.0.1", self.port))
            except Exception:
                pass # Ignore if it fails (e.g. socket already closed)
            self.sock.close() # This should cause recvfrom to error out if running
        print("UDP Server stop signal sent.")

    def get_all_session_data_udp(self): # Specific name to avoid conflict if merging
        with self.client_sessions_lock:
            # Return a deep copy if modification by caller is a concern
            return list(self.client_sessions.values())


if __name__ == '__main__': # Main remains similar
    print("UDP Server Example")
    server = UDPServer("0.0.0.0", 9998)
    server_thread = threading.Thread(target=server.start)
    server_thread.daemon = True # Allow main to exit even if server thread is stuck (for testing)

    print("Starting UDP server...")
    server_thread.start()

    try:
        while server_thread.is_alive():
            cmd = input("Type 'stop' to shutdown the server, or 'stats' to view session data: \n")
            if cmd.strip().lower() == 'stop':
                break
            elif cmd.strip().lower() == 'stats':
                all_data = server.get_all_session_data_udp()
                if not all_data:
                    print("No UDP session data collected yet.")
                for i, session_summary in enumerate(all_data):
                    print(f"\n--- Session {i+1} Summary (from stats command) ---")
                    for k, v_val in session_summary.items():
                        if k == "received_packet_details" and isinstance(v_val, list):
                            print(f"  {k}: {len(v_val)} entries, e.g., {v_val[0] if v_val else 'N/A'}")
                        elif k == "events" and isinstance(v_val, list):
                            print(f"  {k}: {len(v_val)} events, e.g., {v_val[0] if v_val else 'N/A'}")
                        else:
                            print(f"  {k}: {v_val}")
                    print("------------------------------------")


            time.sleep(0.2) # Reduce CPU usage for input loop
    except KeyboardInterrupt:
        print("Keyboard interrupt received by main UDP server.")
    finally:
        print("Main: Initiating UDP server stop...")
        server.stop()
        server_thread.join(timeout=3)
        if server_thread.is_alive():
            print("Main: UDP Server thread did not terminate cleanly in time.")
        print("Main: UDP Server shutdown sequence complete.")
