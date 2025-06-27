use crate::config::{TestConfig, Protocol, TestMode};
use crate::metrics::TestMetrics;
use crate::network::{run_network_test, NetworkError};
use std::sync::{Arc, Mutex};
use std::time::Duration;

#[derive(Debug, Clone)]
pub struct BenchmarkSummary {
    pub duration_secs: u64,
    pub packet_payload_size_bytes: usize,
    pub client_packets_sent: u64,
    pub server_packets_received: u64,
    pub server_bytes_received: u64,
    pub client_pps: f64,
    pub server_pps: f64,
    pub server_mbps: f64,
}

/// Runs a self-contained UDP loopback benchmark.
pub async fn run_udp_loopback_benchmark(
    duration_secs: u64,
    packet_payload_size: usize,
) -> Result<BenchmarkSummary, NetworkError> {
    let port = популярных_портов::BENCHMARK_PORT; // Use a dedicated port, e.g., 5202 or from a const

    // --- Server Setup ---
    let server_config = Arc::new(TestConfig {
        target_ip: "127.0.0.1".to_string(), // Not used by server directly, but part of config
        target_port: port,
        test_duration_secs: duration_secs + 2, // Server runs a bit longer
        tick_rate_hz: 1000, // Server tick rate for its loops, not directly relevant for packet processing speed.
        packet_size_bytes: packet_payload_size, // To know what to expect if it were validating
        packet_size_range: None,
        protocol: Protocol::Udp,
        test_mode: TestMode::Server,
        tcp_bidirectional_mode: None,
        latency_spike_threshold_ms: None, // Disable anomaly detection for benchmark
        jitter_spike_threshold_ms: None,
        packet_loss_threshold_percent: None,
    });
    let server_metrics = Arc::new(Mutex::new(TestMetrics::default()));

    let server_metrics_clone = Arc::clone(&server_metrics);
    let server_handle = tokio::spawn(async move {
        println!("Benchmark Server: Starting...");
        let result = run_network_test(server_config, server_metrics_clone).await;
        println!("Benchmark Server: Finished.");
        result
    });

    // Brief pause for server to bind
    tokio::time::sleep(Duration::from_millis(200)).await;

    // --- Client Setup ---
    let client_config = Arc::new(TestConfig {
        target_ip: "127.0.0.1".to_string(),
        target_port: port,
        test_duration_secs: duration_secs,
        tick_rate_hz: 0, // AFAP mode!
        packet_size_bytes: packet_payload_size,
        packet_size_range: None,
        protocol: Protocol::Udp,
        test_mode: TestMode::Client,
        tcp_bidirectional_mode: None,
        latency_spike_threshold_ms: None,
        jitter_spike_threshold_ms: None,
        packet_loss_threshold_percent: None,
    });
    let client_metrics = Arc::new(Mutex::new(TestMetrics::default()));

    let client_metrics_clone = Arc::clone(&client_metrics);
    println!("Benchmark Client: Starting...");
    // Client runs directly, not in a separate tokio::spawn here, as we await its full execution.
    let client_result = run_network_test(client_config, client_metrics_clone).await;
    println!("Benchmark Client: Finished.");

    // Wait for server to finish (it runs slightly longer)
    // Or, implement a shutdown signal. For now, simple join.
    let server_shutdown_result = server_handle.await;

    if let Err(e) = client_result {
        return Err(e);
    }
    if let Err(e) = server_shutdown_result.unwrap_or(Ok(())) { // Handle panic from server task
         return Err(e);
    }


    // --- Process Results ---
    let final_client_metrics = client_metrics.lock().unwrap();
    let final_server_metrics = server_metrics.lock().unwrap();

    let client_pps = if duration_secs > 0 {
        final_client_metrics.packets_sent as f64 / duration_secs as f64
    } else { 0.0 };

    let server_pps = if duration_secs > 0 {
        final_server_metrics.packets_received as f64 / duration_secs as f64
    } else { 0.0 };

    let server_mbps = if duration_secs > 0 {
        (final_server_metrics.bytes_received * 8) as f64 / (duration_secs as f64 * 1_000_000.0)
    } else { 0.0 };

    Ok(BenchmarkSummary {
        duration_secs,
        packet_payload_size_bytes: packet_payload_size,
        client_packets_sent: final_client_metrics.packets_sent,
        server_packets_received: final_server_metrics.packets_received,
        server_bytes_received: final_server_metrics.bytes_received,
        client_pps,
        server_pps,
        server_mbps,
    })
}

// Placeholder for a dedicated port, ideally from a constants module or config
mod популярных_портов {
    pub const BENCHMARK_PORT: u16 = 5202;
}
