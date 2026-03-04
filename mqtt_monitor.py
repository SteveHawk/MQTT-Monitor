import base64
from typing import Any

import paho.mqtt.client as mqtt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from loguru import logger
from meshtastic.protobuf import mesh_pb2, mqtt_pb2, portnums_pb2, telemetry_pb2


class MQTTMonitor:
    def __init__(self) -> None:
        self.mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_message = self.on_message

        self.mqttc.connect_async("mqtt.mess.host", 1883, 60)
        self.mqttc.username_pw_set("meshdev", "large4cats")

    def loop_forever(self) -> None:
        # self.mqttc.loop_forever()  # doesn't gracefully handle keyboard interrupt
        with self:
            try:
                self.mqttc._thread.join()  # type: ignore
            except KeyboardInterrupt:
                logger.warning("Keyboard interrupt, exiting...")

    def __enter__(self) -> None:
        self.mqttc.loop_start()

    def __exit__(self, exc_type: Any, exc_valuee: Any, traceback: Any) -> None:
        self.mqttc.loop_stop()
        self.mqttc.disconnect()

    @staticmethod
    def on_connect(
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        """The callback for when the client receives a CONNACK response from the server."""
        if reason_code.is_failure:
            logger.error(f"Connect failed with result code `{reason_code}`")
        else:
            logger.success(f"Connected with result code `{reason_code}`")

        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        # About topic name: https://meshtastic.org/docs/software/integrations/mqtt/
        client.subscribe("msh/CN/2/e/LongFast/#")

    @staticmethod
    def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        """The callback for when a PUBLISH message is received from the server."""
        try:
            service_envelope = mqtt_pb2.ServiceEnvelope()
            service_envelope.ParseFromString(msg.payload)
            packet = service_envelope.packet

            if packet.HasField("encrypted") and not packet.HasField("decoded"):
                MQTTMonitor.decode_encrypted(packet, "1PG7OiApB1nwvP+rz05pAQ==")
            payload = MQTTMonitor.decode_payload(packet)

            logger.info(f"{msg.topic}\n{packet}\npayload:\n{payload}")

        except Exception:
            logger.exception(f"Packet parse error: {msg.payload!r}")

    @staticmethod
    def decode_encrypted(packet: mesh_pb2.MeshPacket, key: str) -> None:
        """Decrypt an encrypted meshtastic message."""
        # Convert key to bytes
        key_bytes = base64.b64decode(key.encode("ascii"))

        nonce_packet_id = getattr(packet, "id").to_bytes(8, "little")
        nonce_from_node = getattr(packet, "from").to_bytes(8, "little")

        # Put both parts into a single byte array.
        nonce = nonce_packet_id + nonce_from_node

        cipher = Cipher(
            algorithms.AES(key_bytes), modes.CTR(nonce), backend=default_backend()
        )
        decryptor = cipher.decryptor()
        decrypted_bytes = (
            decryptor.update(getattr(packet, "encrypted")) + decryptor.finalize()
        )

        data = mesh_pb2.Data()
        data.ParseFromString(decrypted_bytes)
        packet.decoded.CopyFrom(data)

    @staticmethod
    def decode_payload(
        packet: mesh_pb2.MeshPacket,
    ) -> (
        str
        | mesh_pb2.User
        | mesh_pb2.Position
        | mesh_pb2.RouteDiscovery
        | telemetry_pb2.Telemetry
        | None
    ):
        """Decode encoded message payload."""
        payload = packet.decoded.payload
        portnum = packet.decoded.portnum

        if not payload:
            return None

        match portnum:
            case portnums_pb2.TEXT_MESSAGE_APP:
                return payload.decode("utf-8")

            case portnums_pb2.NODEINFO_APP:
                user = mesh_pb2.User()
                user.ParseFromString(payload)
                return user

            case portnums_pb2.POSITION_APP:
                position = mesh_pb2.Position()
                position.ParseFromString(payload)
                return position

            case portnums_pb2.TELEMETRY_APP:
                telemetry = telemetry_pb2.Telemetry()
                telemetry.ParseFromString(payload)
                return telemetry

            case portnums_pb2.TRACEROUTE_APP:
                route_discovery = mesh_pb2.RouteDiscovery()
                route_discovery.ParseFromString(payload)
                return route_discovery

            case _:
                portnum_name = portnums_pb2.PortNum.Name(portnum)
                logger.warning(f"Not implemented PortNum: {portnum_name}, skip.")
                return None


if __name__ == "__main__":
    MQTTMonitor().loop_forever()
