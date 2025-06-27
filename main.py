import sys
import os
import argparse
import time
import threading

# Ensure src is in python path FIRST
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# Now import custom modules
from tcp_client import TCPClient
from tcp_server import TCPServer
from udp_client import UDPClient
from udp_server import UDPServer
from utils import save_results_to_json # generate_session_id was confirmed unused here
from analysis import analyze_session

def run_tcp_client(args):
    print(f"Running TCP Client Test to {args.host}:{args.port}")
    client_session_id = args.session_id

    client = TCPClient(host=args.host, port=args.port, session_id=client_session_id)
    effective_session_id = client.session_id

    print(f"TCP Client starting. Session ID: {effective_session_id}")
    if client.connect():
        print("TCP Client connected.") # F541 Fix
        print(f"Starting TCP test: Duration={args.duration}s, Packet Size={args.size}B, Rate={args.rate}pps")

        results = client.run_bandwidth_test(
            duration=args.duration,
            packet_size=args.size,
            tickrate=args.rate
        )
        client.close()

        print("\n--- TCP Client Test Results ---")
        for key, value in results.items():
            if key == "session_id":
                continue
            if isinstance(value, float):
                print(f"  {key}: {value:.3f}")
            elif isinstance(value, list) and len(value) > 5:
                print(f"  {key}: {value[:3]}... ({len(value)} items)")
            else:
                print(f"  {key}: {value}")

        if results.get("status") != "failure":
            save_results_to_json(
                data=results,
                base_filename=f"tcp_client_{args.host.replace('.', '_')}_{args.port}",
                session_id_override=effective_session_id
            )
    else:
        print(f"TCP Client failed to connect to {args.host}:{args.port}")

def run_udp_client(args):
    print(f"Running UDP Client Test to {args.host}:{args.port}")
    client_session_id = args.session_id
    client = UDPClient(host=args.host, port=args.port, session_id=client_session_id)
    effective_session_id = client.session_id

    print(f"UDP Client starting. Session ID: {effective_session_id}")
    print(f"Starting UDP test: Duration={args.duration}s, Packet Size={args.size}B, Rate={args.rate}pps, AckTimeout={args.udp_ack_timeout}s")

    results = client.run_bandwidth_test(
        duration=args.duration,
        packet_size=args.size,
        tickrate=args.rate,
        ack_timeout=args.udp_ack_timeout
    )
    client.close()

    print("\n--- UDP Client Test Results ---")
    for key, value in results.items():
        if key == "session_id":
            continue
        if isinstance(value, float):
            print(f"  {key}: {value:.3f}")
        elif key == "rtt_samples_ms" and isinstance(value, list) and len(value) > 5 :
            print(f"  {key}: {value[:3]}... ({len(value)} samples)")
        elif isinstance(value, list) and len(value) > 5:
            print(f"  {key}: {value[:3]}... ({len(value)} items)")
        else:
            print(f"  {key}: {value}")

    if results.get("status") != "failure":
        save_results_to_json(
            data=results,
            base_filename=f"udp_client_{args.host.replace('.', '_')}_{args.port}",
            session_id_override=effective_session_id
        )

def start_threaded_server(server_instance):
    server_thread = threading.Thread(target=server_instance.start, daemon=True)
    server_thread.start()
    print("Server started in a thread. Use Ctrl+C to stop main program and server.") # F541 Fix
    try:
        while server_thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received by main. Stopping server...") # F541 Fix
    finally:
        if hasattr(server_instance, 'stop'):
            server_instance.stop()
        print("Server shutdown process initiated from main.")


def run_server(args):
    server_instance = None
    if args.type == "tcp":
        print(f"Preparing TCP Server on {args.bind_ip}:{args.port}")
        server_instance = TCPServer(host=args.bind_ip, port=args.port)
    elif args.type == "udp":
        print(f"Preparing UDP Server on {args.bind_ip}:{args.port}")
        server_instance = UDPServer(host=args.bind_ip, port=args.port)
    else:
        print(f"Error: Unknown server type '{args.type}'. Choose 'tcp' or 'udp'.")
        return

    if server_instance:
        print(f"Starting {args.type.upper()} server in background thread...")
        start_threaded_server(server_instance)


def run_analysis_cli(args):
    print(f"CLI: Running analysis for target: {args.target if args.target else 'latest results'}")

    if args.target:
        client_target_path = None
        server_target_path = None

        if os.path.isfile(args.target):
            if "client" in args.target.lower():
                client_target_path = args.target
            elif "server" in args.target.lower():
                server_target_path = args.target
            else:
                print(f"Target '{args.target}' is a file, but type (client/server) unclear from name. Attempting generic SID search or direct pass if no SID found.")

        if not (client_target_path or server_target_path):
            print(f"Treating '{args.target}' as a Session ID or search term for result files.")
            results_path = "results"
            # F841: found_files = [] was here, removed as it's not used.
            if os.path.exists(results_path):
                for f_name in os.listdir(results_path):
                    if args.target in f_name and f_name.endswith(".json") and os.path.isfile(os.path.join(results_path, f_name)):
                        full_f_path = os.path.join(results_path, f_name)
                        if "client" in f_name.lower() and not client_target_path:
                            client_target_path = full_f_path
                        elif "server" in f_name.lower() and not server_target_path:
                            server_target_path = full_f_path

            if not (client_target_path or server_target_path):
                print(f"No specific client/server files found for target/SID '{args.target}'.")
                if os.path.isfile(args.target):
                     print(f"Attempting to analyze '{args.target}' as a single file (type inferred from name).")
                     analyze_session(
                         client_filepath=args.target if "client" in args.target.lower() else None,
                         server_filepath=args.target if "server" in args.target.lower() else None
                        )
                     return

        if client_target_path or server_target_path:
            print(f"Found for analysis: Client='{client_target_path}', Server='{server_target_path}'")
            analyze_session(client_filepath=client_target_path, server_filepath=server_target_path)
        elif not os.path.isfile(args.target):
            print(f"No result files found matching target/SID '{args.target}'.")
    else:
        print("No specific target. Attempting to analyze latest results...")
        analyze_session()


def main():
    parser = argparse.ArgumentParser(description="Network Quality Tester CLI.", formatter_class=argparse.RawTextHelpFormatter)
    subparsers = parser.add_subparsers(title="Modes", dest="mode", required=True,
                                       help="""\
client  - Run in client mode to test network to a server.
server  - Run in server mode to listen for client tests.
analyze - Analyze previously saved test results.
""")

    # --- Client Mode ---
    client_parser = subparsers.add_parser("client", help="Run client test (e.g., client tcp <host> -p <port> ...)")
    client_parser.add_argument("type", choices=["tcp", "udp"], help="Type of test (tcp or udp).")
    client_parser.add_argument("host", type=str, help="Target server IP or hostname.")
    client_parser.add_argument("-p", "--port", type=int, help="Target server port. (TCP default: 9999, UDP default: 9998)")
    client_parser.add_argument("-d", "--duration", type=int, default=10, help="Duration in seconds (default: 10).")
    client_parser.add_argument("-s", "--size", type=int, default=1024, help="Payload size in bytes (default: 1024).")
    client_parser.add_argument("-r", "--rate", type=int, default=10, help="Packets per second (default: 10).")
    client_parser.add_argument("--session-id", type=str, default=None, help="Specify Session ID (default: auto).")
    client_parser.add_argument("--udp-ack-timeout", type=float, default=0.2, help="UDP ACK timeout in seconds (default: 0.2).")
    client_parser.set_defaults(func=lambda args_inner: run_tcp_client(args_inner) if args_inner.type == "tcp" else run_udp_client(args_inner))

    # --- Server Mode ---
    server_parser = subparsers.add_parser("server", help="Run server (e.g., server tcp -b <ip> -p <port>)")
    server_parser.add_argument("type", choices=["tcp", "udp"], help="Type of server (tcp or udp).")
    server_parser.add_argument("-b", "--bind-ip", type=str, default="0.0.0.0", help="IP to bind server to (default: 0.0.0.0).")
    server_parser.add_argument("-p", "--port", type=int, help="Port to bind server to. (TCP default: 9999, UDP default: 9998)")
    server_parser.set_defaults(func=run_server)

    # --- Analysis Mode ---
    analysis_parser = subparsers.add_parser("analyze", help="Analyze results (e.g., analyze <session_id_or_filepath_or_empty_for_latest>)")
    analysis_parser.add_argument("target", nargs='?', default=None,
                                 help="Optional: Session ID, path to a result file, or part of filename. If empty, analyzes latest.")
    analysis_parser.set_defaults(func=run_analysis_cli)

    args = parser.parse_args()

    if args.mode == "client" or args.mode == "server":
        if args.port is None:
            args.port = 9999 if args.type == "tcp" else 9998
            print(f"Using default port {args.port} for {args.type.upper()} {args.mode}.")

    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
```
