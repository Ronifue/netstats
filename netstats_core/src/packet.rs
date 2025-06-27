// Packet definitions, serialization/deserialization
use serde::{Serialize, Deserialize};
use std::time::{SystemTime, UNIX_EPOCH};

// Using bincode for serialization/deserialization for efficiency.
// If text-based is needed for some reason, could switch to JSON.

/// Represents the different types of packets that can be sent.
/// This helps the receiver understand how to interpret the payload.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq)]
pub enum PacketType {
    Data,         // Standard data packet for bandwidth/latency tests
    Ack,          // Acknowledgement packet
    Control,      // For control messages like test start/stop, parameter negotiation
    EchoRequest,  // For simple RTT echo
    EchoReply,    // Reply to an EchoRequest
}

/// The header part of our custom packet.
/// Contains metadata for sequencing, timing, and type identification.
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct PacketHeader {
    pub sequence_number: u32,
    pub timestamp_ms: u64,    // Sender's timestamp in milliseconds since a common epoch (e.g., test start or Unix epoch)
    pub packet_type: PacketType,
    // pub session_id: u32, // Could be useful for managing multiple concurrent tests or sessions
    // pub integrity_checksum: u32, // Optional: For payload integrity if not relying solely on UDP/TCP checksums
}

impl PacketHeader {
    pub fn new(sequence_number: u32, packet_type: PacketType) -> Self {
        PacketHeader {
            sequence_number,
            timestamp_ms: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("Time went backwards")
                .as_millis() as u64,
            packet_type,
        }
    }
}

/// The full packet structure including header and payload.
/// The payload is generic to allow different types of data.
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct CustomPacket {
    pub header: PacketHeader,
    pub payload: Vec<u8>, // The actual data being sent
}

impl CustomPacket {
    /// Creates a new data packet with the given sequence number and payload.
    pub fn new_data_packet(sequence_number: u32, payload_size_bytes: usize) -> Self {
        CustomPacket {
            header: PacketHeader::new(sequence_number, PacketType::Data),
            payload: vec![0u8; payload_size_bytes], // Dummy payload
        }
    }

    /// Creates a new echo request packet.
    pub fn new_echo_request(sequence_number: u32, payload_size_bytes: usize) -> Self {
        CustomPacket {
            header: PacketHeader::new(sequence_number, PacketType::EchoRequest),
            payload: vec![0u8; payload_size_bytes], // Can include a small payload
        }
    }

    /// Creates an echo reply packet based on an echo request.
    pub fn new_echo_reply(request_packet: &CustomPacket) -> Self {
        CustomPacket {
            header: PacketHeader { // Keep original sequence and timestamp for RTT calculation
                sequence_number: request_packet.header.sequence_number,
                timestamp_ms: request_packet.header.timestamp_ms,
                packet_type: PacketType::EchoReply,
            },
            payload: request_packet.payload.clone(), // Echo the payload
        }
    }

    /// Serializes the packet into a byte vector using bincode.
    pub fn to_bytes(&self) -> Result<Vec<u8>, bincode::Error> {
        bincode::serialize(self)
    }

    /// Deserializes a byte slice into a Packet structure using bincode.
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, bincode::Error> {
        bincode::deserialize(bytes)
    }
}


// Legacy/Simpler packet structure used in initial network.rs stubs
// This can be removed or refactored once CustomPacket is fully integrated.
#[deprecated(note = "Prefer CustomPacket. This will be removed in a future version.")]
#[derive(Debug, Clone)]
pub struct DataPacket {
    pub sequence_number: u32,
    pub timestamp_ms: u64, // Milliseconds, e.g., since test start
    pub payload: Vec<u8>,
}

impl DataPacket {
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(&self.sequence_number.to_be_bytes());
        bytes.extend_from_slice(&self.timestamp_ms.to_be_bytes());
        bytes.extend_from_slice(&self.payload);
        bytes
    }

    pub fn from_bytes(data: &[u8]) -> Result<Self, &'static str> {
        if data.len() < 12 { // 4 for seq, 8 for timestamp
            return Err("Packet too short for header");
        }
        let sequence_number = u32::from_be_bytes(data[0..4].try_into().unwrap());
        let timestamp_ms = u64::from_be_bytes(data[4..12].try_into().unwrap());
        let payload = data[12..].to_vec();
        Ok(DataPacket {
            sequence_number,
            timestamp_ms,
            payload,
        })
    }
}

// This is just a type alias for clarity in network.rs, can be removed
// pub type PacketPayload = Vec<u8>; // Removed as CustomPacket.payload is Vec<u8>


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_data_packet_serialization_deserialization() {
        let packet = DataPacket {
            sequence_number: 123,
            timestamp_ms: 456789,
            payload: vec![1, 2, 3, 4, 5],
        };
        let bytes = packet.to_bytes();
        let deserialized_packet = DataPacket::from_bytes(&bytes).unwrap();

        assert_eq!(packet.sequence_number, deserialized_packet.sequence_number);
        assert_eq!(packet.timestamp_ms, deserialized_packet.timestamp_ms);
        assert_eq!(packet.payload, deserialized_packet.payload);
    }

    #[test]
    fn test_custom_packet_serialization_deserialization_bincode() {
        let packet = CustomPacket::new_data_packet(1001, 64);

        let bytes = packet.to_bytes().expect("Serialization failed");
        let deserialized_packet = CustomPacket::from_bytes(&bytes).expect("Deserialization failed");

        assert_eq!(packet.header.sequence_number, deserialized_packet.header.sequence_number);
        assert_eq!(packet.header.packet_type, deserialized_packet.header.packet_type);
        // Timestamps might differ slightly if created nano/microsecond apart, so check within a tolerance or don't assert equality if not fixed.
        // For this test, PacketHeader::new sets it, so it's fine.
        assert_eq!(packet.header.timestamp_ms, deserialized_packet.header.timestamp_ms);
        assert_eq!(packet.payload.len(), deserialized_packet.payload.len());
        assert_eq!(packet.payload, deserialized_packet.payload);


        let echo_req = CustomPacket::new_echo_request(1002, 32);
        let echo_reply = CustomPacket::new_echo_reply(&echo_req);

        let reply_bytes = echo_reply.to_bytes().unwrap();
        let deserialized_reply = CustomPacket::from_bytes(&reply_bytes).unwrap();

        assert_eq!(echo_reply.header.sequence_number, deserialized_reply.header.sequence_number);
        assert_eq!(echo_reply.header.timestamp_ms, deserialized_reply.header.timestamp_ms); // Important for RTT
        assert_eq!(echo_reply.header.packet_type, PacketType::EchoReply);
        assert_eq!(echo_reply.payload, deserialized_reply.payload);
    }

    #[test]
    fn test_short_packet_from_bytes() {
        let short_data = vec![1,2,3];
        assert!(DataPacket::from_bytes(&short_data).is_err());
    }
}
