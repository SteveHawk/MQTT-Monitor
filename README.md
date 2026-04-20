# MQTT Monitor for Meshtastic

A MQTT message and packet monitor for Meshtastic. Directly connect to MQTT server, no radio hardware required.

Mostly a simplified version of [pdxlocations/connect](https://github.com/pdxlocations/connect), read-only with a web interface.

| ![screenshot-messages-tab](./assets/screenshot-messages-tab.webp) | ![screenshot-packets-tab](./assets/screenshot-packets-tab.webp) |
| :----------------------------------------------------------: | :----------------------------------------------------------: |

## Usage

Run prebuilt docker image with default settings:

(official MQTT server `mqtt.meshtastic.org`, US default root topic `msh/US`)

```bash
docker run -d --name mqtt-monitor -p 5001:5001 \
           -v ./mqtt-monitor-data/:/app/data/ \
           ghcr.io/stevehawk/mqtt-monitor:latest
```

Or run prebuilt image with CN settings:

(CN MQTT server `mqtt.mess.host`, CN default root topic `msh/CN`)

```bash
docker run -d --name mqtt-monitor -p 5001:5001 \
           -v ./mqtt-monitor-data/:/app/data/ \
           ghcr.io/stevehawk/mqtt-monitor:latest-cn
```

Now you can view the web interface at <localhost:5001>.

## Build locally

With default settings:

```bash
docker build -t mqtt-monitor:default --target default .
```

With CN settings:

```bash
docker build -t mqtt-monitor:cn --target cn .
```

## Available configs via environment variables

| name                           | default value                                                |
| ------------------------------ | ------------------------------------------------------------ |
| PORT                           | 5001                                                         |
| MQTT_MONITOR_ADDRESS           | mqtt.meshtastic.org (default image)<br />mqtt.mess.host (CN image) |
| MQTT_MONITOR_USERNAME          | meshdev                                                      |
| MQTT_MONITOR_PASSWORD          | large4cats                                                   |
| MQTT_MONITOR_ROOT_TOPIC        | msh/US (default image)<br />msh/CN (CN image)                |
| MQTT_MONITOR_CHANNEL           | LongFast                                                     |
| MQTT_MONITOR_KEY               | AQ==                                                         |
| MQTT_MONITOR_DB_PATH           | data/mqtt-monitor.db                                         |
| MQTT_MONITOR_PACKET_KEEP_COUNT | 5000                                                         |
| MQTT_MONITOR_MESSAGE_KEEP_DAYS | 30                                                           |
