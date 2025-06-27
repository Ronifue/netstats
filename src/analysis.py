import json
import os
import pandas as pd
import matplotlib
matplotlib.use('Agg') # Use Agg backend for non-interactive environments (e.g. servers, scripts)
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Optional # Added Optional

# Ensure a directory for charts exists
CHARTS_DIR = os.path.join("results", "charts")
if not os.path.exists(CHARTS_DIR):
    os.makedirs(CHARTS_DIR, exist_ok=True)

def load_json_results(filepath: str) -> dict | None:
    """Loads a JSON results file."""
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"Error: File not found at {filepath}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error: Could not decode JSON from {filepath}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred loading {filepath}: {e}")
        return None


def plot_bandwidth_timeseries(
    packet_details: list[dict],
    timestamp_key: str, # e.g., 'server_ts' or 'client_ack_ts'
    bytes_key: str,     # e.g., 'payload_size' or 'protocol_size'
    title_prefix: str,
    output_filename: str,
    session_id: str = "N/A"
    ):
    """
    Generic function to plot bandwidth over time from a list of packet details.
    """
    if not packet_details:
        print(f"No packet details for {title_prefix} bandwidth plot.")
        return

    df = pd.DataFrame(packet_details)

    if df.empty or timestamp_key not in df.columns or bytes_key not in df.columns:
        print(f"Data for {title_prefix} is empty or missing required columns ('{timestamp_key}', '{bytes_key}').")
        return

    # Ensure data types are correct
    df[timestamp_key] = pd.to_numeric(df[timestamp_key], errors='coerce')
    df[bytes_key] = pd.to_numeric(df[bytes_key], errors='coerce')
    df.dropna(subset=[timestamp_key, bytes_key], inplace=True)

    if df.empty:
        print(f"No valid numeric data after cleaning for {title_prefix} bandwidth plot.")
        return

    df['timestamp_dt'] = pd.to_datetime(df[timestamp_key], unit='s')
    df = df.sort_values(by='timestamp_dt')
    df.set_index('timestamp_dt', inplace=True)

    bandwidth_series_bps = df[bytes_key].resample('1S').sum() * 8
    bandwidth_series_mbps = bandwidth_series_bps / (1000 * 1000)

    if bandwidth_series_mbps.empty:
        print(f"No data to plot after resampling for {title_prefix} bandwidth.")
        return

    plt.figure(figsize=(12, 6))
    bandwidth_series_mbps.plot(kind='line', marker='.', linestyle='-', markersize=4)

    plt.title(f"{title_prefix} Bandwidth Over Time (SID: {session_id})")
    plt.xlabel("Time")
    plt.ylabel("Bandwidth (Mbps)")
    plt.grid(True, which='both', linestyle='--', linewidth=0.5)
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    plt.xticks(rotation=30, ha='right')
    plt.tight_layout()

    filepath = os.path.join(CHARTS_DIR, output_filename)
    plt.savefig(filepath)
    plt.close()
    print(f"{title_prefix} bandwidth timeseries plot saved to {filepath}")


def plot_latency_distribution(latency_samples_ms: list, title_prefix: str, output_filename: str, unit:str = "ms", session_id: str = "N/A"):
    if not latency_samples_ms or all(x is None for x in latency_samples_ms): # check if all are None
        print(f"No valid latency samples provided for {title_prefix} (SID: {session_id}).")
        return

    # Filter out None values if any mixed in, convert to float
    valid_latencies = [float(x) for x in latency_samples_ms if x is not None]
    if not valid_latencies:
        print(f"All latency samples were None for {title_prefix} (SID: {session_id}). Cannot plot.")
        return

    df = pd.DataFrame(valid_latencies, columns=['latency'])

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    df['latency'].plot(kind='hist', bins=max(10, min(len(df)//10, 50)), ax=axes[0], edgecolor='black', alpha=0.7)
    axes[0].set_title("Latency Histogram") # F541 Fix
    axes[0].set_xlabel(f"Latency ({unit})")
    axes[0].set_ylabel("Frequency")
    axes[0].grid(True, axis='y', linestyle=':', linewidth=0.7)

    df['latency'].plot(kind='box', ax=axes[1], vert=True, widths=0.5)  # Changed to vertical
    axes[1].set_title("Latency Boxplot") # F541 Fix
    axes[1].set_ylabel(f"Latency ({unit})")  # Y-label for vertical
    axes[1].set_xticks([])  # Remove x-axis ticks for vertical boxplot
    axes[1].grid(True, axis='y', linestyle=':', linewidth=0.7)

    plt.suptitle(f"{title_prefix} Latency Distribution (SID: {session_id})", fontsize=16)
    plt.tight_layout(rect=[0, 0.02, 1, 0.95])

    filepath = os.path.join(CHARTS_DIR, output_filename)
    plt.savefig(filepath)
    plt.close()
    print(f"Latency distribution plot for {title_prefix} saved to {filepath}")


def generate_summary_statistics_table_image(data: dict, title: str, output_filename: str, session_id: str = "N/A"):
    if not data:
        print(f"No data for summary statistics table: {title} (SID: {session_id}).")
        return

    # Select specific keys for the summary table to keep it concise
    # This list can be customized based on what's important.
    relevant_keys_ordered = [
        "status", "test_type", "duration_configured_sec", "actual_duration_sec",
        "packet_size_payload_bytes", "tickrate_hz",
        "total_packets_sent", "total_bytes_payload_sent", "total_bytes_protocol_sent",
        "packets_acked", "bytes_payload_acked", "bytes_protocol_acked", # UDP Client
        "total_packets_received", "total_bytes_payload_received", "total_bytes_protocol_received", # Server
        "bandwidth_payload_mbps", "bandwidth_protocol_mbps", # Client TCP
        "bandwidth_payload_acked_mbps", "bandwidth_protocol_acked_mbps", # Client UDP
        "bandwidth_payload_mbps_calculated", "bandwidth_protocol_mbps_calculated", # Server calculated
        "loss_rate_percent", "packets_lost", # UDP Client
        "lost_packets_inferred", "out_of_order_packets", "corrupted_packets", "duplicate_packets_detected_on_server", # Server
        "avg_rtt_ms", "min_rtt_ms", "max_rtt_ms", "jitter_ms", # UDP Client
        "send_errors", "receive_errors", # Client
        "start_time_unix", "end_time_unix",
        "client_address", # Server
        # "ack_timeout_sec" # UDP Client
    ]

    summary_text = f"{title}\nSID: {session_id}\n" + "="* (len(title) + len(session_id) + 6) + "\n"

    for key in relevant_keys_ordered:
        if key in data:
            value = data[key]
            if isinstance(value, float):
                summary_text += f"{key:<40}: {value:.3f}\n"
            else:
                summary_text += f"{key:<40}: {value}\n"

    # Count events if present
    if "events" in data and isinstance(data["events"], list):
        summary_text += f"{'event_count':<40}: {len(data['events'])}\n"

    # Determine figure height based on number of lines
    num_lines = summary_text.count('\n')
    fig_height = max(4, num_lines * 0.25) # Approximate height

    fig, ax = plt.subplots(figsize=(10, fig_height)) # Width 10, dynamic height
    ax.axis('tight')
    ax.axis('off')
    ax.text(0.01, 0.99, summary_text, va='top', ha='left', fontsize=9, family='monospace', wrap=True)

    filepath = os.path.join(CHARTS_DIR, output_filename)
    plt.savefig(filepath, bbox_inches='tight', dpi=120)
    plt.close()
    print(f"Summary statistics table image for {title} saved to {filepath}")


def analyze_session(client_filepath: Optional[str] = None, server_filepath: Optional[str] = None): # Changed type hints
    client_data = None
    server_data = None
    client_sid = "N/A_C"
    server_sid = "N/A_S" # Server's view of session ID
    server_client_addr = "N/A"


    if client_filepath:
        print(f"\n--- Analyzing Client Data: {os.path.basename(client_filepath)} ---")
        client_data = load_json_results(client_filepath)
        if client_data:
            client_sid = str(client_data.get("session_id", client_data.get("start_time_unix", "unknown_client_sid")))

            if client_data.get("test_type") == "udp_bandwidth_quality":
                if "rtt_samples_ms" in client_data and client_data["rtt_samples_ms"]:
                    plot_latency_distribution(
                        client_data["rtt_samples_ms"],
                        title_prefix="Client UDP RTT", # F541 Fix
                        output_filename=f"client_udp_rtt_dist_{client_sid}.png",
                        session_id=client_sid
                    )
                # UDP Client Bandwidth (acked data)
                # Need to reconstruct timeseries from sent_packet_info if we want client-side TX bandwidth plot
                # For now, client summary table will show overall acked bandwidth.

            generate_summary_statistics_table_image(
                client_data,
                title="Client Test Summary", # F541 Fix
                output_filename=f"client_summary_{client_sid}.png",
                session_id=client_sid
            )

    if server_filepath:
        print(f"\n--- Analyzing Server Data: {os.path.basename(server_filepath)} ---")
        server_data = load_json_results(server_filepath)
        if server_data:
            server_sid = str(server_data.get("session_id", server_data.get("start_time_unix", "unknown_server_sid")))
            server_client_addr = server_data.get("client_address", "unknown_client").replace(':','-').replace('.','_')

            if "received_packet_details" in server_data and server_data["received_packet_details"]:
                # Server-side received bandwidth timeseries
                plot_bandwidth_timeseries(
                    packet_details=server_data["received_packet_details"],
                    timestamp_key='server_ts',
                    bytes_key='payload_size',  # Or a calculated protocol_size_per_packet if available
                    title_prefix="Server RX Payload", # F541 Fix
                    output_filename=f"server_rx_payload_bw_{server_sid}_{server_client_addr}.png",
                    session_id=server_sid
                )

                # Server-side one-way latency distribution
                one_way_latencies = [d.get("one_way_latency_ms") for d in server_data["received_packet_details"] if "one_way_latency_ms" in d]
                plot_latency_distribution(
                    one_way_latencies,
                    title_prefix=f"Server One-Way Latency (from {server_client_addr})",
                    output_filename=f"server_oneway_latency_dist_{server_sid}_{server_client_addr}.png",
                    session_id=server_sid
                )

            generate_summary_statistics_table_image(
                server_data,
                title=f"Server Session Summary (Client: {server_client_addr})",
                output_filename=f"server_summary_{server_sid}_{server_client_addr}.png",
                session_id=server_sid
            )

if __name__ == '__main__':
    print(f"Plotting charts to: {os.path.abspath(CHARTS_DIR)}")
    results_path = "results"
    all_files = []
    if os.path.exists(results_path):
        for f_name in os.listdir(results_path):
            if f_name.endswith(".json") and os.path.isfile(os.path.join(results_path, f_name)):
                 f_path = os.path.join(results_path, f_name)
                 try:
                     f_stat = os.stat(f_path)
                     all_files.append({"path": f_path, "name": f_name, "mtime": f_stat.st_mtime})
                 except OSError:
                     continue

    if all_files:
        all_files.sort(key=lambda x: x["mtime"], reverse=True)

        # Try to find the latest pair of client and server files by session ID if possible
        # This is a simple heuristic, a proper CLI would take specific files or SIDs as input.
        processed_sids = set()
        print(f"Found {len(all_files)} JSON files in '{results_path}'. Analyzing most recent by SID pairs or individually.")

        for i in range(len(all_files)):
            f_info = all_files[i]
            current_sid = None
            # Try to extract SID from filename, e.g., "..._sid_ActualSID_timestamp.json"
            parts = f_info["name"].split("_sid_")
            if len(parts) > 1:
                current_sid = parts[1].split("_")[0] # Get the ActualSID part

            if current_sid and current_sid in processed_sids:
                continue # Already processed this SID (likely the other file of the pair)

            client_file_for_sid = None
            server_file_for_sid = None

            if current_sid:
                # Find matching pair for this SID
                for f_check in all_files: # Check all files for this SID
                    if f"_sid_{current_sid}_" in f_check["name"]:
                        if "client" in f_check["name"].lower():
                            client_file_for_sid = f_check["path"]
                        elif "server" in f_check["name"].lower():
                            server_file_for_sid = f_check["path"]
                if client_file_for_sid or server_file_for_sid:
                    print(f"\nProcessing SID: {current_sid}")
                    analyze_session(client_filepath=client_file_for_sid, server_filepath=server_file_for_sid)
                    processed_sids.add(current_sid)
                else:  # No clear pair, process individually if it wasn't part of a pair
                    if not (client_file_for_sid or server_file_for_sid) and \
                       ("client" in f_info["name"].lower() or "server" in f_info["name"].lower()):
                        print(f"\nProcessing individual file (no SID match or SID not in filename pattern): {f_info['name']}")
                        if "client" in f_info["name"].lower():
                            analyze_session(client_filepath=f_info["path"])
                        else:
                            analyze_session(server_filepath=f_info["path"])

            elif ("client" in f_info["name"].lower() or "server" in f_info["name"].lower()):  # No SID in filename, process individual
                print(f"\nProcessing individual file (no SID in filename): {f_info['name']}")
                if "client" in f_info["name"].lower():
                    analyze_session(client_filepath=f_info["path"])
                else:
                    analyze_session(server_filepath=f_info["path"])

            if len(processed_sids) >= 3 and len(all_files) > 6:  # Limit processing for bulk files in test
                print("\nProcessed a few SIDs/files. Stopping analysis for brevity in this run.")
                break


        if not processed_sids and not any("client" in f["name"].lower() or "server" in f["name"].lower() for f in all_files if isinstance(f, dict) and "name" in f): # Added check for f type
             print("No client or server result files with recognizable SIDs found to analyze.")
    else:
        print(f"No result files found in '{results_path}' directory.")
