---
outline: [2, 3]
---

# Troubleshooting

## Common Issues

### Base Station Connection Issues

**Problem**: Base stations cannot connect to TLS server

**Solutions**:

1. **Certificate Issues**:

   ```bash
   # Check certificate validity
   openssl x509 -in certs/service_center_cert.pem -text -noout
   
   # Verify CA certificate
   openssl verify -CAfile certs/ca_cert.pem certs/service_center_cert.pem
   ```

2. **Network Connectivity**:

   ```bash
   # Check if port is accessible
   telnet <service-center-ip> 16018
   
   # Verify firewall settings
   netstat -tlnp | grep 16018
   ```

3. **SSL Configuration**:
   - Ensure base station has correct CA certificate
   - Verify base station client certificate is signed by same CA
   - Check certificate expiration dates

### MQTT Connectivity Issues

**Problem**: MQTT broker connection failures

**Solutions**:

1. **Authentication Issues**:
   - Verify MQTT_USERNAME and MQTT_PASSWORD in configuration
   - Check broker access control lists (ACLs)
   - Test credentials with mosquitto_pub/sub

2. **Network Issues**:

   ```bash
   # Test MQTT connectivity
   mosquitto_pub -h <broker-host> -p <port> -u <username> -P <password> -t "test" -m "hello"
   ```

3. **Topic Permissions**:
   - Ensure user has publish/subscribe permissions for all required topics
   - Check broker topic filter configurations

### Sensor Registration Problems

**Problem**: Sensors not registering properly

**Solutions**:

1. **Configuration Validation**:
   - Verify EUI format (16 hex characters)
   - Check network key format (32 hex characters)  
   - Validate short address (4 hex characters)
   - Ensure sensor configuration is saved in endpoints.json

2. **Base Station Issues**:
   - Verify base station is connected to service center
   - Check base station sensor capacity
   - Review base station logs for errors

### Auto-Detach Issues

**Problem**: Sensors being detached unexpectedly

**Solutions**:

1. **Timeout Configuration**:
   - Review AUTO_DETACH_TIMEOUT setting (default 72 hours)
   - Check AUTO_DETACH_WARNING_TIMEOUT (default 36 hours)
   - Verify sensor communication frequency

2. **Activity Tracking**:
   - Monitor sensor last-seen timestamps in web interface
   - Check for network issues preventing sensor communication
   - Verify sensor transmission schedules

3. **Disable Auto-Detach**:

   ```python
   # In bssci_config.py or via web interface
   AUTO_DETACH_ENABLED = False
   ```

## Debugging Tools

### Log Analysis

```bash
# View real-time logs
tail -f logs/bssci_service.log

# Filter by log level
grep "ERROR" logs/bssci_service.log

# Search for specific sensor
grep "FCA84A0300001234" logs/bssci_service.log

# Monitor auto-detach activity
grep "AUTO-DETACH" logs/bssci_service.log
```

### MQTT Debugging

```bash
# Monitor all MQTT traffic
mosquitto_sub -h <broker> -u <user> -P <pass> -t "#" -v

# Test sensor commands
mosquitto_pub -h <broker> -u <user> -P <pass> -t "EP/FCA84A0300001234/cmd/" -m "status"

# Monitor specific sensor
mosquitto_sub -h <broker> -u <user> -P <pass> -t "mioty/ep/FCA84A0300001234/#" -v
```
