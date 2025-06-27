// network.rs
use crate::config::{Protocol, TestConfig, TestMode, TcpBidirectionalMode};
use crate::packet::CustomPacket;
use crate::metrics::TestMetrics;
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use std::io;
use tokio::net::{TcpStream, TcpListener, UdpSocket};
use tokio::sync::mpsc; // For potential internal signaling if needed

#[derive(Debug)] // Added Debug derive
pub enum NetworkError {
    IoError(std::io::Error),
    SerializationError(String), // Changed from no arg to String
    HandshakeError(String),
    Timeout,
    Other(String),
    InvalidAddress(String), // More specific error type
    UnsupportedMode(String), // For unsupported combinations
}

impl From<std::io::Error> for NetworkError {
    fn from(err: std::io::Error) -> Self {
        NetworkError::IoError(err)
    }
}

impl From<bincode::Error> for NetworkError {
    fn from(err: bincode::Error) -> Self {
        NetworkError::SerializationError(err.to_string())
    }
}


// --- Main Dispatch Function ---
pub async fn run_network_test(
    config: Arc<TestConfig>,
    metrics: Arc<Mutex<TestMetrics>>,
) -> Result<(), NetworkError> {
    // Initialize metrics start time and configure anomaly detection thresholds
    if let Ok(mut m) = metrics.lock() {
        m.init_start_time();
        m.configure_anomaly_detection(&config); // Pass the config to set thresholds
    } else {
        return Err(NetworkError::Other("Failed to lock metrics for init/config.".to_string()));
    }


    match config.test_mode {
        TestMode::Client => {
            println!("Mode: Client, Protocol: {:?}", config.protocol);
            let remote_addr = format!("{}:{}", config.target_ip, config.target_port)
                .parse::<SocketAddr>()
                .map_err(|e| NetworkError::InvalidAddress(format!("Invalid target address: {} - {}", config.target_ip, e)))?;
            match config.protocol {
                Protocol::Udp => udp_send_loop(Arc::clone(&config), remote_addr, metrics, true).await?, // is_primary_sender = true
                Protocol::Tcp => {
                    let stream = tcp_connect(remote_addr).await?;
                    let (reader, writer) = tokio::io::split(stream);
                    // In client-only mode, primarily sends. Receiving might be for ACKs.
                    // For now, just run send_loop. Acks would require a receive_loop too.
                    tcp_send_loop(Arc::clone(&config), writer, metrics, true).await?;
                }
            }
        }
        TestMode::Server => {
            println!("Mode: Server, Protocol: {:?}", config.protocol);
            let listen_addr = format!("0.0.0.0:{}", config.target_port)
                .parse::<SocketAddr>()
                .map_err(|e| NetworkError::InvalidAddress(format!("Invalid listen address: {}", e)))?;
            match config.protocol {
                Protocol::Udp => {
                    let socket = Arc::new(UdpSocket::bind(listen_addr).await?);
                    udp_receive_loop(Arc::clone(&config), socket, metrics).await?;
                }
                Protocol::Tcp => {
                    let listener = tcp_listen(listen_addr).await?;
                    println!("TCP Server: Waiting for a connection on {}...", listen_addr);
                    let (stream, client_addr) = listener.accept().await?;
                    println!("TCP Server: Accepted connection from {}", client_addr);
                    let (reader, writer) = tokio::io::split(stream);
                    // In server-only mode, primarily receives. Sending might be for ACKs.
                    // For now, just run receive_loop. ACKs would require a send_loop too.
                    tcp_receive_loop(Arc::clone(&config), reader, metrics).await?;
                }
            }
        }
        TestMode::Bidirectional => {
            println!("Mode: Bidirectional, Protocol: {:?}", config.protocol);
            let remote_addr = format!("{}:{}", config.target_ip, config.target_port)
                .parse::<SocketAddr>()
                .map_err(|e| NetworkError::InvalidAddress(format!("Invalid target address for sending: {} - {}", config.target_ip, e)))?;

            // Local listen port for receiving part of bidirectional test.
            // For now, assume it's the same as target_port. This might need refinement
            // if client and server are on the same machine or for more complex setups.
            let local_listen_port = config.target_port; // Could be a separate config field: config.local_listen_port
            let listen_addr = format!("0.0.0.0:{}", local_listen_port)
                .parse::<SocketAddr>()
                .map_err(|e| NetworkError::InvalidAddress(format!("Invalid listen address for receiving: {}", e)))?;

            match config.protocol {
                Protocol::Udp => {
                    let send_config = Arc::clone(&config);
                    let recv_config = Arc::clone(&config);
                    let metrics_send = Arc::clone(&metrics);
                    let metrics_recv = Arc::clone(&metrics);

                    let listen_socket = Arc::new(UdpSocket::bind(listen_addr).await?);
                    let recv_socket_clone = Arc::clone(&listen_socket);

                    let send_handle = tokio::spawn(async move {
                        udp_send_loop(send_config, remote_addr, metrics_send, true).await // is_primary_sender = true
                    });
                    let recv_handle = tokio::spawn(async move {
                        udp_receive_loop(recv_config, recv_socket_clone, metrics_recv).await
                    });

                    // Wait for both tasks to complete
                    let (send_result, recv_result) = tokio::join!(send_handle, recv_handle);
                    send_result.unwrap_or(Err(NetworkError::Other("UDP send task panicked".to_string())))?;
                    recv_result.unwrap_or(Err(NetworkError::Other("UDP recv task panicked".to_string())))?;
                }
                Protocol::Tcp => {
                    // Determine TCP bidirectional strategy
                    let tcp_bidi_mode = config.tcp_bidirectional_mode.unwrap_or(TcpBidirectionalMode::DualStream);
                    match tcp_bidi_mode {
                        TcpBidirectionalMode::DualStream => {
                            println!("TCP Bidirectional: Dual Stream Mode");
                            // Task 1: Outgoing connection for sending, also receives on this stream if peer sends back
                            let client_send_config = Arc::clone(&config);
                            let client_metrics = Arc::clone(&metrics);
                            let client_handle = tokio::spawn(async move {
                                let stream = tcp_connect(remote_addr).await?;
                                let peer_display = stream.peer_addr().map_or("unknown peer".to_string(), |a| a.to_string());
                                println!("TCP BiDi (Dual): Connected to {} for sending.", peer_display);
                                let (reader, writer) = tokio::io::split(stream);

                                // For dual stream, the "client" task primarily sends on its outgoing connection
                                // and might receive ACKs or control messages.
                                // The "server" task primarily receives on its incoming connection
                                // and might send ACKs or control messages.
                                // If full data is to be exchanged both ways on EACH stream, then both loops run fully.
                                // For now, let's assume the client task is primary sender on its stream,
                                // and server task is primary receiver on its stream.
                                // Any "return" traffic on these streams (like ACKs) would be handled by the other loop.
                                let _ = tokio::try_join!(
                                    tcp_send_loop(Arc::clone(&client_send_config), writer, Arc::clone(&client_metrics), true),
                                    // Secondary receive loop on the client's outgoing stream (e.g., for control/acks)
                                    // This receive loop should not run for the full test_duration if it's just for ACKs.
                                    // This needs careful thought: what does this reader do? If it's expecting data, it needs to run.
                                    // For now, assume it's a full receive loop.
                                    tcp_receive_loop(Arc::clone(&client_send_config), reader, Arc::clone(&client_metrics))
                                );
                                Ok::<(), NetworkError>(())
                            });

                            // Task 2: Incoming connection for receiving
                            let server_recv_config = Arc::clone(&config);
                            let server_metrics = Arc::clone(&metrics);
                            let server_handle = tokio::spawn(async move {
                                let listener = tcp_listen(listen_addr).await?;
                                println!("TCP BiDi (Dual): Listening on {} for incoming connection.", listen_addr);
                                let (stream, client_addr) = listener.accept().await?;
                                println!("TCP BiDi (Dual): Accepted connection from {} for receiving.", client_addr);
                                let (reader, writer) = tokio::io::split(stream);

                                let _ = tokio::try_join!(
                                    tcp_receive_loop(Arc::clone(&server_recv_config), reader, Arc::clone(&server_metrics)),
                                    // Secondary send loop on the server's incoming stream (e.g., for control/acks)
                                    tcp_send_loop(Arc::clone(&server_recv_config), writer, Arc::clone(&server_metrics), false) // is_primary_sender = false
                                );
                                Ok::<(), NetworkError>(())
                            });

                            let (client_result, server_result) = tokio::join!(client_handle, server_handle);
                            client_result.map_err(|e| NetworkError::Other(format!("TCP client task error: {}", e)))??;
                            server_result.map_err(|e| NetworkError::Other(format!("TCP server task error: {}", e)))??;

                        }
                        TcpBidirectionalMode::SingleStream => {
                            println!("TCP Bidirectional: Single Stream Mode");
                            // Requires one side to be designated initiator.
                            // This could be based on IP comparison, or a specific config flag.
                            // For now, let's assume a simple heuristic or that it's handled by how user starts it.
                            // The one with "lower" IP:Port string initiates, for example.
                            // Or more simply, one is "client_initiator" one is "server_listener" for single stream setup.
                            // This part needs a clear "role" for single stream setup.
                            // Let's assume for now this mode is initiated by the "client" role in a traditional sense.
                            // This means `run_network_test` needs to know if it's the "initiator" or "listener" for single stream.
                            // This is getting complex for a simple config.
                            // Alternative: GUI has "Start Single Stream Test (as Initiator)" and "Listen for Single Stream Test".
                            // For now, let's make a simplifying assumption: if local is "client-like", it initiates.
                            // This is not robust.
                            // A better way: Add a boolean to TestConfig `is_single_stream_initiator: bool`
                            // For now, this mode will be a TODO for full implementation detail.

                            // Simplified: if current instance is "targetting" a remote, it initiates.
                            // This means both sides can't be generic "Bidirectional" for SingleStream without more info.
                            // The user would have to run one as "SingleStreamClient" and other as "SingleStreamServer".
                            // Let's assume TestMode::Client with a flag would initiate, TestMode::Server would listen for it.
                            // This means SingleStream is not a top-level TestMode but a TCP behavior.

                            // Re-evaluating: The config `tcp_bidirectional_mode` should be enough.
                            // One peer will act as connector, the other as listener, then both use the stream.
                            // We need a way to decide who connects. A common way is string comparison of addresses.
                            let local_addr_for_comparison = format!("0.0.0.0:{}", local_listen_port); // Approximation
                            let should_initiate_connection = local_addr_for_comparison < remote_addr.to_string(); // Simple heuristic

                            let send_config = Arc::clone(&config);
                            let recv_config = Arc::clone(&config); // Same config for both directions
                            let metrics_send = Arc::clone(&metrics);
                            let metrics_recv = Arc::clone(&metrics);

                            let stream: TcpStream; // Not Arc needed before split
                            if should_initiate_connection {
                                println!("TCP BiDi (Single): Initiating connection to {}", remote_addr);
                                stream = tcp_connect(remote_addr).await?;
                                let peer_display = stream.peer_addr().map_or("unknown peer".to_string(), |a| a.to_string());
                                println!("TCP BiDi (Single): Connected to {}", peer_display);
                            } else {
                                let listener = tcp_listen(listen_addr).await?;
                                println!("TCP BiDi (Single): Listening on {} for incoming connection.", listen_addr);
                                let (accepted_stream, client_addr) = listener.accept().await?;
                                stream = accepted_stream;
                                println!("TCP BiDi (Single): Accepted connection from {}", client_addr);
                            }

                            let (reader, writer) = tokio::io::split(stream);

                            let send_handle = tokio::spawn(async move {
                                // One side needs to be primary sender, the other can be too, or just for ACKs.
                                // The heuristic for `should_initiate_connection` can also decide primary sender role.
                                tcp_send_loop(send_config, writer, metrics_send, should_initiate_connection).await
                            });
                            let recv_handle = tokio::spawn(async move {
                                tcp_receive_loop(recv_config, reader, metrics_recv).await
                            });

                            let (send_result, recv_result) = tokio::join!(send_handle, recv_handle);
                            send_result.unwrap_or(Err(NetworkError::Other("TCP single-stream send task panicked".to_string())))?;
                            recv_result.unwrap_or(Err(NetworkError::Other("TCP single-stream recv task panicked".to_string())))?;
                        }
                    }
                }
            }
        }
    }
    Ok(())
}


// --- UDP Loops ---
async fn udp_send_loop(
    config: Arc<TestConfig>,
    remote_addr: SocketAddr,
    metrics: Arc<Mutex<TestMetrics>>,
    is_primary_sender: bool, // True if this loop drives the main packet sending sequence based on tickrate
) -> Result<(), NetworkError> {
    // Bind to a local port. "0.0.0.0:0" lets the OS choose.
    // For BiDi, the socket might be shared if we want to receive ACKs on the same one.
    // Or, it could be a dedicated sending socket.
    // For simplicity, let's use a new socket for sending. The receive_loop will use the listening one.
    let socket = UdpSocket::bind("0.0.0.0:0").await?;
    socket.connect(remote_addr).await?; // Connects the UDP socket to a default remote address
    println!("UDP SendLoop: Sending to {} from local addr {}", remote_addr, socket.local_addr()?);

    let test_start_time = metrics.lock().unwrap().test_start_time.unwrap_or_else(Instant::now);
    let test_duration = config.total_duration();
    let tick_interval = config.tick_interval();

    let mut rng = if config.packet_size_range.is_some() { Some(rand::thread_rng()) } else { None };
    let mut sequence_number: u32 = 0;

    let mut ticker = if config.tick_rate_hz > 0 { // Normal tick-based sending
        Some(tokio::time::interval_at(tokio::time::Instant::now() + tick_interval, tick_interval))
    } else { // Tick rate of 0 means "as fast as possible" (AFAP) for benchmark
        println!("UDP SendLoop: AFAP mode enabled (tick_rate_hz == 0)");
        None
    };

    // Only the primary sender respects the full test duration for sending.
    let loop_duration = if is_primary_sender { test_duration } else { Duration::MAX };

    while Instant::now().duration_since(test_start_time) < loop_duration {
        if is_primary_sender {
            if let Some(ref mut t) = ticker { // Normal tick-based
                t.tick().await;
            } else { // AFAP mode for primary sender
                tokio::task::yield_now().await; // Yield to allow other tasks (like receiver) to run
            }
        } else { // Non-primary sender logic (e.g., for ACKs or other direction in BiDi)
            // This part is not typically used in AFAP benchmark mode.
            // If it were, it would need its own rate control or be event-driven.
            // For now, assume non-primary senders are not in AFAP mode or this loop isn't hit in that benchmark.
            if config.tick_rate_hz > 0 { // Ensure tick_interval is valid
                 tokio::time::sleep(tick_interval).await;
            } else {
                // If non-primary and main config is AFAP, this is undefined; yield to be safe.
                tokio::task::yield_now().await;
            }
        }

        let current_packet_size = match config.packet_size_range {
            Some((min_size, max_size)) => {
                if let Some(ref mut r) = rng { use rand::Rng; r.gen_range(min_size..=max_size) }
                else { config.packet_size_bytes }
            }
            None => config.packet_size_bytes,
        };

        let packet_type = if is_primary_sender {
            crate::packet::PacketType::Data // Primary data stream
        } else {
            crate::packet::PacketType::Data // Also data, but from the "other side" of bidi
            // Or could be EchoRequest if we want to measure RTT for this direction
        };

        // For UDP RTT measurement, client sends EchoRequest and expects EchoReply
        let packet = CustomPacket::new_echo_request(sequence_number, current_packet_size);

        let sent_payload = packet.to_bytes()?;
        let send_time = Instant::now();
        socket.send(&sent_payload).await?;

        metrics.lock().unwrap().record_packet_sent(sent_payload.len());

        // Try to receive EchoReply for RTT - only if this loop is primary sender
        if is_primary_sender {
            let mut recv_buf = vec![0u8; 2048]; // Buffer for the reply
            // Set a timeout for receiving the reply, e.g., 500ms or related to tick_interval
            // A simple way is to use tokio::time::timeout.
            // If the main loop is driven by `ticker.tick().await`, waiting here can mess with timing.
            // This receive should be non-blocking or very short timeout.
            // For a proper RTT test, the send loop might be simpler: send, try recv with timeout, repeat.
            // Or, have a separate task for receiving replies.

            // Simplified non-blocking attempt for this pass:
            // This is not ideal as try_recv is not async.
            // A better approach: use socket.recv() in a tokio::select! with a timeout.
            match tokio::time::timeout(Duration::from_millis(200), socket.recv(&mut recv_buf)).await {
                Ok(Ok(len)) => { // Received something within timeout
                    let rtt = send_time.elapsed().as_micros();
                    match CustomPacket::from_bytes(&recv_buf[..len]) {
                        Ok(reply_packet) => {
                            if reply_packet.header.packet_type == crate::packet::PacketType::EchoReply &&
                               reply_packet.header.sequence_number == sequence_number {
                                metrics.lock().unwrap().record_packet_received(len, rtt);
                            } else {
                                // Received unexpected packet or old reply
                                println!("UDP SendLoop: Received unexpected packet type {:?} or seq {} (expected EchoReply for seq {})",
                                         reply_packet.header.packet_type, reply_packet.header.sequence_number, sequence_number);
                            }
                        }
                        Err(_e) => { /* Malformed reply */ }
                    }
                }
                Ok(Err(_e)) => { /* Socket error on recv */ }
                Err(_elapsed) => { /* Timeout waiting for EchoReply */ }
            }
        }

        sequence_number = sequence_number.wrapping_add(1);

        if !is_primary_sender && Instant::now().duration_since(test_start_time) >= test_duration {
            // If this is the secondary sender in a bidi test, stop after main duration.
            break;
        }
    }
    println!("UDP SendLoop to {}: Finished.", remote_addr);
    Ok(())
}

async fn udp_receive_loop(
    config: Arc<TestConfig>,
    socket: Arc<UdpSocket>, // Use an Arc for the socket
    metrics: Arc<Mutex<TestMetrics>>,
) -> Result<(), NetworkError> {
    println!("UDP ReceiveLoop: Listening on {}", socket.local_addr()?);
    let mut buf = vec![0u8; 4096]; // Increased buffer size
    let mut highest_udp_seq_received: Option<u32> = None; // For out-of-order detection

    let test_start_time = metrics.lock().unwrap().test_start_time.unwrap_or_else(Instant::now);
    let bandwidth_sample_interval_ms = 1000; // 1 second
    let mut bandwidth_sampler = tokio::time::interval_at(
        tokio::time::Instant::now() + Duration::from_millis(bandwidth_sample_interval_ms),
        Duration::from_millis(bandwidth_sample_interval_ms)
    );

    // Server loop runs for test duration + grace period to catch trailing packets
    let server_lifetime = config.total_duration() + Duration::from_secs(5);

    loop {
        tokio::select! {
            biased;

            _ = tokio::time::sleep_until(tokio::time::Instant::from_std(test_start_time + server_lifetime)) => {
                println!("UDP ReceiveLoop on {}: Test duration likely ended. Taking final bandwidth sample and shutting down.", socket.local_addr()?);
                if let Ok(mut metrics_guard) = metrics.lock() {
                    if let Some(start_time_instant) = metrics_guard.test_start_time { // Use the stored Instant
                        let current_test_time_ms = Instant::now().duration_since(start_time_instant).as_millis();
                        metrics_guard.take_bandwidth_sample(current_test_time_ms);
                    }
                }
                break;
            }

            result = socket.recv_from(&mut buf) => {
                match result {
                    Ok((len, src_addr)) => {
                        let data = &buf[..len];
                        match CustomPacket::from_bytes(data) {
                            Ok(packet) => {
                                let current_seq = packet.header.sequence_number;
                                let mut is_out_of_order = false;

                                { // Metrics lock scope
                                    let mut metrics_guard = metrics.lock().unwrap();
                                    metrics_guard.record_packet_received(len, 0); // RTT 0 for server-side

                                    if let Some(highest_seen) = highest_udp_seq_received {
                                        // Crude wrap-around check (e.g. seq 10 received after seq 4_000_000_000)
                                        let is_likely_wrap = current_seq < (u32::MAX / 4) && highest_seen > (u32::MAX * 3 / 4);
                                        if current_seq < highest_seen && !is_likely_wrap {
                                            is_out_of_order = true;
                                            metrics_guard.out_of_order_count += 1;

                                            let anomaly_time_ms = metrics_guard.test_start_time
                                                .map_or(0, |st| Instant::now().duration_since(st).as_millis());
                                            metrics_guard.anomalies.push(crate::anomalies::AnomalyEvent {
                                                timestamp_ms: anomaly_time_ms,
                                                anomaly_type: crate::anomalies::AnomalyType::OutOfOrder,
                                                description: format!("UDP Packet Seq: {} received after {}", current_seq, highest_seen),
                                            });
                                        }
                                    }
                                } // Metrics lock scope ends

                                // Update highest_udp_seq_received, consider it even if OOO for next packet comparisons
                                // but primary update should be for in-order or new highest.
                                // If it's out of order, we don't necessarily update highest_udp_seq_received downwards.
                                // It should always track the actual highest sequence number encountered so far to detect subsequent OOO packets.
                                highest_udp_seq_received = Some(highest_udp_seq_received.map_or(current_seq, |h| h.max(current_seq)));


                                if packet.header.packet_type == crate::packet::PacketType::EchoRequest {
                                    let reply_packet = CustomPacket::new_echo_reply(&packet);
                                    if let Ok(reply_bytes) = reply_packet.to_bytes() {
                                        if let Err(e) = socket.send_to(&reply_bytes, src_addr).await {
                                            eprintln!("UDP Server: Error sending echo reply: {}", e);
                                        } else {
                                            // metrics.lock().unwrap().record_packet_sent(reply_bytes.len()); // If server ACKs are counted
                                        }
                                    }
                                }
                            }
                            Err(e) => eprintln!("UDP ReceiveLoop on {}: Failed to parse CustomPacket from {}: {:?}", socket.local_addr()?, src_addr, e),
                        }
                    }
                    Err(e) => {
                        // Handle specific errors like ConnectionReset which can occur on UDP
                        if e.kind() == io::ErrorKind::ConnectionReset {
                            eprintln!("UDP ReceiveLoop on {}: ConnectionReset from a client (ICMP Port Unreachable?)", socket.local_addr()?);
                            // This is not fatal for a UDP server, continue listening.
                        } else {
                            eprintln!("UDP ReceiveLoop on {}: Error receiving data: {}", socket.local_addr()?, e);
                            // For other errors, you might choose to break or log and continue.
                            // If the socket is truly broken, this loop might spin. Consider error count limits.
                            break; // For now, break on other I/O errors.
                        }
                    }
                }
            }

            _ = bandwidth_sampler.tick() => {
                if let Ok(mut metrics_guard) = metrics.lock() {
                    if let Some(start_time_instant) = metrics_guard.test_start_time {
                        let current_test_time_ms = Instant::now().duration_since(start_time_instant).as_millis();
                        metrics_guard.take_bandwidth_sample(current_test_time_ms);
                    }
                }
            }
        }
    }
    println!("UDP ReceiveLoop on {}: Finished.", socket.local_addr()?);
    Ok(())
}


// --- TCP Stubs (to be fully implemented) ---
async fn tcp_connect(remote_addr: SocketAddr) -> Result<TcpStream, NetworkError> {
    println!("TCP: Attempting to connect to {}...", remote_addr);
    match TcpStream::connect(remote_addr).await {
        Ok(stream) => {
            println!("TCP: Successfully connected to {}", remote_addr);
            Ok(stream)
        }
        Err(e) => {
            println!("TCP: Failed to connect to {}: {}", remote_addr, e);
            Err(NetworkError::IoError(e))
        }
    }
}

async fn tcp_listen(listen_addr: SocketAddr) -> Result<TcpListener, NetworkError> {
    println!("TCP: Attempting to listen on {}...", listen_addr);
    match TcpListener::bind(listen_addr).await {
        Ok(listener) => {
            println!("TCP: Successfully listening on {}", listen_addr);
            Ok(listener)
        }
        Err(e) => {
            println!("TCP: Failed to listen on {}: {}", listen_addr, e);
            Err(NetworkError::IoError(e))
        }
    }
}

async fn tcp_send_loop(
    config: Arc<TestConfig>,
    mut writer: tokio::io::WriteHalf<TcpStream>, // Changed to WriteHalf
    metrics: Arc<Mutex<TestMetrics>>,
    is_primary_sender: bool,
) -> Result<(), NetworkError> {
    // Note: peer_addr might not be available from WriteHalf directly.
    // It should be logged by the caller who has the full stream before splitting.
    println!("TCP SendLoop: Started (is_primary_sender: {})", is_primary_sender);

    use tokio::io::AsyncWriteExt;

    let test_start_time = metrics.lock().unwrap().test_start_time.unwrap_or_else(Instant::now);
    let test_duration = config.total_duration();
    let tick_interval = config.tick_interval();
    let mut rng = if config.packet_size_range.is_some() { Some(rand::thread_rng()) } else { None };
    let mut sequence_number: u32 = 0;
    let mut ticker = tokio::time::interval_at(tokio::time::Instant::now() + tick_interval, tick_interval);

    let loop_duration = if is_primary_sender { test_duration } else { Duration::MAX };

    while Instant::now().duration_since(test_start_time) < loop_duration {
         if is_primary_sender {
            ticker.tick().await;
        } else {
            // Non-primary senders in TCP bidi might be event-driven (e.g. ACKs)
            // or could also send data not strictly tied to the main tickrate.
            // For now, let's assume it might also send data periodically if not primary.
            // If this loop is ONLY for ACKs, it would look very different (event-driven).
            tokio::time::sleep(tick_interval).await;
        }

        let current_packet_size = match config.packet_size_range {
            Some((min_size, max_size)) => {
                if let Some(ref mut r) = rng { use rand::Rng; r.gen_range(min_size..=max_size) }
                else { config.packet_size_bytes }
            }
            None => config.packet_size_bytes,
        };

        // TODO: Define packet type more meaningfully if not primary_sender (e.g. Ack, EchoReply)
        let packet = CustomPacket::new_data_packet(sequence_number, current_packet_size);
        let data = packet.to_bytes()?;

        // Frame the packet: send length (u32) then data
        let len_bytes = (data.len() as u32).to_be_bytes();

        writer.write_all(&len_bytes).await.map_err(|e| NetworkError::IoError(e))?;
        writer.write_all(&data).await.map_err(|e| NetworkError::IoError(e))?;
        // Consider writer.flush().await? if timely delivery is critical and Nagle might be an issue.

        metrics.lock().unwrap().record_packet_sent(data.len() + 4); // +4 for length prefix
        sequence_number = sequence_number.wrapping_add(1);

        if !is_primary_sender && Instant::now().duration_since(test_start_time) >= test_duration {
            // If this is the secondary sender in a bidi test, stop after main duration.
            break;
        }
    }

    if let Err(e) = writer.shutdown().await { // Gracefully close the write half
        eprintln!("TCP SendLoop: Error shutting down writer: {}", e);
    }
    println!("TCP SendLoop: Finished (is_primary_sender: {}).", is_primary_sender);
    Ok(())
}

async fn tcp_receive_loop(
    config: Arc<TestConfig>,
    mut reader: tokio::io::ReadHalf<TcpStream>, // Changed to ReadHalf
    metrics: Arc<Mutex<TestMetrics>>,
) -> Result<(), NetworkError> {
    println!("TCP ReceiveLoop: Started.");
    use tokio::io::AsyncReadExt;

    let test_start_time = metrics.lock().unwrap().test_start_time.unwrap_or_else(Instant::now);
    let bandwidth_sample_interval_ms = 1000;
    let mut bandwidth_sampler = tokio::time::interval_at(
        tokio::time::Instant::now() + Duration::from_millis(bandwidth_sample_interval_ms),
        Duration::from_millis(bandwidth_sample_interval_ms)
    );
    let server_lifetime = config.total_duration() + Duration::from_secs(5); // Grace period

    // Placeholder for reading loop
    // Actual TCP receive needs framing, e.g. send packet length first, then packet.
    // For now, simulate activity.
    // Similar to tcp_send_loop, this function should take an OwnedReadHalf.
    // The current signature `stream: Arc<TcpStream>` is problematic for direct read loop
    // if a send loop is also trying to use the same Arc directly.
    use tokio::io::AsyncReadExt;
    // let peer_addr = stream.peer_addr().ok(); // Not available on ReadHalf, log from caller if needed
    println!("TCP ReceiveLoop: Placeholder section (simulating duration). Actual logic below.");

    // Simulate test duration (Placeholder part)
    // tokio::time::sleep(config.total_duration() + Duration::from_secs(5)).await; // Grace period for receiver
    // This sleep was part of the placeholder, the actual loop is below.

    let mut length_buffer = [0u8; 4]; // To read the u32 length prefix
    let mut packet_buffer = Vec::with_capacity(config.packet_size_bytes.max(1024) * 2); // Initial capacity

    loop {
        tokio::select! {
            biased; // Prioritize packet reading over sampling or timeout

            _ = tokio::time::sleep_until(tokio::time::Instant::from_std(test_start_time + server_lifetime)) => {
                println!("TCP ReceiveLoop: Test duration likely ended.");
                 if let Ok(mut metrics_guard) = metrics.lock() {
                    if let Some(start_time_instant) = metrics_guard.test_start_time {
                        let current_test_time_ms = Instant::now().duration_since(start_time_instant).as_millis();
                        metrics_guard.take_bandwidth_sample(current_test_time_ms);
                    }
                }
                break; // Exit loop
            }

            // 1. Read packet length (u32)
            read_len_result = reader.read_exact(&mut length_buffer) => {
                match read_len_result {
                    Ok(_) => {
                        let packet_len = u32::from_be_bytes(length_buffer) as usize;

                        if packet_len == 0 { // Could be a keep-alive or shutdown signal
                            println!("TCP ReceiveLoop: Received 0-length packet, possibly EOF or keep-alive.");
                            continue; // Or break, depending on protocol for 0-len
                        }
                        if packet_len > packet_buffer.capacity() { // Basic sanity check for length
                             if packet_len > 10 * 1024 * 1024 { // e.g. 10MB limit
                                eprintln!("TCP ReceiveLoop: Excessive packet length received: {}, closing connection.", packet_len);
                                return Err(NetworkError::SerializationError("Excessive packet length".to_string()));
                            }
                            packet_buffer.reserve(packet_len); // Grow buffer if needed
                        }
                        // Ensure buffer is correctly sized for the read_exact operation
                        // This is slightly inefficient if packet_len is much smaller than current vec len.
                        // Using VecDeque or a more managed buffer could be better.
                        // For now, simple resize.
                        if packet_buffer.len() < packet_len {
                           packet_buffer.resize(packet_len, 0);
                        }


                        // 2. Read packet data
                        match reader.read_exact(&mut packet_buffer[..packet_len]).await {
                            Ok(_) => {
                                match CustomPacket::from_bytes(&packet_buffer[..packet_len]) {
                                    Ok(packet) => {
                                        // TODO: Process packet (e.g., if it's an EchoRequest, need WriteHalf to reply)
                                        // This loop currently only has ReadHalf. Echo replies would need more complex setup.
                                        // For now, just record metrics.
                                        let rtt_micros = 0; // Server-side receive, RTT measured by client.
                                                          // If this is client receiving echo, then RTT is calculated here.
                                        metrics.lock().unwrap().record_packet_received(packet_len + 4, rtt_micros);
                                    }
                                    Err(e) => {
                                        eprintln!("TCP ReceiveLoop: Failed to parse CustomPacket: {:?}", e);
                                        // Potentially log anomaly
                                    }
                                }
                            }
                            Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => {
                                eprintln!("TCP ReceiveLoop: Connection closed prematurely while reading packet data.");
                                break; // Connection lost
                            }
                            Err(e) => {
                                eprintln!("TCP ReceiveLoop: Error reading packet data: {}", e);
                                return Err(NetworkError::IoError(e)); // Return error
                            }
                        }
                    }
                    Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => {
                        println!("TCP ReceiveLoop: Connection closed by peer (EOF while reading length).");
                        break; // Connection closed
                    }
                    Err(e) => {
                        eprintln!("TCP ReceiveLoop: Error reading packet length: {}", e);
                        return Err(NetworkError::IoError(e)); // Return error
                    }
                }
            }

            _ = bandwidth_sampler.tick() => {
                if let Ok(mut metrics_guard) = metrics.lock() {
                    if let Some(start_time_instant) = metrics_guard.test_start_time {
                        let current_test_time_ms = Instant::now().duration_since(start_time_instant).as_millis();
                        metrics_guard.take_bandwidth_sample(current_test_time_ms);
                    }
                }
            }
        }
    }

    println!("TCP ReceiveLoop: Finished.");
    Ok(())
}
