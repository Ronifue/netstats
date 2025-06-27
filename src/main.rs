// Import the generated Rust code from the .slint file
slint::include_modules!();

use netstats_core::config::{TestConfig, Protocol, TestMode, TcpBidirectionalMode};
use netstats_core::metrics::TestMetrics; // For potential real-time updates
use netstats_core::reporter::TestSummary; // For displaying summary
use netstats_core::anomalies::AnomalyEvent; // For displaying anomalies

use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration; // For actual test duration, not GUI value
use slint::SharedString;


fn main() -> Result<(), slint::PlatformError> {
    let ui = AppWindow::new()?;

    let ui_handle = ui.as_weak(); // Weak handle for callbacks

    // --- State for Core Logic ---
    // Use Arc<Mutex<Option<TestSummary>>> to store the latest test result
    let latest_summary: Arc<Mutex<Option<TestSummary>>> = Arc::new(Mutex::new(None));


    // --- Callbacks ---
    ui.on_start_test_clicked(move || {
        let ui = ui_handle.unwrap();
        ui.set_test_in_progress(true);
        ui.set_status_text("Starting test...".into());
        ui.set_results_summary("".into()); // Clear previous results
        ui.set_html_report_path("".into());


        // Gather config from UI properties
        let target_ip = ui.get_target_ip().to_string();
        let target_port = ui.get_target_port() as u16;
        let duration_secs = ui.get_duration_secs() as u64;
        let tick_rate_hz = ui.get_tick_rate_hz() as u32;
        let packet_size_bytes = ui.get_packet_size_bytes() as usize;

        let packet_size_range = if ui.get_use_random_packet_size() {
            let min_size = ui.get_random_min_size() as usize;
            let max_size = ui.get_random_max_size() as usize;
            if min_size > 0 && max_size > 0 && min_size <= max_size {
                Some((min_size, max_size))
            } else {
                // TODO: Show error in UI if range is invalid
                ui.set_status_text("Error: Invalid random packet size range.".into());
                ui.set_test_in_progress(false);
                return;
            }
        } else {
            None
        };

        let protocol = match ui.get_protocol_options().get(ui.get_selected_protocol_idx() as usize).unwrap().id.as_str() {
            "udp" => Protocol::Udp,
            "tcp" => Protocol::Tcp,
            _ => Protocol::Udp, // Default
        };

        let test_mode = match ui.get_test_mode_options().get(ui.get_selected_test_mode_idx() as usize).unwrap().id.as_str() {
            "client" => TestMode::Client,
            "server" => TestMode::Server,
            "bidi" => TestMode::Bidirectional,
            _ => TestMode::Client, // Default
        };

        let tcp_bidi_mode = if protocol == Protocol::Tcp && test_mode == TestMode::Bidirectional {
            match ui.get_tcp_bidi_mode_options().get(ui.get_selected_tcp_bidi_mode_idx() as usize).unwrap().id.as_str() {
                "dual" => Some(TcpBidirectionalMode::DualStream),
                "single" => Some(TcpBidirectionalMode::SingleStream),
                _ => Some(TcpBidirectionalMode::DualStream), // Default
            }
        } else {
            None
        };

        let config = Arc::new(TestConfig {
            target_ip,
            target_port,
            test_duration_secs: duration_secs,
            tick_rate_hz,
            packet_size_bytes,
            packet_size_range,
            protocol,
            test_mode,
            tcp_bidirectional_mode: tcp_bidi_mode,
        });

        let metrics = Arc::new(Mutex::new(TestMetrics::default()));
        let summary_clone = Arc::clone(&latest_summary); // Clone Arc for thread
        let ui_handle_thread = ui.as_weak();

        // Spawn a new thread for the network test to avoid blocking the UI
        thread::spawn(move || {
            let rt = tokio::runtime::Runtime::new().unwrap();
            let core_config = Arc::clone(&config);
            let core_metrics = Arc::clone(&metrics);

            rt.block_on(async {
                match netstats_core::network::run_network_test(core_config, core_metrics).await {
                    Ok(()) => {
                        // Make final_metrics mutable to potentially add a high packet loss anomaly.
                        let mut final_metrics = Arc::try_unwrap(metrics)
                            .expect("Metrics Arc should be unique after test")
                            .into_inner()
                            .expect("Failed to unlock metrics");

                        let actual_duration = if let Some(start_time) = final_metrics.test_start_time {
                            start_time.elapsed()
                        } else {
                            Duration::from_secs(config.test_duration_secs) // Fallback
                        };

                        // Check for high packet loss anomaly based on config threshold
                        if let Some(loss_threshold_percent) = config.packet_loss_threshold_percent {
                            let loss_percentage = final_metrics.packet_loss_percentage();
                            if loss_percentage >= loss_threshold_percent {
                                // Timestamp the anomaly as occurring at the end of the test for summary purposes
                                let anomaly_timestamp_ms = final_metrics.test_start_time
                                    .map_or(0, |st| actual_duration.as_millis() as u128); // or st.elapsed().as_millis() before summary

                                final_metrics.anomalies.push(AnomalyEvent {
                                    timestamp_ms: anomaly_timestamp_ms,
                                    anomaly_type: netstats_core::anomalies::AnomalyType::PacketLoss, // Using existing PacketLoss type
                                    description: format!(
                                        "High packet loss detected: {:.2}% (threshold: {}%)",
                                        loss_percentage, loss_threshold_percent
                                    ),
                                });
                            }
                        }

                        // Call the updated generate_summary from reporter.rs
                        // It now takes (config, metrics, actual_duration)
                        // Anomalies are expected to be within final_metrics.anomalies
                        let summary = netstats_core::reporter::generate_summary(
                            &config,
                            final_metrics, // final_metrics is moved here
                            actual_duration,
                        );

                        let report_path_str = format!("netstats_report_{}.html", chrono::Local::now().format("%Y%m%d_%H%M%S"));
                        match netstats_core::reporter::generate_html_report_string(&summary) {
                            Ok(html_content) => {
                                if let Err(e) = std::fs::write(&report_path_str, html_content) {
                                    eprintln!("Failed to write HTML report: {}", e);
                                     let _ = slint::invoke_from_event_loop(move || {
                                        ui_handle_thread.unwrap().set_status_text(SharedString::from(format!("Test complete. Failed to write report: {}",e)));
                                    });
                                } else {
                                    let _ = slint::invoke_from_event_loop(move || {
                                        ui_handle_thread.unwrap().set_html_report_path(report_path_str.clone().into());
                                        ui_handle_thread.unwrap().set_status_text(SharedString::from(format!("Test complete! Report: {}", report_path_str)));
                                    });
                                }
                            }
                            Err(e) => {
                                eprintln!("Failed to generate HTML report: {}", e);
                                 let _ = slint::invoke_from_event_loop(move || {
                                    ui_handle_thread.unwrap().set_status_text(SharedString::from(format!("Test complete. Failed to gen HTML: {}",e)));
                                });
                            }
                        }
                        // Store summary for display in UI
                        let mut summary_guard = summary_clone.lock().unwrap();
                        *summary_guard = Some(summary);

                    }
                    Err(e) => {
                        eprintln!("Network test error: {:?}", e);
                        let error_msg = format!("Test Error: {:?}", e);
                         let _ = slint::invoke_from_event_loop(move || {
                            ui_handle_thread.unwrap().set_status_text(SharedString::from(error_msg));
                        });
                    }
                }
            });

            // Update UI after test completion (back on main thread via Slint event loop)
            let _ = slint::invoke_from_event_loop(move || {
                 ui_handle_thread.unwrap().set_test_in_progress(false);
                // Update summary text view if needed, or rely on report.
                if let Some(summary_data) = summary_clone.lock().unwrap().as_ref() {
                     ui_handle_thread.unwrap().set_results_summary(SharedString::from(format!("{:#?}", summary_data.overall_metrics)));
                }
            });
        });
    });

    ui.on_open_report_clicked(move || {
        let ui = ui_handle.unwrap();
        let report_path = ui.get_html_report_path();
        if !report_path.is_empty() {
            if let Err(e) = open::that(report_path.as_str()) {
                eprintln!("Failed to open report '{}': {}", report_path, e);
                ui.set_status_text(SharedString::from(format!("Error opening report: {}", e)));
            } else {
                ui.set_status_text("Report opened in browser.".into());
            }
        } else {
            ui.set_status_text("No report available to open.".into());
        }
    });

    ui.on_run_benchmark_clicked(move || {
        let ui = ui_handle.unwrap();
        ui.set_test_in_progress(true);
        ui.set_status_text("Running benchmark...".into());
        ui.set_results_summary("".into());
        ui.set_html_report_path("".into()); // Benchmarks don't generate HTML reports by default

        let ui_handle_thread = ui.as_weak();

        thread::spawn(move || {
            let rt = tokio::runtime::Runtime::new().unwrap();
            let benchmark_duration_secs = 10; // Standard duration for this benchmark
            let benchmark_packet_payload_size = 64;   // Standard small packet size

            let benchmark_result = rt.block_on(async {
                netstats_core::benchmark::run_udp_loopback_benchmark(
                    benchmark_duration_secs,
                    benchmark_packet_payload_size,
                )
                .await
            });

            let _ = slint::invoke_from_event_loop(move || {
                let ui = ui_handle_thread.unwrap();
                ui.set_test_in_progress(false);
                match benchmark_result {
                    Ok(summary) => {
                        let result_text = format!(
                            "Benchmark Complete ({}s, {}B payload):\nClient Sent: {} packets ({:.2} PPS)\nServer Received: {} packets ({:.2} PPS)\nServer Throughput: {:.2} Mbps",
                            summary.duration_secs,
                            summary.packet_payload_size_bytes,
                            summary.client_packets_sent,
                            summary.client_pps,
                            summary.server_packets_received,
                            summary.server_pps,
                            summary.server_mbps
                        );
                        ui.set_status_text("Benchmark complete!".into());
                        ui.set_results_summary(result_text.into());
                    }
                    Err(e) => {
                        let error_msg = format!("Benchmark Error: {:?}", e);
                        ui.set_status_text(error_msg.clone().into());
                        ui.set_results_summary(error_msg.into());
                    }
                }
            });
        });
    });

    ui.run()
}
