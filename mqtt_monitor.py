import base64
from collections import deque
from typing import Any

import paho.mqtt.client as mqtt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from loguru import logger
from meshtastic.protobuf import mesh_pb2, mqtt_pb2, portnums_pb2, telemetry_pb2

type Payload = (
    str
    | mesh_pb2.User
    | mesh_pb2.Position
    | mesh_pb2.RouteDiscovery
    | telemetry_pb2.Telemetry
)


class Message:
    def __init__(self, id: int, packet: mesh_pb2.MeshPacket, payload: Payload) -> None:
        self.id = id
        self.packet = packet
        self.payload = payload


class RingBuffer:
    def __init__(self, max_len: int = 128, max_id: int = 0) -> None:
        self.deque = deque[Message](maxlen=max_len)
        self.max_id: int = max_id

    def append(self, message: Message) -> None:
        self.deque.append(message)
        self.max_id += 1

    def new_id(self) -> int:
        return self.max_id + 1

    def fetch_all(self) -> list[Message]:
        return list(self.deque)

    def fetch_new(self, current_id: int) -> list[Message]:
        return list(self.deque)[max(0, current_id - self.max_id) :]


class MQTTMonitor:
    def __init__(self) -> None:
        self.mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_message = self.on_message

        self.mqttc.connect_async("mqtt.mess.host", 1883, 60)
        self.mqttc.username_pw_set("meshdev", "large4cats")

        self.ring_buffer = RingBuffer()

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

    def on_message(
        self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage
    ) -> None:
        """The callback for when a PUBLISH message is received from the server."""
        try:
            service_envelope = mqtt_pb2.ServiceEnvelope()
            service_envelope.ParseFromString(msg.payload)
            packet = service_envelope.packet

            if packet.HasField("encrypted") and not packet.HasField("decoded"):
                self.decode_encrypted(packet, "1PG7OiApB1nwvP+rz05pAQ==")
            payload = self.decode_payload(packet)

            logger.info(f"{msg.topic}\n{packet}\npayload:\n{payload}")

        except Exception:
            logger.exception(f"Packet parse error: {msg.payload!r}")

    def decode_encrypted(self, packet: mesh_pb2.MeshPacket, key: str) -> None:
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

    def decode_payload(self, packet: mesh_pb2.MeshPacket) -> Payload | None:
        """Decode encoded message payload."""
        payload = packet.decoded.payload
        portnum = packet.decoded.portnum

        if not payload:
            return None

        match portnum:
            case portnums_pb2.TEXT_MESSAGE_APP:
                _payload = payload.decode("utf-8")
                _message = Message(self.ring_buffer.new_id(), packet, _payload)
                self.ring_buffer.append(_message)
                return _payload

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
