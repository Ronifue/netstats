import socket
import time
from .packet_handler import Packet, read_packet_from_tcp_socket
from .utils import generate_session_id # Added import

class TCPClient:
    def __init__(self, host: str, port: int, session_id: str = None): # Added session_id param
        self.host = host
        self.port = port
        self.sock = None
        self.session_id = session_id if session_id else generate_session_id() # Use provided or generate

    def connect(self) -> bool:
        # Update results in run_bandwidth_test to include the effective session_id
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Optional: Set TCP_NODELAY (Nagle's algorithm) if simulating game traffic more closely
            # self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # Optional: Set timeout for connect operation
            # self.sock.settimeout(5.0) # 5 seconds timeout for connection
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None) # Reset timeout to blocking for subsequent operations by default
            print(f"TCP Client connected to {self.host}:{self.port}")
            return True
        except socket.timeout:
            print(f"TCP Client connection to {self.host}:{self.port} timed out.")
            self.sock = None
            return False
        except socket.error as e:
            print(f"TCP Client connection error: {e}")
            self.sock = None
            return False

    def send_packet(self, packet: Packet) -> bool:
        if not self.sock:
            print("TCP Client not connected.")
            return False
        try:
            serialized_packet = packet.serialize()
            self.sock.sendall(serialized_packet)
            # print(f"Sent: {packet}")
            return True
        except socket.error as e:
            print(f"TCP Client send error: {e}")
            # Potentially close socket here or mark as unusable
            return False

    def receive_packet(self, timeout: float | None = None) -> Packet | None:
        if not self.sock:
            print("TCP Client not connected.")
            return None

        original_timeout = self.sock.gettimeout()
        self.sock.settimeout(timeout) # Can be None for blocking, or a float for timeout

        packet = None
        try:
            packet = read_packet_from_tcp_socket(self.sock)
        except socket.timeout:
            print("TCP Client receive_packet timed out.")
            return None
        except Exception as e:
            print(f"TCP Client error during receive_packet: {e}")
            return None # Or handle more gracefully
        finally:
            self.sock.settimeout(original_timeout) # Restore original timeout

        # if packet:
        #     print(f"Received: {packet}")
        return packet

    def close(self):
        if self.sock:
            print("Closing TCP client socket.")
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except socket.error:
                pass # Ignore error if socket already closed or not connected
            self.sock.close()
            self.sock = None

    def run_bandwidth_test(self, duration: int, packet_size: int, tickrate: int) -> dict:
        """
        Runs a TCP bandwidth test towards the server.

        Args:
            duration (int): Test duration in seconds.
            packet_size (int): Size of the payload for each packet in bytes.
            tickrate (int): Packets to send per second.

        Returns:
            dict: A dictionary containing test results and statistics.
        """
        if not self.sock:
            print("TCP Client not connected. Cannot run bandwidth test.")
            return {"error": "Client not connected", "status": "failure"}

        if tickrate <= 0:
            return {"error": "Tickrate must be positive.", "status": "failure"}
        if packet_size <= 0: # Or some reasonable minimum payload size
            return {"error": "Packet size must be positive.", "status": "failure"}
        if duration <=0:
            return {"error": "Duration must be positive.", "status": "failure"}


        results = {
            "test_type": "tcp_bandwidth",
            "status": "running", # Will be updated to "completed" or "error"
            "duration_configured_sec": duration,
            "packet_size_payload_bytes": packet_size,
            "tickrate_hz": tickrate,
            "total_packets_sent": 0,
            "total_bytes_payload_sent": 0,
            "total_bytes_protocol_sent": 0, # Total bytes including our protocol overhead
            "actual_duration_sec": 0,
            "send_errors": 0,
            "bandwidth_payload_mbps": 0,
            "bandwidth_protocol_mbps": 0,
            "start_time_unix": time.time(),
            "end_time_unix": 0,
            "events": [],
            "session_id": self.session_id # Ensure session_id is in results
        }

        interval = 1.0 / tickrate
        start_time_monotonic = time.monotonic() # Use monotonic clock for duration measurement
        end_time_expected_monotonic = start_time_monotonic + duration

        sequence_number = 0

        try:
            while time.monotonic() < end_time_expected_monotonic:
                loop_start_time_monotonic = time.monotonic()

                # Create dummy payload - consider creating once if size is fixed and large
                payload = b'X' * packet_size
                current_packet = Packet(sequence_number=sequence_number, data=payload, session_id=self.session_id)

                serialized_packet_data = current_packet.serialize()

                if self.send_packet_raw(serialized_packet_data): # Modified to send raw bytes for efficiency here
                    results["total_packets_sent"] += 1
                    results["total_bytes_payload_sent"] += current_packet.payload_size
                    results["total_bytes_protocol_sent"] += len(serialized_packet_data)
                    sequence_number += 1
                else:
                    results["send_errors"] += 1
                    timestamp = time.time()
                    results["events"].append({
                        "time": timestamp,
                        "type": "send_error",
                        "seq": sequence_number,
                        "message": "send_packet_raw returned false"
                    })
                    print(f"Client: Send error for packet {sequence_number} at {timestamp}, stopping test.")
                    results["status"] = "error_send_failed"
                    break

                loop_end_time_monotonic = time.monotonic()
                elapsed_this_tick = loop_end_time_monotonic - loop_start_time_monotonic
                sleep_time = interval - elapsed_this_tick
                if sleep_time > 0:
                    time.sleep(sleep_time)
                # else: # Optional: Log if falling behind
                #    print(f"Client: Cannot keep up with tickrate {tickrate} Hz. Deficit: {-sleep_time*1000:.2f}ms")

        except KeyboardInterrupt:
            print("Client: Bandwidth test interrupted by user.")
            results["events"].append({"time": time.time(), "type": "interrupt", "message": "User interrupted test"})
            results["status"] = "interrupted"
        except Exception as e:
            print(f"Client: Exception during bandwidth test: {e}")
            results["events"].append({"time": time.time(), "type": "exception", "message": str(e)})
            results["status"] = "error_exception"
        finally:
            results["end_time_unix"] = time.time()
            results["actual_duration_sec"] = time.monotonic() - start_time_monotonic # Use monotonic for duration

            if results["status"] == "running": # If not set to an error status already
                results["status"] = "completed"

            if results["actual_duration_sec"] > 0.001: # Avoid division by zero or tiny duration
                bits_payload_sent = results["total_bytes_payload_sent"] * 8
                results["bandwidth_payload_mbps"] = (bits_payload_sent / results["actual_duration_sec"]) / (1000 * 1000) # Use 1000 for Mbps

                bits_total_sent = results["total_bytes_protocol_sent"] * 8
                results["bandwidth_protocol_mbps"] = (bits_total_sent / results["actual_duration_sec"]) / (1000 * 1000) # Use 1000 for Mbps
            else: # Handle very short durations or no time elapsed
                results["bandwidth_payload_mbps"] = 0
                results["bandwidth_protocol_mbps"] = 0
                if results["status"] == "completed": # If it was supposed to run but duration is near zero
                     results["events"].append({"time": time.time(), "type": "warning", "message": "Test duration too short for meaningful bandwidth calculation."})


        return results

    def send_packet_raw(self, data: bytes) -> bool:
        """Helper to send raw bytes, used by bandwidth test for efficiency."""
        if not self.sock:
            # print("TCP Client not connected (send_packet_raw).") # Can be noisy
            return False
        try:
            self.sock.sendall(data)
            return True
        except socket.error as e:
            # print(f"TCP Client send_packet_raw error: {e}") # Can be noisy
            return False


if __name__ == '__main__':
    import time
    from .utils import save_results_to_json # Relative import for package execution
    # If running script directly for testing & utils.py is sibling:
    # try:
    #     from .utils import save_results_to_json
    # except ImportError:
    #     from utils import save_results_to_json # Fallback for direct script run if src is in PYTHONPATH

    print("TCP Client Example with Bandwidth Test")
    client = TCPClient("127.0.0.1", 9999)

    if client.connect():
        test_results = None # Initialize
        try:
            print("Starting TCP bandwidth test for 5 seconds...")
            test_results = client.run_bandwidth_test(duration=5, packet_size=1024, tickrate=100)

            print("\n--- TCP Bandwidth Test Results (Client-Side) ---")
            for key, value in test_results.items():
                if key == "events":
                    print(f"Events ({len(value)}):")
                    for event in value:
                        print(f"  - {event}")
                elif isinstance(value, float):
                    print(f"{key}: {value:.4f}")
                else:
                    print(f"{key}: {value}")

            end_signal_packet = Packet(sequence_number=-1, data=b"TEST_ENDED_GRACEFULLY", session_id=client.session_id)
            print(f"\nClient: Sending test completion signal: {end_signal_packet}")
            client.send_packet(end_signal_packet)

        finally:
            print("Client: Closing connection.")
            client.close()
            # Save results after closing client, ensuring all test activities are done
            if test_results and test_results.get("status") != "failure":
                print(f"Client: Saving test results for session {client.session_id}...")
                save_results_to_json(
                    data=test_results,
                    base_filename=f"tcp_client_{client.host.replace('.', '_')}_{client.port}",
                    session_id_override=str(client.session_id)
                )
            elif test_results:
                print(f"Client: Test results not saved due to status: {test_results.get('status')}")

    else:
        print("TCP Client could not connect to run test.")
