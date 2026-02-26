from typing import Any

import paho.mqtt.client as mqtt


class MQTTMonitor:
    def __init__(self) -> None:
        self.mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_message = self.on_message

        self.mqttc.connect_async("mqtt.eclipseprojects.io", 1883, 60)

    def loop_forever(self) -> None:
        # Blocking call that processes network traffic, dispatches callbacks and handles reconnecting.
        # Other loop*() functions are available that give a threaded interface and a manual interface.
        self.mqttc.loop_forever()

    def __enter__(self) -> None:
        self.mqttc.loop_start()

    def __exit__(self, exc_type: Any, exc_valuee: Any, traceback: Any) -> None:
        self.mqttc.loop_stop()

    # The callback for when the client receives a CONNACK response from the server.
    @staticmethod
    def on_connect(
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        print(f"Connected with result code {reason_code}")
        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        client.subscribe("$SYS/#")

    # The callback for when a PUBLISH message is received from the server.
    @staticmethod
    def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        print(msg.topic + " " + str(msg.payload))


if __name__ == "__main__":
    MQTTMonitor().loop_forever()
