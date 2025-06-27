use netstats_core::config::{TestConfig, Protocol, TestMode, TcpBidirectionalMode};
use netstats_core::metrics::TestMetrics;
use netstats_core::network::run_network_test;

use std::sync::{Arc, Mutex};
use std::time::Duration;

// Helper function to create a default config for tests, allowing specific overrides.
fn create_test_config(
    protocol: Protocol,
    mode: TestMode,
    duration_secs: u64,
    target_port: u16,
    tcp_bidi_mode: Option<TcpBidirectionalMode>
) -> Arc<TestConfig> {
    Arc::new(TestConfig {
        target_ip: "127.0.0.1".to_string(),
        target_port,
        test_duration_secs: duration_secs,
        tick_rate_hz: 10, // Lower tick rate for faster tests
        packet_size_bytes: 64, // Smaller packets for faster tests
        packet_size_range: None,
        protocol,
        test_mode: mode,
        tcp_bidirectional_mode: tcp_bidi_mode,
    })
}

#[tokio::test]
async fn test_udp_client_server_basic() {
    let test_duration_secs = 1;
    let port = 6001; // Unique port for this test

    let server_config = create_test_config(Protocol::Udp, TestMode::Server, test_duration_secs, port, None);
    let server_metrics = Arc::new(Mutex::new(TestMetrics::default()));

    let client_config = create_test_config(Protocol::Udp, TestMode::Client, test_duration_secs, port, None);
    let client_metrics = Arc::new(Mutex::new(TestMetrics::default()));

    let server_metrics_clone = Arc::clone(&server_metrics);
    let server_handle = tokio::spawn(async move {
        run_network_test(server_config, server_metrics_clone).await
    });

    // Give server a moment to start
    tokio::time::sleep(Duration::from_millis(100)).await;

    let client_metrics_clone = Arc::clone(&client_metrics);
    let client_handle = tokio::spawn(async move {
        run_network_test(client_config, client_metrics_clone).await
    });

    let server_result = server_handle.await.unwrap();
    let client_result = client_handle.await.unwrap();

    assert!(server_result.is_ok(), "Server error: {:?}", server_result.err());
    assert!(client_result.is_ok(), "Client error: {:?}", client_result.err());

    let final_client_metrics = client_metrics.lock().unwrap();
    let final_server_metrics = server_metrics.lock().unwrap();

    println!("Client Metrics: {:?}", final_client_metrics);
    println!("Server Metrics: {:?}", final_server_metrics);

    // Assertions
    // Client should have sent packets
    assert!(final_client_metrics.packets_sent > 0, "Client should send packets");
    assert_eq!(final_client_metrics.packets_sent, test_duration_secs as u64 * 10, "Client sent packet count mismatch"); // 10 ticks/sec * duration

    // Server should have received packets. Allow for some loss in UDP, though on loopback it should be 0.
    // For a robust test, we might not check exact equality for received packets in UDP.
    // However, on loopback, it's usually reliable.
    assert!(final_server_metrics.packets_received > 0, "Server should receive packets");
    assert!(final_server_metrics.packets_received <= final_client_metrics.packets_sent, "Server received more than client sent");

    // Check if bytes were transferred
    assert!(final_client_metrics.bytes_sent > 0);
    assert!(final_server_metrics.bytes_received > 0);

    // If server echoes EchoRequest, client might receive them.
    // Current UDP server echoes EchoRequest, but client sends DataPacket.
    // So client.packets_received would be 0 unless it's also setup to receive/process those echoes.
    // For now, client doesn't process incoming UDP packets in send_loop.
    assert_eq!(final_client_metrics.packets_received, 0, "Client should not receive UDP packets in this basic test");

    // Check bandwidth samples were recorded on server
    assert!(!final_server_metrics.bandwidth_samples.is_empty(), "Server should have bandwidth samples");
}


#[tokio::test]
async fn test_tcp_client_server_basic() {
    let test_duration_secs = 1;
    let port = 6002; // Unique port

    let server_config = create_test_config(Protocol::Tcp, TestMode::Server, test_duration_secs, port, None);
    let server_metrics = Arc::new(Mutex::new(TestMetrics::default()));

    let client_config = create_test_config(Protocol::Tcp, TestMode::Client, test_duration_secs, port, None);
    let client_metrics = Arc::new(Mutex::new(TestMetrics::default()));

    let server_metrics_clone = Arc::clone(&server_metrics);
    let server_handle = tokio::spawn(async move {
        run_network_test(server_config, server_metrics_clone).await
    });

    tokio::time::sleep(Duration::from_millis(100)).await; // Server startup grace

    let client_metrics_clone = Arc::clone(&client_metrics);
    let client_handle = tokio::spawn(async move {
        run_network_test(client_config, client_metrics_clone).await
    });

    let server_result = server_handle.await.unwrap();
    let client_result = client_handle.await.unwrap();

    assert!(server_result.is_ok(), "Server error: {:?}", server_result.err());
    assert!(client_result.is_ok(), "Client error: {:?}", client_result.err());

    let final_client_metrics = client_metrics.lock().unwrap();
    let final_server_metrics = server_metrics.lock().unwrap();

    println!("TCP Client Metrics: {:?}", final_client_metrics);
    println!("TCP Server Metrics: {:?}", final_server_metrics);

    assert!(final_client_metrics.packets_sent > 0, "Client should send TCP packets");
    assert_eq!(final_client_metrics.packets_sent, test_duration_secs as u64 * 10, "Client TCP sent packet count mismatch");

    // TCP is reliable, so server should receive all packets sent by client in this simple case.
    assert!(final_server_metrics.packets_received > 0, "Server should receive TCP packets");
    assert_eq!(final_server_metrics.packets_received, final_client_metrics.packets_sent, "TCP packet count mismatch between client and server");

    assert!(final_client_metrics.bytes_sent > 0);
    // +4 for length prefix per packet
    assert_eq!(final_server_metrics.bytes_received, final_client_metrics.bytes_sent + (final_client_metrics.packets_sent * 4));

    assert!(!final_server_metrics.bandwidth_samples.is_empty(), "Server should have TCP bandwidth samples");
}


// TODO: Add more integration tests:
// - UDP Bidirectional
// - TCP Bidirectional (Dual Stream)
// - TCP Bidirectional (Single Stream)
// - Tests with randomized packet sizes
// - Tests with longer durations or higher tick rates (might need to be marked `#[ignore]` for CI)
// - Tests verifying specific anomaly detection (once implemented)
