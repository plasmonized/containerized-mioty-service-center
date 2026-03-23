---
outline: [2, 3]
---

# Advanced Features

## Message Deduplication

The system implements sophisticated message deduplication for multi-base station deployments:

```mermaid
sequenceDiagram
    participant S as Sensor
    participant BS1 as Base Station 1
    participant BS2 as Base Station 2
    participant SC as Service Center
    participant MQTT as MQTT Broker
    
    S->>BS1: Sensor Data
    S->>BS2: Sensor Data
    BS1->>SC: Message (SNR: 5.2 dB)
    BS2->>SC: Message (SNR: 8.1 dB)
    
    SC->>SC: Compare SNR values
    SC->>SC: Select best path (BS2)
    SC->>MQTT: Publish message from BS2
    SC->>SC: Discard duplicate from BS1
    
    Note over SC: Deduplication window: 2.0s
```

### Configuration

- **Deduplication Delay**: `DEDUPLICATION_DELAY = 2.0` seconds
- **Buffer Management**: Automatic cleanup of processed messages
- **Statistics Tracking**: Real-time duplicate rate monitoring

## Preferred Downlink Path Management

```mermaid
flowchart LR
    subgraph Selection["Path Selection Algorithm"]
        Receive[Message received<br/>with SNR] --> Compare{Compare<br/>SNR values}
        Compare -->|New SNR > Current| Update[Update preferred path]
        Compare -->|New SNR < Current| Keep[Keep current path]
        Update --> Save[Save to config]
        Keep --> Save
        Save --> Use[Use for future<br/>downlink messages]
    end
    
    subgraph Paths["Multi-Base Station Support"]
        BS1[("Base Station 1<br/>SNR: 5.2 dB")]
        BS2[("Base Station 2<br/>SNR: 8.1 dB")]
        BS3[("Base Station 3<br/>SNR: 6.8 dB")]
        
        BS1 & BS2 & BS3 --> Selection
    end
    
    style Selection fill:#ff9
    style Paths fill:#9ff
```

### Signal Quality Tracking

- **SNR Monitoring**: Tracks Signal-to-Noise Ratio for each sensor-base station pair
- **Dynamic Updates**: Continuously updates preferred path based on signal quality
- **Path Persistence**: Stores preferred paths in sensor configuration
- **Multi-Base Station Support**: Handles sensors communicating through multiple base stations

## Queue Management System

### Asynchronous Queue Architecture

- **MQTT Output Queue**: Messages to be published to MQTT broker
- **MQTT Input Queue**: Configuration and command messages from MQTT
- **Queue Monitoring**: Real-time queue size monitoring and statistics
- **Health Checking**: Automatic detection and recovery from queue issues

### Queue Statistics

- Queue sizes and utilization
- Message processing rates
- Error rates and recovery statistics
- Performance metrics and bottleneck detection

## Security Features

### SSL/TLS Security

- **Mutual Authentication**: Base stations must present valid certificates
- **Certificate Validation**: Full chain validation with CA verification
- **Secure Channels**: All communication encrypted with TLS 1.2+
- **Certificate Management**: Web-based certificate upload, generation, and backup

### Access Control

- **Web Interface Security**: Session-based access control with role-based permissions
- **API Protection**: Request validation, sanitization, and role-based permission decorators
- **Certificate-Based Auth**: Base station authentication via client certificates
- **MQTT Security**: Username/password authentication for MQTT broker
