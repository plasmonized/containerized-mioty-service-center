---
outline: [2, 3]
---

# Introduction

The **BSSCI Service Center** is a comprehensive IoT device management system that provides secure communication between mioty sensors, base stations, and MQTT brokers. It implements the BSSCI (Base Station Service Center Interface) protocol with advanced features for sensor lifecycle management, automatic detachment, and real-time monitoring.

## System Architecture

```mermaid
graph LR
    subgraph BaseStation["Base Station"]
        BS_SensorMgmt["Sensor Management"]
        BS_DataCollect["Data Collection"]
        BS_StatusRep["Status Reporting"]
    end

    subgraph ServiceCenter["Service Center"]
        SC_TLS["TLS Server"]
        SC_MQTT["MQTT Client"]
        SC_Web["Web Interface"]
        SC_AutoDetach["Auto-Detach"]
    end

    subgraph MQTTBroker["MQTT Broker"]
        MB_Data["Data Topics"]
        MB_Config["Config Topics"]
        MB_Status["Status Topics"]
        MB_Commands["Commands"]
    end

    subgraph WebBrowser["Web Browser"]
        WB_Manage["Management UI"]
    end

    BS_SensorMgmt & BS_DataCollect & BS_StatusRep <-->|"TLS"| SC_TLS
    SC_MQTT <--> MB_Data & MB_Config & MB_Status & MB_Commands
    SC_Web --> WB_Manage
    SC_TLS --> SC_MQTT
    SC_TLS --> SC_AutoDetach

    style BaseStation fill:#f9f,stroke:#333,stroke-width:2px
    style ServiceCenter fill:#ff9,stroke:#333,stroke-width:2px
    style MQTTBroker fill:#9f9,stroke:#333,stroke-width:2px
    style WebBrowser fill:#9ff,stroke:#333,stroke-width:2px
```

## Key Components

- **TLS Server**: Secure communication with base stations using BSSCI protocol
- **MQTT Interface**: Bidirectional communication with external systems
- **Web UI**: Real-time management and monitoring dashboard
- **Auto-Detach System**: Automated sensor lifecycle management
- **Certificate Management**: SSL/TLS security infrastructure

## Tested Base Stations

| Manufacturer | Device |
|---|---|
| Diehl Metering | Premium Gateway |
| Weptech | AVA1 |
| Miromico | Edge |
| Diehl Metering | Compact Gateway |
| RAK | WisGate Connect for mioty |

## Next Steps

- [Installation & Setup](./installation.md) - Get started with installation
- [Configuration](./configuration.md) - Configure the service center
- [Docker Deployment](../deployment/docker.md) - Deploy using Docker
