import socket
import threading
import time
from .packet_handler import Packet, read_packet_from_tcp_socket
from .utils import save_results_to_json # Added for saving results

class TCPServer:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock = None
        self._running = threading.Event()
        self.clients: dict[socket.socket, str] = {}
        self._lock = threading.Lock()
        # self.all_session_data = [] # We'll save sessions individually now
        # self.all_session_data_lock = threading.Lock()


    def _handle_client(self, conn: socket.socket, addr: tuple):
        client_addr_str = f"{addr[0]}:{addr[1]}"
        print(f"TCP Server: New connection from {client_addr_str}")
        with self._lock:
            self.clients[conn] = client_addr_str

        # Per-client session data
        current_session_data = {
            "client_address": client_addr_str,
            "session_id": None,
            "start_time_unix": time.time(),
            "end_time_unix": 0,
            "total_packets_received": 0,
            "total_bytes_payload_received": 0,
            "total_bytes_protocol_received": 0,
            "expected_sequence_number": 0,
            "lost_packets_inferred": 0,
            "out_of_order_packets": 0,
            "duplicate_packets": 0, # Not fully implemented yet, needs SN tracking
            "corrupted_packets": 0,
            "received_packet_details": [], # (client_ts, server_ts, seq, payload_size, integrity_ok, latency_ms)
            "events": [],
            "last_packet_time_unix": time.time()
        }

        conn_active = True
        is_new_test_stream = True # To handle sequence number resets for multiple tests on same connection

        try:
            while self._running.is_set() and conn_active:
                packet = read_packet_from_tcp_socket(conn)

                if packet:
                    server_recv_time_unix = time.time()
                    current_session_data["last_packet_time_unix"] = server_recv_time_unix

                    if current_session_data["session_id"] is None: # First packet from this client connection
                        current_session_data["session_id"] = packet.session_id

                    # If client indicates a new test by resetting sequence number to 0 (and it's not the very first packet)
                    if packet.sequence_number == 0 and not is_new_test_stream and current_session_data["total_packets_received"] > 0 :
                        print(f"TCP Server: Detected SN reset to 0 from {addr} (SID: {packet.session_id}). Assuming new test stream.")
                        current_session_data["events"].append({
                            "time": server_recv_time_unix, "type": "info", "message": "Sequence number reset to 0, re-aligning."
                        })
                        current_session_data["expected_sequence_number"] = 0
                        # Old "lost_packets_inferred" are for the previous stream part, so we might want to log them separately
                        # or reset this counter if we are only interested in the current stream.
                        # For now, let's keep accumulating unless specifically segmented.

                    is_new_test_stream = False # No longer the first packet of a potential new stream

                    integrity_ok = packet.verify_integrity()
                    if not integrity_ok:
                        current_session_data["corrupted_packets"] += 1
                        msg = f"Packet SN {packet.sequence_number} failed integrity check."
                        # print(f"TCP Server from {addr}: {msg}") # Can be verbose
                        current_session_data["events"].append({"time": server_recv_time_unix, "type": "integrity_error", "seq": packet.sequence_number, "message": msg})

                    current_session_data["total_packets_received"] += 1
                    current_session_data["total_bytes_payload_received"] += packet.payload_size

                    serialized_packet_for_size = packet.serialize() # Need to serialize to get actual protocol size
                    current_session_data["total_bytes_protocol_received"] += len(serialized_packet_for_size)

                    latency_ms = (server_recv_time_unix - packet.timestamp) * 1000 # One-way latency
                    current_session_data["received_packet_details"].append({
                        "client_ts": packet.timestamp,
                        "server_ts": server_recv_time_unix,
                        "seq": packet.sequence_number,
                        "payload_size": packet.payload_size,
                        "integrity_ok": integrity_ok,
                        "latency_ms": latency_ms
                    })

                    if packet.sequence_number == current_session_data["expected_sequence_number"]:
                        current_session_data["expected_sequence_number"] += 1
                    elif packet.sequence_number > current_session_data["expected_sequence_number"]:
                        lost_count = packet.sequence_number - current_session_data["expected_sequence_number"]
                        current_session_data["lost_packets_inferred"] += lost_count
                        current_session_data["events"].append({"time": server_recv_time_unix, "type": "loss_inferred", "seq_expected": current_session_data["expected_sequence_number"], "seq_received": packet.sequence_number, "count": lost_count})
                        current_session_data["expected_sequence_number"] = packet.sequence_number + 1
                    else: # packet.sequence_number < current_session_data["expected_sequence_number"]
                        current_session_data["out_of_order_packets"] += 1
                        current_session_data["events"].append({"time": server_recv_time_unix, "type": "out_of_order_or_duplicate", "seq_expected": current_session_data["expected_sequence_number"], "seq_received": packet.sequence_number})

                    if packet.payload == b"TEST_ENDED_GRACEFULLY" and packet.sequence_number == -1:
                        print(f"TCP Server: Received TEST_ENDED_GRACEFULLY from {addr} (SID: {packet.session_id}).")
                        current_session_data["events"].append({"time": server_recv_time_unix, "type": "test_end_signal", "message": "Client signaled end of test."})
                        conn_active = False
                else:
                    current_session_data["events"].append({"time": time.time(), "type": "connection_read_eof_or_error", "message": "read_packet_from_tcp_socket returned None."})
                    conn_active = False

        except ConnectionResetError:
            msg = f"Connection reset by {addr}."
            print(f"TCP Server: {msg}")
            current_session_data["events"].append({"time": time.time(), "type": "connection_reset", "message": msg})
        except socket.timeout:
            msg = f"Socket timeout for client {addr}."
            print(f"TCP Server: {msg}")
            current_session_data["events"].append({"time": time.time(), "type": "socket_timeout", "message": msg})
        except Exception as e:
            if self._running.is_set():
                 msg = f"Error handling client {addr}: {e}"
                 print(f"TCP Server: {msg}")
                 current_session_data["events"].append({"time": time.time(), "type": "exception_handling_client", "message": msg, "error_type": type(e).__name__})
        finally:
            current_session_data["end_time_unix"] = time.time()
            actual_duration = current_session_data["end_time_unix"] - current_session_data["start_time_unix"]

            if actual_duration > 0.001 and current_session_data["total_bytes_payload_received"] > 0:
                payload_bps = (current_session_data["total_bytes_payload_received"] * 8) / actual_duration
                current_session_data["bandwidth_payload_mbps_calculated"] = payload_bps / (1000 * 1000)
                protocol_bps = (current_session_data["total_bytes_protocol_received"] * 8) / actual_duration
                current_session_data["bandwidth_protocol_mbps_calculated"] = protocol_bps / (1000*1000)

            # --- Print Session Summary ---
            print(f"\n--- TCP Server: Session Summary for {client_addr_str} (SID: {current_session_data.get('session_id', 'N/A')}) ---")
            summary_keys = ["client_address", "session_id", "start_time_unix", "end_time_unix",
                            "total_packets_received", "total_bytes_payload_received", "total_bytes_protocol_received",
                            "lost_packets_inferred", "out_of_order_packets", "corrupted_packets",
                            "bandwidth_payload_mbps_calculated", "bandwidth_protocol_mbps_calculated"]
            for key in summary_keys:
                if key in current_session_data:
                    value = current_session_data[key]
                    if isinstance(value, float) and ("mbps" in key or "_unix" in key):
                        print(f"  {key}: {value:.3f}")
                    else:
                        print(f"  {key}: {value}")
            print(f"  Actual Duration: {actual_duration:.3f} sec")

            event_count = len(current_session_data["events"])
            if event_count > 0:
                print(f"  Noteworthy events ({event_count}):")
                for event in current_session_data["events"][:min(3, event_count)]: # Print first few
                    print(f"    - Time: {event.get('time'):.2f}, Type: {event.get('type')}, Details: {event.get('message', event.get('seq', ''))}")
                if event_count > 3: print(f"    ... and {event_count - 3} more events.")
            print("-----------------------------------\n")
            # --- End Session Summary ---

            # Save current_session_data to a file
            if current_session_data.get("session_id") is not None and \
               current_session_data.get("total_packets_received", 0) > 0:
                print(f"TCP Server: Saving session data for SID {current_session_data['session_id']} from {client_addr_str}...")
                save_results_to_json(
                    data=current_session_data,
                    base_filename=f"tcp_server_session_{client_addr_str.replace(':', '_').replace('.', '_')}",
                    session_id_override=str(current_session_data["session_id"])
                )
            else:
                print(f"TCP Server: Session data for {client_addr_str} not saved (no SID or no packets).")


            with self._lock:
                if conn in self.clients:
                    del self.clients[conn]
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except socket.error: pass
            conn.close()
            print(f"TCP Server: Closed connection for {addr}")

    # def get_all_session_data(self): # Not strictly needed if saving individually
    #     # If we still want to aggregate in memory for some reason:
    #     # with self.all_session_data_lock:
    #     #     return list(self.all_session_data)
    #     pass


    def start(self):
        if self._running.is_set():
            print("TCP Server is already running.")
            return

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Set a timeout on the server listening socket to allow periodic checks of _running flag
        self.sock.settimeout(1.0) # Timeout for accept()

        try:
            self.sock.bind((self.host, self.port))
            self.sock.listen(5) # Max 5 pending connections
            self._running.set() # Signal that server is now running
            print(f"TCP Server listening on {self.host}:{self.port}")

            while self._running.is_set():
                try:
                    conn, addr = self.sock.accept()
                    # Set timeout for individual client connections if desired
                    # conn.settimeout(60) # e.g., 60 seconds inactivity timeout
                    client_thread = threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True)
                    client_thread.start()
                except socket.timeout:
                    # This is expected due to self.sock.settimeout(1.0)
                    # Allows the loop to check self._running.is_set()
                    continue
                except socket.error as e:
                    if self._running.is_set(): # Only log if we weren't trying to stop
                        print(f"TCP Server accept error: {e}")
                    break # Exit loop on other socket errors
        except socket.error as e:
            print(f"TCP Server bind/listen error: {e}")
            self._running.clear() # Ensure it's marked as not running
            if self.sock:
                self.sock.close()
                self.sock = None
        finally:
            self._running.clear() # Ensure it's marked as not running on any exit
            if self.sock:
                print("TCP Server shutting down listening socket.")
                self.sock.close()
                self.sock = None
            # Wait for client handler threads? Not strictly necessary with daemon=True
            # but good for cleaner shutdown if there's shared state to save.

    def stop(self):
        print("Attempting to stop TCP server...")
        self._running.clear() # Signal all loops to stop

        # Close the listening socket to unblock accept() and stop new connections
        if self.sock:
            # No need for dummy connection if accept() has a timeout
            self.sock.close()
            self.sock = None

        # Closing active client connections:
        # The client handler threads should detect _running.clear() or socket errors eventually.
        # For a more immediate shutdown of client connections:
        with self._lock:
            for client_socket in list(self.clients.keys()): # list() for safe iteration while modifying
                try:
                    client_socket.shutdown(socket.SHUT_RDWR)
                    client_socket.close()
                except socket.error:
                    pass # Ignore errors if already closed
            self.clients.clear()
        print("TCP Server stop signal sent. Listening socket closed. Active connections closing.")


if __name__ == '__main__':
    print("TCP Server Example")
    server = TCPServer("0.0.0.0", 9999)
    server_thread = threading.Thread(target=server.start) # Not daemon for this example to allow join

    print("Starting TCP server...")
    server_thread.start()

    try:
        while server_thread.is_alive(): # Keep main thread alive while server runs
            cmd = input("Type 'stop' to shutdown the server: \n")
            if cmd.strip().lower() == 'stop':
                break
            time.sleep(0.5) # Prevent busy-waiting on input
    except KeyboardInterrupt:
        print("Keyboard interrupt received.")
    finally:
        print("Main: Initiating server stop...")
        server.stop()
        server_thread.join(timeout=5) # Wait for server thread to finish
        if server_thread.is_alive():
            print("Main: Server thread did not terminate in time.")
        print("Main: Server shutdown sequence complete.")
