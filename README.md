# NetStats - Network Quality and Benchmark Tool

NetStats is a Rust-based tool designed to test network quality between two peers, simulating P2P game connectivity behaviors, and to benchmark UDP network performance under ideal conditions. It features a Slint-based GUI for easy configuration and provides detailed HTML reports with charts.

## Table of Contents

- [Features](#features)
- [Building NetStats](#building-netstats)
- [Running NetStats (GUI)](#running-netstats-gui)
  - [Configuration Options](#configuration-options)
  - [Running a Test](#running-a-test)
  - [Interpreting Results](#interpreting-results)
  - [HTML Report](#html-report)
- [Benchmark Mode](#benchmark-mode)
  - [Running the Benchmark](#running-the-benchmark)
  - [Interpreting Benchmark Results](#interpreting-benchmark-results)
- [Project Structure](#project-structure)
- [Known Limitations & Future Work](#known-limitations--future-work)

## Features

-   **Cross-Protocol Testing**: Supports network quality assessment over UDP and TCP.
-   **Configurable Test Parameters**:
    -   Target IP address and port.
    -   Test duration.
    -   **Tick Rate**: Simulates game tick rates (packets per second).
    -   **Packet Size**: Fixed size or a random size within a specified range.
-   **Comprehensive Network Metrics**:
    -   **Throughput**: Bandwidth measurement (Mbps).
    -   **Latency (RTT)**: Round-Trip Time for UDP (echo mode) and potentially TCP.
    -   **Jitter**: Variation in packet arrival times (derived from UDP RTTs).
    -   **Packet Loss**: Percentage of lost packets.
    -   **Out-of-Order Packets**: Basic detection for UDP.
-   **Test Modes**:
    -   **Client**: Sends data to a server.
    -   **Server**: Listens for and receives data from a client.
    -   **Bidirectional**: Both peers simultaneously send and receive data.
        -   TCP Bidirectional supports "Dual Stream" (default, two separate connections) and "Single Stream" (one connection for both directions) modes.
-   **Anomaly Detection**: Identifies and reports:
    -   High Latency Spikes.
    -   High Jitter Spikes.
    -   High Packet Loss percentage.
    -   Out-of-Order UDP packets.
-   **Graphical User Interface (GUI)**: Built with Slint for easy configuration and test execution.
-   **HTML Reports**: Generates detailed HTML reports including:
    -   Test configuration summary.
    -   Overall performance metrics.
    -   A time-series graph of bandwidth over the test duration.
    -   A list of detected network anomalies.
-   **UDP Benchmark Mode**: A self-contained UDP loopback test to measure maximum PPS and throughput of the tool itself under ideal conditions.

## Building NetStats

NetStats is a Rust project. You'll need the Rust toolchain (Rustc, Cargo) installed.

1.  **Clone the repository (if applicable)**:
    ```bash
    # git clone <repository_url>
    # cd netstats
    ```
2.  **Build the project**:
    From the project root directory (`netstats/` if you cloned, or the main project folder):
    ```bash
    cargo build --release
    ```
    The executable will be located at `target/release/netstats`.

## Running NetStats (GUI)

Execute the compiled binary:
```bash
./target/release/netstats
# On Windows:
# .\target\release\netstats.exe
```
This will launch the NetStats GUI.

### Configuration Options

The GUI provides the following configuration fields:

-   **Target IP**: The IP address of the remote peer. For Server mode, this is not directly used by the server itself but might be noted for context. For Client/Bidirectional modes, this is the machine to connect to.
-   **Target Port**: The port number the remote peer is listening on (for Client/Bidirectional send) or the port this instance will listen on (for Server/Bidirectional receive).
-   **Duration (s)**: The length of the test in seconds.
-   **Tick Rate (Hz)**: Number of packets to attempt to send per second. Set to `0` for "As Fast As Possible" (AFAP) mode (primarily for benchmarks, uses UDP).
-   **Packet Size (bytes)**: The base payload size for each packet.
-   **Random Size**: Checkbox to enable random packet sizes.
    -   **Min Size**: Minimum payload size if random sizing is enabled.
    -   **Max Size**: Maximum payload size if random sizing is enabled.
-   **Protocol**:
    -   `UDP`: Uses the UDP protocol. UDP tests include RTT and jitter measurements via an echo mechanism.
    -   `TCP`: Uses the TCP protocol.
-   **Test Mode**:
    -   `Client`: This instance sends data to the specified Target IP/Port.
    -   `Server`: This instance listens for incoming data on the specified Target Port (binds to 0.0.0.0:Port).
    -   `Bidirectional`: This instance both sends data to the Target IP/Port and listens for data from the remote peer on its local Target Port.
-   **TCP BiDi Mode** (Visible only if Protocol is TCP and Test Mode is Bidirectional):
    -   `Dual Stream`: Each peer initiates a separate TCP connection to the other for sending its primary data stream. (Default)
    -   `Single Stream`: One peer initiates a single TCP connection, and both peers use this one stream for sending and receiving their data.

### Running a Test

1.  **Configure Server (if needed)**:
    -   If running a Client or Bidirectional test, ensure the other peer is running NetStats in Server or Bidirectional mode, listening on the specified IP and Port.
    -   For Server mode, simply configure the listening port and start.
2.  **Configure Client/Your Side**: Set all parameters in the GUI as desired.
3.  **Start Test**: Click the "Start Test" button.
    -   The button will become disabled, and status text will indicate the test is in progress.
    -   For the duration of the test, the application will send and/or receive packets according to the configuration.
4.  **Test Completion**:
    -   Once the test duration is met, the status text will update to "Test complete!".
    -   An HTML report will be automatically generated (e.g., `netstats_report_YYYYMMDD_HHMMSS.html`) in the same directory where `netstats` was run. The path to this report will be shown.
    -   A brief summary of overall metrics will appear in the "Real-time Statistics" text area.

### Interpreting Results

After the test, examine the "Real-time Statistics" area in the GUI for a quick overview, or open the HTML report for detailed analysis.

Key metrics to look for:

-   **Packets Sent/Received**: Indicates basic connectivity and potential packet loss.
-   **Bytes Sent/Received**: Total data volume.
-   **Packet Loss (%)**: The percentage of packets that were sent but not received. Crucial for UDP.
-   **Avg. RTT (ms)**: Average Round-Trip Time. Lower is better. (Primarily for UDP echo tests).
-   **Min/Max RTT (ms)**: The minimum and maximum RTT observed. A large difference can indicate instability.
-   **Avg. Jitter (ms)**: Average variation in packet delay (derived from RTT variations for UDP). Lower is better, indicating more consistent packet delivery times.
-   **Overall Throughput (Mbps)**: The effective data rate achieved by the receiver.
-   **Bandwidth Over Time (Chart in HTML Report)**: Shows how throughput fluctuated during the test. Stable lines are desirable.
-   **Detected Anomalies (HTML Report & Metrics)**:
    -   `HighLatencySpike`: An RTT measurement significantly exceeded the configured threshold.
    -   `JitterSpike`: A jitter measurement significantly exceeded the configured threshold.
    -   `PacketLoss`: Overall packet loss exceeded the configured threshold. Also individual packet loss is implicitly part of the loss percentage.
    -   `OutOfOrder`: A UDP packet arrived with a sequence number lower than a previously received higher sequence number.

### HTML Report

Click the "Open Last Report" button in the GUI to open the generated HTML file in your default web browser. The report includes:
-   Full test configuration details.
-   A table of overall metrics.
-   A line chart showing bandwidth (Mbps) over time.
-   A list of any detected network anomalies with timestamps and descriptions.

## Benchmark Mode

NetStats includes a built-in UDP loopback benchmark to test the raw packet processing capability of the `netstats_core` library on your machine.

### Running the Benchmark

1.  Launch the NetStats GUI.
2.  Click the "Run Benchmark" button. No other configuration is needed for this mode.
    -   The application will automatically run a 10-second UDP test sending small (64-byte payload) packets as fast as possible to itself (`127.0.0.1`) on a dedicated port (5202).
    -   It internally starts a server, then a client, and waits for completion.
3.  **Benchmark Completion**:
    -   The status text will update to "Benchmark complete!".
    -   The "Real-time Statistics" area will display the benchmark results, including:
        -   Client Packets Sent & Packets Per Second (PPS).
        -   Server Packets Received & Packets Per Second (PPS).
        -   Server Throughput (Mbps).
    -   No HTML report is generated for the benchmark mode by default.

### Interpreting Benchmark Results

The benchmark shows the maximum PPS and Mbps the tool can achieve locally. This is an *ideal scenario* and not representative of real-world network performance over a WAN or even LAN, but it provides a baseline for the tool's own processing overhead.
-   **Client PPS**: How fast the client loop can generate and send packets.
-   **Server PPS**: How fast the server loop can receive and process packets. This is often the bottleneck.
-   **Server Mbps**: The resulting throughput based on received packets.

Differences between Client PPS and Server PPS in a loopback benchmark can indicate CPU limitations, OS networking stack overhead, or inefficiencies in the receive loop at very high packet rates.

## Project Structure

```
netstats/
├── Cargo.toml
├── build.rs                # Slint build script for the GUI app
├── ui/
│   └── appwindow.slint     # Slint UI definition for the main application
├── src/
│   └── main.rs             # Rust source for the GUI application
├── netstats_core/          # The core library crate
│   ├── Cargo.toml
│   ├── src/
│   │   ├── lib.rs          # Core library entry point
│   │   ├── network.rs      # TCP/UDP network logic (client, server, loops)
│   │   ├── packet.rs       # Packet structure definitions and serialization
│   │   ├── metrics.rs      # Data structures and calculations for metrics
│   │   ├── anomalies.rs    # Definitions for anomaly types and events
│   │   ├── config.rs       # Configuration structs (TestConfig, enums)
│   │   ├── reporter.rs     # Logic for processing results and HTML report generation
│   │   ├── benchmark.rs    # Self-contained UDP loopback benchmark logic
│   │   └── templates/
│   │       └── report_template.html # Askama HTML template for reports
│   └── tests/
│       └── integration_test.rs # Integration tests for netstats_core
└── README.md               # This documentation
```

## Known Limitations & Future Work

-   **GUI Real-time Updates**: The GUI currently shows summary results only after the test completes. Live, real-time updates of key metrics during the test are a planned enhancement.
-   **Advanced Anomaly Detection**:
    -   TCP anomaly detection (beyond connection errors) is currently limited. Detecting issues like retransmissions or SYN timeouts at the application level without raw sockets is challenging.
    -   UDP out-of-order detection is basic. More sophisticated duplicate packet detection is not yet implemented.
-   **TCP RTT Measurement**: While the UDP test measures RTT via an echo mechanism, dedicated RTT measurement for TCP (e.g., by embedding timestamps in data and ACKs) is not explicitly implemented in client/server modes. Bidirectional TCP modes might offer some RTT insights if packets are timestamped and echoed.
-   **Configuration Validation**: GUI input validation could be more robust with direct visual feedback for invalid entries.
-   **`start_time_utc` in Report**: The `start_time_utc` field in the HTML report is currently a placeholder ("N/A (TODO)") and should be populated with the actual test start time.
-   **CLI for `netstats_core`**: While the GUI is the primary interface, a simple CLI wrapper around `netstats_core` could be useful for scripting, headless server operation, or easier benchmark automation.
```
