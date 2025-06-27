// Test configuration structures

use std::time::Duration;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Protocol {
    Tcp,
    Udp,
}

#[derive(Debug, Clone)]
pub struct TestConfig {
    pub target_ip: String,
    pub target_port: u16,
    pub test_duration_secs: u64,
    pub tick_rate_hz: u32,
    pub packet_size_bytes: usize, // Base packet size, or default if range not specified
    pub packet_size_range: Option<(usize, usize)>, // (min_bytes, max_bytes) for random packet sizes
    pub protocol: Protocol,
    pub test_mode: TestMode,
    pub tcp_bidirectional_mode: Option<TcpBidirectionalMode>, // Only relevant if protocol is TCP and mode is Bidirectional

    // Anomaly detection thresholds
    pub latency_spike_threshold_ms: Option<u64>,
    pub jitter_spike_threshold_ms: Option<u64>,
    pub packet_loss_threshold_percent: Option<f64>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TcpBidirectionalMode {
    DualStream, // Each peer initiates a separate stream for sending
    SingleStream, // One peer initiates, both use that single stream
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TestMode {
    Client,       // Only sends data, receives ACKs/responses if applicable
    Server,       // Only receives data, sends ACKs/responses if applicable
    Bidirectional, // Both sends and receives test data streams simultaneously
}

impl Default for TestConfig {
    fn default() -> Self {
        TestConfig {
            target_ip: "127.0.0.1".to_string(),
            target_port: 5001, // Common for iperf
            test_duration_secs: 10,
            tick_rate_hz: 20,    // e.g., 20 ticks per second
            packet_size_bytes: 1024,
            packet_size_range: None, // Default to fixed size
            protocol: Protocol::Udp,
            test_mode: TestMode::Client, // Default to client mode
            tcp_bidirectional_mode: Some(TcpBidirectionalMode::DualStream), // Default for TCP BiDi
            latency_spike_threshold_ms: Some(200), // Default 200ms for latency spike
            jitter_spike_threshold_ms: Some(50),   // Default 50ms for jitter spike
            packet_loss_threshold_percent: Some(5.0), // Default 5% packet loss threshold
        }
    }
}

impl TestConfig {
    pub fn tick_interval(&self) -> Duration {
        Duration::from_secs_f64(1.0 / self.tick_rate_hz as f64)
    }

    pub fn total_duration(&self) -> Duration {
        Duration::from_secs(self.test_duration_secs)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = TestConfig::default();
        assert_eq!(config.target_ip, "127.0.0.1");
        assert_eq!(config.target_port, 5201); // As per current default in appwindow.slint (oops, core default is 5001)
                                            // Let's ensure core default is consistent or test against its actual value
        assert_eq!(config.target_port, 5001); // Corrected to actual TestConfig default
        assert_eq!(config.test_duration_secs, 10);
        assert_eq!(config.tick_rate_hz, 20);
        assert_eq!(config.packet_size_bytes, 1024);
        assert_eq!(config.protocol, Protocol::Udp);
        assert_eq!(config.test_mode, TestMode::Client);
        assert!(config.packet_size_range.is_none());
        assert_eq!(config.tcp_bidirectional_mode, Some(TcpBidirectionalMode::DualStream));
    }

    #[test]
    fn test_tick_interval() {
        let config_20hz = TestConfig { tick_rate_hz: 20, ..Default::default() };
        assert_eq!(config_20hz.tick_interval(), Duration::from_millis(50));

        let config_1hz = TestConfig { tick_rate_hz: 1, ..Default::default() };
        assert_eq!(config_1hz.tick_interval(), Duration::from_secs(1));

        let config_1000hz = TestConfig { tick_rate_hz: 1000, ..Default::default() };
        assert_eq!(config_1000hz.tick_interval(), Duration::from_millis(1));
    }

    #[test]
    fn test_total_duration() {
        let config_10s = TestConfig { test_duration_secs: 10, ..Default::default() };
        assert_eq!(config_10s.total_duration(), Duration::from_secs(10));

        let config_1s = TestConfig { test_duration_secs: 1, ..Default::default() };
        assert_eq!(config_1s.total_duration(), Duration::from_secs(1));
    }

    #[test]
    fn test_custom_config_values() {
        let config = TestConfig {
            target_ip: "192.168.1.100".to_string(),
            target_port: 8888,
            test_duration_secs: 5,
            tick_rate_hz: 50,
            packet_size_bytes: 128,
            packet_size_range: Some((64, 256)),
            protocol: Protocol::Tcp,
            test_mode: TestMode::Bidirectional,
            tcp_bidirectional_mode: Some(TcpBidirectionalMode::SingleStream),
        };
        assert_eq!(config.target_ip, "192.168.1.100");
        assert_eq!(config.target_port, 8888);
        assert_eq!(config.test_duration_secs, 5);
        assert_eq!(config.tick_rate_hz, 50);
        assert_eq!(config.packet_size_bytes, 128);
        assert_eq!(config.packet_size_range, Some((64, 256)));
        assert_eq!(config.protocol, Protocol::Tcp);
        assert_eq!(config.test_mode, TestMode::Bidirectional);
        assert_eq!(config.tcp_bidirectional_mode, Some(TcpBidirectionalMode::SingleStream));
    }
}
