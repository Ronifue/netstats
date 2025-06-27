// This is the core library crate for netstats.
// It will contain all the backend logic for network testing,
// analysis, and report generation.

pub mod anomalies;   // Logic for detecting defined network anomalies
pub mod config;      // Test configuration structures
pub mod metrics;     // Logic for calculating metrics (loss, latency, jitter, bandwidth)
pub mod network;     // TCP/UDP client/server logic
pub mod packet;      // Packet definitions, serialization/deserialization
pub mod reporter;    // Data aggregation and preparing data for reports
pub mod benchmark;   // For self-contained benchmark logic

pub fn greet() {
    println!("Hello from netstats_core library! This is the place for core logic.");
}

// The main test execution logic is now in network::run_network_test
// and is called directly from the GUI's worker thread.
// The old run_test placeholder is removed.

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn it_works() {
        greet();
        assert_eq!(2 + 2, 4);
    }

    // basic_config_test was moved to config.rs
}
