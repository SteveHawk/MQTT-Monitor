import base64
import contextlib
import threading
from typing import Annotated, Any, Generator, Sequence

import google.protobuf.message
import paho.mqtt.client as mqtt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from loguru import logger
from meshtastic.protobuf import mesh_pb2, mqtt_pb2, portnums_pb2, telemetry_pb2
from pydantic import AfterValidator, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .packet_store import Packet, PacketStore


class Settings(BaseSettings):
    address: str = "mqtt.meshtastic.org"
    username: str = "meshdev"
    password: str = "large4cats"
    root_topic: str = "msh/US"
    channel: str = "LongFast"
    key: Annotated[
        str, AfterValidator(lambda k: "1PG7OiApB1nwvP+rz05pAQ==" if k == "AQ==" else k)
    ] = "AQ=="

    packet_keep_count: int = 5000
    message_keep_days: int = 30

    @computed_field
    @property
    def topic(self) -> str:
        return f"{self.root_topic}/2/e/{self.channel}/#"

    model_config = SettingsConfigDict(env_prefix="mqtt_monitor_")


type Payload = (
    str
    | mesh_pb2.User
    | mesh_pb2.Position
    | mesh_pb2.RouteDiscovery
    | mesh_pb2.NeighborInfo
    | mesh_pb2.Routing
    | telemetry_pb2.Telemetry
    | None
)


class MQTTMonitor:
    def __init__(self) -> None:
        settings = self.settings = Settings()

        self.mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata=settings)
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_message = self.on_message
        self.mqttc.on_disconnect = self.on_disconnect

        self.mqttc.connect_async(settings.address, 1883, 60)
        self.mqttc.username_pw_set(settings.username, settings.password)

        self.packet_store: PacketStore
        self.shutdown_event = threading.Event()

    def loop_forever(self) -> None:
        """Start MQTT server, blocking."""
        # self.mqttc.loop_forever()  # doesn't gracefully handle keyboard interrupt
        with self.start():
            try:
                self.mqttc._thread.join()  # type: ignore
            except KeyboardInterrupt:
                logger.warning("Keyboard interrupt, exiting...")

    @contextlib.contextmanager
    def start(self) -> Generator[None]:
        """Context manager for starting and stopping the service."""
        logger.info(
            "Starting MQTT monitor,"
            f" address={self.settings.address}, topic={self.settings.topic}"
        )
        self.mqttc.loop_start()

        self.packet_store = PacketStore()
        with contextlib.closing(self.packet_store):
            cleanup_thread = threading.Thread(target=self.packets_cleanup_service)
            cleanup_thread.start()

            yield

            self.shutdown_event.set()
            cleanup_thread.join()

        self.mqttc.disconnect()
        self.mqttc.loop_stop()
        logger.info("MQTT monitor stopped.")

    def packets_cleanup_service(self) -> None:
        """Auto run packets table cleanup job."""
        self.packet_store.thread_init()
        _s = self.settings
        while not self.shutdown_event.wait(3600):
            with self.packet_store.thread_sql_store():
                logger.info("Running packets cleanup.")
                self.packet_store.cleanup(_s.packet_keep_count, _s.message_keep_days)

    def on_connect(
        self,
        client: mqtt.Client,
        userdata: Settings,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        """The callback for when the client receives a CONNACK response from the server."""
        if reason_code.is_failure:
            logger.error(f"MQTT connect failed with reason code `{reason_code}`")
        else:
            logger.success(f"MQTT connected with reason code `{reason_code}`")

        # Init SQLite connection for this thread
        self.packet_store.thread_init()

        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        # About topic name: https://meshtastic.org/docs/software/integrations/mqtt/
        client.subscribe(userdata.topic)

    def on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Settings,
        flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        """The callback called when the client disconnects from the broker."""
        if reason_code.is_failure:
            logger.error(f"MQTT disconnected with reason code `{reason_code}`")
        else:
            logger.success(f"MQTT disconnected with reason code `{reason_code}`")

        # Close SQLite connection for this thread
        self.packet_store.thread_close()

    def on_message(
        self, client: mqtt.Client, userdata: Settings, msg: mqtt.MQTTMessage
    ) -> None:
        """The callback for when a PUBLISH message is received from the server."""
        try:
            # Parse message
            packet_dict = self.process_message(msg.payload, userdata.key)
            packet = Packet(*self.packet_store.new_id(), packet_dict)
            logger.info(f"{msg.topic}: [{packet.pkt_id}][{packet.msg_id}] {packet}")

            # Insert into ring buffer
            with self.packet_store.thread_sql_store():
                self.packet_store.append(packet)

        except Exception:
            logger.exception(f"Packet parse error: {msg.payload!r}")

    @classmethod
    def process_message(cls, msg: bytes, key: str) -> dict[str, Any]:
        # Get message
        service_envelope = mqtt_pb2.ServiceEnvelope()
        service_envelope.ParseFromString(msg)
        packet = service_envelope.packet

        # Decrypt and decode
        if packet.HasField("encrypted") and not packet.HasField("decoded"):
            cls.decode_encrypted(packet, key)
        payload = cls.decode_payload(packet)

        # Parse into dict
        return cls.to_dict(packet, payload)

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
    def decode_payload(packet: mesh_pb2.MeshPacket) -> Payload:
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

            case portnums_pb2.NEIGHBORINFO_APP:
                neighbor_info = mesh_pb2.NeighborInfo()
                neighbor_info.ParseFromString(payload)
                return neighbor_info

            case portnums_pb2.ROUTING_APP:
                routing = mesh_pb2.Routing()
                routing.ParseFromString(payload)
                return routing

            case _:
                portnum_name = portnums_pb2.PortNum.Name(portnum)
                logger.warning(f"Not implemented PortNum: {portnum_name}, skip.")
                return None

    @classmethod
    def to_dict(cls, packet: mesh_pb2.MeshPacket, payload: Payload) -> dict[str, Any]:
        """Convert packet and payload to dictionary."""
        packet_dict = cls._pb_to_dict(packet)
        if payload:
            packet_dict["decoded"]["payload"] = (
                payload if isinstance(payload, str) else cls._pb_to_dict(payload)
            )
        return packet_dict

    @classmethod
    def _pb_to_dict(cls, packet: google.protobuf.message.Message) -> dict[str, Any]:
        """Convert google.protobuf.message.Message to dictionary."""

        def type_handle(val: Any) -> Any:
            if isinstance(val, (str, int, float)):
                return val
            elif isinstance(val, google.protobuf.message.Message):
                return cls._pb_to_dict(val)
            elif isinstance(val, bytes):
                if desc.name == "macaddr":
                    _mac = val.hex()
                    return ":".join([_mac[i : i + 2] for i in range(0, len(_mac), 2)])
                elif desc.name == "public_key":
                    return base64.b64encode(val).decode()
                else:
                    if desc.name != "payload":
                        logger.warning(f"New bytes type: {desc.name=} {val=}")
                    return str(val)
            elif isinstance(val, Sequence):  # RepeatedScalarContainer, etc
                return [type_handle(v) for v in list(val)]
            else:
                logger.warning(f"New data type: {desc.name=} {type(val)=} {val=}")
                return str(val)

        result = dict[str, Any]()
        for desc, val in packet.ListFields():
            if enum_type := desc.enum_type:  # Use enum name instead of value
                val = enum_type.values_by_number[val].name
            result[desc.name] = type_handle(val)
        return result


if __name__ == "__main__":
    MQTTMonitor().loop_forever()
