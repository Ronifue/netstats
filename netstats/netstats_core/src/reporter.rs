// Data aggregation and preparing data for reports

use crate::metrics::TestMetrics;
use crate::anomalies::AnomalyEvent;
use crate::config::{TestConfig, Protocol, TestMode, TcpBidirectionalMode}; // Added more config types for template
use std::time::SystemTime;
use askama::Template; // Import Askama
use serde_json; // For serializing data to JSON for JS charts

#[derive(Template)]
#[template(path = "report_template.html")] // Path to the template file
pub struct HtmlReport<'a> {
    summary: &'a TestSummary,
    // Additional fields needed specifically for the template can be added here
    // For example, pre-formatted strings or chart data.
    bandwidth_chart_data_json: String,
}

#[derive(Debug)] // Keep TestSummary as a plain data struct
pub struct TestSummary {
    pub test_config: TestConfig,
    pub overall_metrics: TestMetrics,
    pub anomalies: Vec<AnomalyEvent>,
    pub start_time_utc: String,
    pub end_time_utc: String,
    pub test_duration_actual_secs: f64,
    pub bandwidth_over_time: Vec<(f64, f64)>, // (time_sec_since_start, mbps)
    // pub latency_over_time: Vec<(f64, f64)>, // (time_sec, latency_ms) - for later if needed
}

/// Processes raw bandwidth samples from TestMetrics into a Vec<(f64, f64)>
/// representing (time_seconds_since_start, megabits_per_second).
fn process_bandwidth_samples(metrics: &TestMetrics) -> Vec<(f64, f64)> {
    let mut processed_samples = Vec::new();
    if metrics.bandwidth_samples.is_empty() {
        return processed_samples;
    }

    // The first timestamp in bandwidth_samples is the time of the end of the first interval.
    // The bytes are for that interval.
    // Example: [(1000ms, 125000 bytes), (2000ms, 130000 bytes)]
    // Sample 1: from 0 to 1000ms, 125000 bytes were received. Interval duration = 1000ms. Mbps = (125000*8)/(1000/1000)/1_000_000
    // Sample 2: from 1000ms to 2000ms, 130000 bytes. Interval duration = 1000ms. Mbps = (130000*8)/(1000/1000)/1_000_000

    let mut last_sample_time_ms = 0;

    for (sample_end_time_ms, bytes_in_interval) in &metrics.bandwidth_samples {
        let interval_duration_ms = sample_end_time_ms.saturating_sub(last_sample_time_ms);
        if interval_duration_ms == 0 {
            // Avoid division by zero if multiple samples at the same millisecond,
            // or if the first sample is at 0ms (though current logic makes it end_time).
            // If bytes > 0, this is infinite bandwidth, which is unlikely/error.
            // If bytes = 0, it's 0 mbps.
            if *bytes_in_interval > 0 {
                 // Log or handle this case - potentially very high or infinite bps
                 // For now, skip if duration is zero and bytes > 0 to avoid skewed graph
                eprintln!("Warning: Zero duration interval with {} bytes at {}ms", bytes_in_interval, sample_end_time_ms);
                // Or assign a very high value, or average with next if possible.
            }
            // if *bytes_in_interval == 0, then 0 mbps is fine.
            // processed_samples.push((*sample_end_time_ms as f64 / 1000.0, 0.0));
            // Let's just update last_sample_time_ms and continue, the bytes will add to next interval.
            // This shouldn't happen often with current sampling logic.
            last_sample_time_ms = *sample_end_time_ms;
            continue;
        }

        let interval_duration_secs = interval_duration_ms as f64 / 1000.0;
        let megabits_per_second = (*bytes_in_interval as f64 * 8.0) / interval_duration_secs / 1_000_000.0;

        // The timestamp for the graph point should represent the end of the interval
        processed_samples.push((*sample_end_time_ms as f64 / 1000.0, megabits_per_second));

        last_sample_time_ms = *sample_end_time_ms;
    }

    processed_samples
}


pub fn generate_summary(
    config: &TestConfig,
    metrics: TestMetrics, // metrics itself contains the anomalies
    actual_duration: std::time::Duration,
) -> TestSummary {
    // For now, using simple string representation of time.
    // Consider chrono crate for more robust time handling and formatting.
    let now_utc = || {
        humantime::format_rfc3339_seconds(SystemTime::now()).to_string()
    };

    let processed_bandwidth = process_bandwidth_samples(&metrics);
    let anomalies_cloned = metrics.anomalies.clone(); // Clone before metrics is moved

    TestSummary {
        test_config: config.clone(),
        overall_metrics: metrics, // Note: metrics is moved here (including its .anomalies field)
        anomalies: anomalies_cloned, // Store the cloned list in TestSummary
        start_time_utc: String::from("N/A (TODO)"), // Will be set at actual test start
        end_time_utc: now_utc(), // Set at test end
        test_duration_actual_secs: actual_duration.as_secs_f64(),
        bandwidth_over_time: processed_bandwidth,
    }
}

// Later, this module will have functions to format TestSummary into HTML
// or other report formats.

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{Protocol, TestConfig, TestMode, TcpBidirectionalMode}; // Added more imports
    use crate::metrics::TestMetrics; // Ensure TestMetrics is in scope
    use std::time::{Duration, Instant}; // Added Instant for metrics.test_start_time

// Function to generate HTML report string
pub fn generate_html_report_string(summary: &TestSummary) -> Result<String, askama::Error> {
    // Prepare data for Chart.js
    // Chart.js expects an array of objects like {time: seconds, mbps: value}
    let chart_data_points: Vec<_> = summary.bandwidth_over_time.iter()
        .map(|(time_sec, mbps_val)| serde_json::json!({"time": time_sec, "mbps": mbps_val}))
        .collect();

    let bandwidth_chart_data_json = serde_json::to_string(&chart_data_points)
        .unwrap_or_else(|_| "[]".to_string()); // Default to empty array on serialization error

    let report_template = HtmlReport {
        summary,
        bandwidth_chart_data_json,
    };
    report_template.render()
}

    #[test]
    fn test_generate_summary_and_process_bandwidth() {
        let config = TestConfig {
            target_ip: "127.0.0.1".to_string(),
            target_port: 8080,
            test_duration_secs: 5,
            tick_rate_hz: 10,
            packet_size_bytes: 512,
            packet_size_range: None,
            protocol: Protocol::Udp,
            test_mode: TestMode::Client,
            tcp_bidirectional_mode: None,
        };

        let mut metrics = TestMetrics::default(); // Use default and populate
        metrics.test_start_time = Some(Instant::now()); // Initialize start time
        metrics.packets_sent = 50;
        metrics.packets_received = 45;
        metrics.bytes_sent = (50 * 512) as u64;
        metrics.bytes_received = (45 * 512) as u64;
        metrics.total_rtt_micros = 50000;
        metrics.rtt_count = 45;
        metrics.min_rtt_micros = Some(800);
        metrics.max_rtt_micros = Some(1200);
        metrics.inter_arrival_jitter_micros_sum = 1000;
        metrics.jitter_count = 44;

        // Raw samples: (timestamp_ms_since_start, bytes_in_interval)
        // Sample 1: At 1s (1000ms), 125000 bytes received in the interval (0-1000ms)
        // Sample 2: At 2s (2000ms), 130000 bytes received in the interval (1000-2000ms)
        // Sample 3: At 2.5s (2500ms), 60000 bytes received in the interval (2000-2500ms)
        metrics.bandwidth_samples = vec![
            (1000, 125000), // 125000 B in 1s  -> 1 Mbps
            (2000, 130000), // 130000 B in 1s  -> 1.04 Mbps
            (2500, 60000),  // 60000 B in 0.5s -> 0.96 Mbps
        ];

        let anomalies = vec![
            AnomalyEvent {
                timestamp_ms: 1500,
                anomaly_type: crate::anomalies::AnomalyType::PacketLoss,
                description: "Packet sequence 23 lost".to_string(),
            }
        ];
        // metrics.anomalies is not populated in this specific test setup directly,
        // so TestSummary.anomalies will be empty unless we assign to metrics.anomalies.
        // For this test, let's assume anomalies are directly part of metrics.
        metrics.anomalies = anomalies; // Assign the test anomalies to the metrics struct

        let duration = Duration::from_secs_f64(5.05);

        // Call the updated generate_summary
        let summary = generate_summary(&config, metrics, duration);

        assert_eq!(summary.test_config.target_ip, "127.0.0.1");
        assert_eq!(summary.test_config.target_ip, "127.0.0.1");
        assert_eq!(summary.overall_metrics.packets_sent, 50);
        assert_eq!(summary.overall_metrics.packets_received, 45);
        assert_eq!(summary.anomalies.len(), 1);
        assert_eq!(summary.test_duration_actual_secs, 5.05);

        // Check processed bandwidth_over_time
        // Expected:
        // 1. (1.0s, 1.0 Mbps) from (1000ms, 125000B) interval 0-1000ms
        // 2. (2.0s, 1.04 Mbps) from (2000ms, 130000B) interval 1000-2000ms
        // 3. (2.5s, 0.96 Mbps) from (2500ms, 60000B) interval 2000-2500ms
        assert_eq!(summary.bandwidth_over_time.len(), 3);
        assert_eq!(summary.bandwidth_over_time[0].0, 1.0); // time in seconds
        assert!((summary.bandwidth_over_time[0].1 - 1.0).abs() < 0.001); // mbps

        assert_eq!(summary.bandwidth_over_time[1].0, 2.0);
        assert!((summary.bandwidth_over_time[1].1 - 1.04).abs() < 0.001);

        assert_eq!(summary.bandwidth_over_time[2].0, 2.5);
        assert!((summary.bandwidth_over_time[2].1 - 0.96).abs() < 0.001);

        println!("Generated test summary: {:#?}", summary);

        // Test HTML report generation
        let html_output = generate_html_report_string(&summary);
        assert!(html_output.is_ok(), "HTML report generation failed: {:?}", html_output.err());
        let html_content = html_output.unwrap();

        // Basic checks for HTML content
        assert!(html_content.contains("<title>NetStats Test Report</title>"));
        assert!(html_content.contains("<h2>Overall Metrics</h2>"));
        assert!(html_content.contains("id=\"bandwidthChart\""));
        assert!(html_content.contains("127.0.0.1")); // Check if config data is rendered
        assert!(html_content.contains("1.00 Mbps")); // Check if a bandwidth value is rendered (approx)

        // Optionally, write to a file for manual inspection:
        // use std::fs::File;
        // use std::io::Write;
        // let mut file = File::create("test_report.html").unwrap();
        // file.write_all(html_content.as_bytes()).unwrap();
        // println!("Test report written to test_report.html");
    }
}
