// Logic for calculating metrics (loss, latency, jitter, bandwidth)
use serde::Serialize; // For #[serde(skip)] if TestMetrics is ever serialized
use std::collections::VecDeque;
use std::time::{Duration, Instant};

#[derive(Debug, Default, Serialize)] // Added Serialize for skip attribute
pub struct TestMetrics {
    pub packets_sent: u64,
    pub packets_received: u64,
    pub bytes_sent: u64,
    pub bytes_received: u64,

    pub total_rtt_micros: u128,
    pub rtt_count: u64,
    pub min_rtt_micros: Option<u128>,
    pub max_rtt_micros: Option<u128>,

    // For jitter calculation (sum of differences between successive RTTs)
    pub inter_arrival_jitter_micros_sum: u128,
    pub jitter_count: u64,

    // For bandwidth over time
    // (timestamp_ms_since_test_start, bytes_received_in_this_sample_interval)
    pub bandwidth_samples: Vec<(u128, u64)>,
    #[serde(skip)] // Skip serialization for non-persistent state used during test
    last_bandwidth_sample_time_ms: Option<u128>,
    #[serde(skip)]
    bytes_since_last_bandwidth_sample: u64,
    #[serde(skip)]
    pub test_start_time: Option<Instant>, // To calculate elapsed time for samples
    #[serde(skip)]
    last_rtt_micros: Option<u128>, // For jitter calculation

    // Store anomalies detected directly related to metrics processing
    pub anomalies: Vec<crate::anomalies::AnomalyEvent>,
    #[serde(skip)]
    latency_spike_threshold_micros: Option<u128>,
    #[serde(skip)]
    jitter_spike_threshold_micros: Option<u128>,

    pub out_of_order_count: u64, // For out-of-order packets
}

impl TestMetrics {
    pub fn new() -> Self {
        Default::default()
    }

    pub fn configure_anomaly_detection(&mut self, config: &crate::config::TestConfig) {
        self.latency_spike_threshold_micros = config.latency_spike_threshold_ms.map(|ms| ms as u128 * 1000);
        self.jitter_spike_threshold_micros = config.jitter_spike_threshold_ms.map(|ms| ms as u128 * 1000);
    }

    pub fn init_start_time(&mut self) {
        if self.test_start_time.is_none() {
            self.test_start_time = Some(Instant::now());
            self.last_bandwidth_sample_time_ms = Some(0); // Start of test
            self.bytes_since_last_bandwidth_sample = 0;
        }
    }

    pub fn record_packet_sent(&mut self, size_bytes: usize) {
        self.init_start_time(); // Ensure start time is set
        self.packets_sent += 1;
        self.bytes_sent += size_bytes as u64;
    }

    pub fn record_packet_received(&mut self, size_bytes: usize, rtt_micros: u128) {
        self.init_start_time(); // Ensure start time is set
        self.packets_received += 1;
        self.bytes_received += size_bytes as u64;
        self.bytes_since_last_bandwidth_sample += size_bytes as u64;

        // RTT calculations (only if rtt_micros is meaningful, e.g., > 0 for client)
        if rtt_micros > 0 {
            self.total_rtt_micros += rtt_micros;
            self.rtt_count += 1;

            self.min_rtt_micros = Some(self.min_rtt_micros.map_or(rtt_micros, |min| min.min(rtt_micros)));
            self.max_rtt_micros = Some(self.max_rtt_micros.map_or(rtt_micros, |max| max.max(rtt_micros)));

            // Calculate jitter based on this RTT and the previous RTT
            if let Some(last_rtt) = self.last_rtt_micros {
                // abs_diff, works for u128 if order is known, otherwise cast or use helper
                let jitter_sample = if rtt_micros >= last_rtt {
                    rtt_micros - last_rtt
                } else {
                    last_rtt - rtt_micros
                };
                self.record_jitter_value(jitter_sample);
            }
            self.last_rtt_micros = Some(rtt_micros);

            // Anomaly detection for this RTT and Jitter sample
            let current_test_time_ms = self.test_start_time.map_or(0, |st| Instant::now().duration_since(st).as_millis());

            if let Some(threshold_micros) = self.latency_spike_threshold_micros {
                if rtt_micros > threshold_micros {
                    self.anomalies.push(crate::anomalies::AnomalyEvent {
                        timestamp_ms: current_test_time_ms,
                        anomaly_type: crate::anomalies::AnomalyType::HighLatencySpike,
                        description: format!("RTT: {:.2} ms", rtt_micros as f64 / 1000.0),
                    });
                }
            }
            // Note: jitter_sample was calculated and record_jitter_value called *inside* this if rtt_micros > 0 block.
            // So, the jitter_sample variable from that scope isn't directly available here.
            // We'd need to check the latest jitter value or pass it around.
            // For simplicity, let's assume record_jitter_value could also check its input.
            // Or, we re-calculate jitter_sample here for checking if it's not stored.
            // The current record_jitter_value doesn't return the sample.
            // Let's adjust record_jitter_value to also perform this check.
        }

        // Basic jitter calculation could be refined here or in analysis step
        // This is a placeholder for now. A common way is RFC 3550's method.
        // For now, let's assume we get inter-arrival times from packet timestamps.
    }

    /// Call this periodically (e.g., every N milliseconds or after X packets)
    /// to record a bandwidth sample.
    pub fn take_bandwidth_sample(&mut self, current_test_time_ms: u128) {
        if self.test_start_time.is_none() { // Should have been initialized by packet send/recv
            self.init_start_time();
        }

        let sample_time = current_test_time_ms;
        // Ensure last_bandwidth_sample_time_ms is initialized, defaulting to 0 if it's the first sample.
        let last_sample_time = self.last_bandwidth_sample_time_ms.unwrap_or(0);

        if self.bytes_since_last_bandwidth_sample > 0 || sample_time > last_sample_time {
            self.bandwidth_samples.push((sample_time, self.bytes_since_last_bandwidth_sample));
        }

        self.bytes_since_last_bandwidth_sample = 0;
        self.last_bandwidth_sample_time_ms = Some(sample_time);
    }

    pub fn record_jitter_value(&mut self, jitter_sample_micros: u128) {
        self.init_start_time();
        self.inter_arrival_jitter_micros_sum += jitter_sample_micros;
        self.jitter_count += 1;

        // Anomaly detection for this jitter sample
        if let Some(threshold_micros) = self.jitter_spike_threshold_micros {
            if jitter_sample_micros > threshold_micros {
                let current_test_time_ms = self.test_start_time.map_or(0, |st| Instant::now().duration_since(st).as_millis());
                self.anomalies.push(crate::anomalies::AnomalyEvent {
                    timestamp_ms: current_test_time_ms,
                    anomaly_type: crate::anomalies::AnomalyType::JitterSpike,
                    description: format!("Jitter: {:.2} ms", jitter_sample_micros as f64 / 1000.0),
                });
            }
        }

        // Note: min/max jitter might also be useful, similar to RTT.
        // For now, just summing for average.
    }
    // Removed duplicate record_jitter_value here

    pub fn average_rtt_micros(&self) -> Option<f64> {
        if self.rtt_count == 0 {
            None
        } else {
            Some(self.total_rtt_micros as f64 / self.rtt_count as f64)
        }
    }

    pub fn packet_loss_percentage(&self) -> f64 {
        if self.packets_sent == 0 {
            0.0
        } else {
            let lost = self.packets_sent.saturating_sub(self.packets_received);
            (lost as f64 / self.packets_sent as f64) * 100.0
        }
    }

    pub fn average_jitter_micros(&self) -> Option<f64> {
        if self.jitter_count == 0 {
            None
        } else {
            Some(self.inter_arrival_jitter_micros_sum as f64 / self.jitter_count as f64)
        }
    }

    // Bandwidth in bits per second
    pub fn overall_throughput_bps(&self, duration_secs: f64) -> f64 {
        if duration_secs <= 0.0 {
            0.0
        } else {
            (self.bytes_received * 8) as f64 / duration_secs
        }
    }
}

// Further details for jitter calculation (e.g., using RFC 3550)
// D(i,j) = (Rj - Ri) - (Sj - Si) = (Rj - Sj) - (Ri - Si)
// J(i) = J(i-1) + (|D(i-1,i)| - J(i-1))/16
// This often requires storing previous arrival and sent timestamps.
// For simplicity, we might start with average difference of packet inter-arrival times vs inter-send times.

#[cfg(test)]
mod metrics_tests {
    use super::*;
    use std::time::{Instant, Duration};

    #[test]
    fn test_new_metrics_is_default() {
        let metrics = TestMetrics::new();
        let default_metrics = TestMetrics::default();
        assert_eq!(metrics.packets_sent, default_metrics.packets_sent);
        assert_eq!(metrics.bytes_received, default_metrics.bytes_received);
        assert!(metrics.test_start_time.is_none());
    }

    #[test]
    fn test_init_start_time() {
        let mut metrics = TestMetrics::new();
        assert!(metrics.test_start_time.is_none());
        metrics.init_start_time();
        assert!(metrics.test_start_time.is_some());
        let first_start_time = metrics.test_start_time.unwrap();
        // Simulate some time passing, ensure init_start_time doesn't overwrite
        std::thread::sleep(Duration::from_micros(10));
        metrics.init_start_time();
        assert_eq!(metrics.test_start_time.unwrap(), first_start_time);
        assert_eq!(metrics.last_bandwidth_sample_time_ms, Some(0));
    }

    #[test]
    fn test_record_packet_sent() {
        let mut metrics = TestMetrics::new();
        metrics.record_packet_sent(100);
        assert_eq!(metrics.packets_sent, 1);
        assert_eq!(metrics.bytes_sent, 100);
        assert!(metrics.test_start_time.is_some()); // init_start_time called

        metrics.record_packet_sent(50);
        assert_eq!(metrics.packets_sent, 2);
        assert_eq!(metrics.bytes_sent, 150);
    }

    #[test]
    fn test_record_packet_received() {
        let mut metrics = TestMetrics::new();
        metrics.record_packet_received(120, 10000); // 120 bytes, 10ms RTT
        assert_eq!(metrics.packets_received, 1);
        assert_eq!(metrics.bytes_received, 120);
        assert_eq!(metrics.bytes_since_last_bandwidth_sample, 120);
        assert_eq!(metrics.total_rtt_micros, 10000);
        assert_eq!(metrics.rtt_count, 1);
        assert_eq!(metrics.min_rtt_micros, Some(10000));
        assert_eq!(metrics.max_rtt_micros, Some(10000));
        assert!(metrics.test_start_time.is_some());

        metrics.record_packet_received(80, 5000); // 80 bytes, 5ms RTT
        assert_eq!(metrics.packets_received, 2);
        assert_eq!(metrics.bytes_received, 200);
        assert_eq!(metrics.bytes_since_last_bandwidth_sample, 200);
        assert_eq!(metrics.total_rtt_micros, 15000);
        assert_eq!(metrics.rtt_count, 2);
        assert_eq!(metrics.min_rtt_micros, Some(5000));
        assert_eq!(metrics.max_rtt_micros, Some(10000));
    }

    #[test]
    fn test_record_packet_received_rtt_zero() {
        let mut metrics = TestMetrics::new();
        metrics.record_packet_received(100, 0); // RTT 0 should not affect RTT stats
        assert_eq!(metrics.rtt_count, 0);
        assert_eq!(metrics.total_rtt_micros, 0);
        assert!(metrics.min_rtt_micros.is_none());
        assert!(metrics.max_rtt_micros.is_none());
    }

    #[test]
    fn test_record_jitter_value_separate() { // Renamed to avoid conflict if any other test is named similarly
        let mut metrics = TestMetrics::new();
        metrics.record_jitter_value(100);
        assert_eq!(metrics.inter_arrival_jitter_micros_sum, 100);
        assert_eq!(metrics.jitter_count, 1);
        metrics.record_jitter_value(50);
        assert_eq!(metrics.inter_arrival_jitter_micros_sum, 150);
        assert_eq!(metrics.jitter_count, 2);
    }

    #[test]
    fn test_take_bandwidth_sample() {
        let mut metrics = TestMetrics::new();
        metrics.init_start_time();

        metrics.bytes_since_last_bandwidth_sample = 1000;
        let sample_time_ms_1 = 1000;
        metrics.take_bandwidth_sample(sample_time_ms_1);
        assert_eq!(metrics.bandwidth_samples.len(), 1);
        assert_eq!(metrics.bandwidth_samples[0], (sample_time_ms_1, 1000));
        assert_eq!(metrics.bytes_since_last_bandwidth_sample, 0);
        assert_eq!(metrics.last_bandwidth_sample_time_ms, Some(sample_time_ms_1));

        metrics.bytes_since_last_bandwidth_sample = 500;
        let sample_time_ms_2 = 1500;
        metrics.take_bandwidth_sample(sample_time_ms_2);
        assert_eq!(metrics.bandwidth_samples.len(), 2);
        assert_eq!(metrics.bandwidth_samples[1], (sample_time_ms_2, 500));
        assert_eq!(metrics.bytes_since_last_bandwidth_sample, 0);
        assert_eq!(metrics.last_bandwidth_sample_time_ms, Some(sample_time_ms_2));

        let sample_time_ms_3 = 2000; // Time moved
        metrics.take_bandwidth_sample(sample_time_ms_3); // 0 bytes in this interval
        assert_eq!(metrics.bandwidth_samples.len(), 3);
        assert_eq!(metrics.bandwidth_samples[2], (sample_time_ms_3, 0));
    }

    #[test]
    fn test_average_rtt_micros() {
        let mut metrics = TestMetrics::new();
        assert!(metrics.average_rtt_micros().is_none());
        metrics.record_packet_received(100, 10000);
        metrics.record_packet_received(100, 20000);
        assert_eq!(metrics.average_rtt_micros(), Some(15000.0));
    }

    #[test]
    fn test_packet_loss_percentage() {
        let mut metrics = TestMetrics::new();
        assert_eq!(metrics.packet_loss_percentage(), 0.0);
        metrics.packets_sent = 10;
        metrics.packets_received = 10;
        assert_eq!(metrics.packet_loss_percentage(), 0.0);
        metrics.packets_received = 5;
        assert_eq!(metrics.packet_loss_percentage(), 50.0);
        metrics.packets_received = 0;
        assert_eq!(metrics.packet_loss_percentage(), 100.0);
        metrics.packets_sent = 0;
        metrics.packets_received = 0;
        assert_eq!(metrics.packet_loss_percentage(), 0.0);
    }

    #[test]
    fn test_average_jitter_micros() {
        let mut metrics = TestMetrics::new();
        assert!(metrics.average_jitter_micros().is_none());
        metrics.record_jitter_value(100);
        metrics.record_jitter_value(200);
        assert_eq!(metrics.average_jitter_micros(), Some(150.0));
    }

    #[test]
    fn test_overall_throughput_bps() {
        let mut metrics = TestMetrics::new();
        metrics.bytes_received = 125000; // 1 Mbit
        assert!((metrics.overall_throughput_bps(1.0) - 1_000_000.0).abs() < 0.01);
        assert_eq!(metrics.overall_throughput_bps(0.0), 0.0);
        metrics.bytes_received = 0;
        assert_eq!(metrics.overall_throughput_bps(10.0), 0.0);
    }
}
