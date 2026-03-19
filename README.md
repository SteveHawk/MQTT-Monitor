# Meshtastic MQTT Monitor

A MQTT message monitor for Meshtastic.

Mostly a simplified version of [pdxlocations/connect](https://github.com/pdxlocations/connect), read-only with a web interface.

## Build and run with Docker

With default config (official MQTT server `mqtt.meshtastic.org`, US default root topic `msh/US`):

```bash
docker build -t mqtt-monitor:default --target default .
docker run mqtt-monitor:default
```

With CN config (CN MQTT server `mqtt.mess.host`, CN default root topic `msh/CN`)

```bash
docker build -t mqtt-monitor:cn --target cn .
docker run mqtt-monitor:cn
```

## Available configs via environment variables

| name                           | default value                                                |
| ------------------------------ | ------------------------------------------------------------ |
| MQTT_MONITOR_ADDRESS           | mqtt.meshtastic.org (default image)<br />mqtt.mess.host (CN image) |
| MQTT_MONITOR_USERNAME          | meshdev                                                      |
| MQTT_MONITOR_PASSWORD          | large4cats                                                   |
| MQTT_MONITOR_ROOT_TOPIC        | msh/US (default image)<br />msh/CN (CN image)                |
| MQTT_MONITOR_CHANNEL           | LongFast                                                     |
| MQTT_MONITOR_KEY               | AQ==                                                         |
| MQTT_MONITOR_PACKET_KEEP_COUNT | 5000                                                         |
| MQTT_MONITOR_MESSAGE_KEEP_DAYS | 30                                                           |
