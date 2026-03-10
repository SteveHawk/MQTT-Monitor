import threading
from collections import deque
from datetime import datetime
from typing import Any, Self

import google.protobuf.message
from meshtastic.protobuf import mesh_pb2, telemetry_pb2

type Payload = (
    str
    | mesh_pb2.User
    | mesh_pb2.Position
    | mesh_pb2.RouteDiscovery
    | mesh_pb2.NeighborInfo
    | telemetry_pb2.Telemetry
    | None
)


NodeDB: dict[int, dict[str, str]] = {
    0xFFFFFFFF: {"id": "Broadcast", "long_name": "Broadcast 📢", "short_name": "📢"}
}


def node_num_to_nodedb_entry(node_num: int) -> dict[str, str]:
    """Convert node_num into a NodeDB entry."""
    node_id = f"!{hex(node_num)[2:]}"
    return {
        "id": node_id,
        "long_name": f"Node {node_id}",
        "short_name": node_id[-4:],
    }


class Message:
    def __init__(self, id: int, message: dict[str, Any]) -> None:
        self.id = id
        self.message = message
        self.payload = self.message["decoded"].get("payload")
        self.is_text = self.filter(message["decoded"]["portnum"])
        self.new_day = False

    def __str__(self) -> str:
        return str(self.message)

    @classmethod
    def from_packet(
        cls, id: int, packet: mesh_pb2.MeshPacket, payload: Payload
    ) -> Self:
        message = cls.to_dict(packet, payload)
        return cls(id, message)

    @classmethod
    def to_dict(cls, packet: mesh_pb2.MeshPacket, payload: Payload) -> dict[str, Any]:
        """Convert packet and payload to dictionary."""
        packet_dict = cls._to_dict(packet)
        if payload:
            packet_dict["decoded"]["payload"] = (
                payload if isinstance(payload, str) else cls._to_dict(payload)
            )
        return packet_dict

    @classmethod
    def _to_dict(cls, message: google.protobuf.message.Message) -> dict[str, Any]:
        """Convert google.protobuf.message.Message to dictionary."""
        result = dict[str, Any]()
        for desc, val in message.ListFields():
            if enum_type := desc.enum_type:  # Use enum name instead of value
                val = enum_type.values_by_number[val].name
            result[desc.name] = val
            if isinstance(val, google.protobuf.message.Message):
                result[desc.name] = cls._to_dict(val)
        return result

    def filter(self, portnum: str) -> bool:
        """Filter packets, load NodeDB, determine which packets to display and how to display."""
        if portnum == "NODEINFO_APP":
            NodeDB[self.message["from"]] = {
                "id": self.payload.get("id"),
                "long_name": self.payload.get("long_name"),
                "short_name": self.payload.get("short_name"),
            }
        else:
            if (node_num := self.message["from"]) not in NodeDB:
                NodeDB[node_num] = node_num_to_nodedb_entry(node_num)
            if (node_num := self.message["to"]) not in NodeDB:
                NodeDB[node_num] = node_num_to_nodedb_entry(node_num)
        return portnum == "TEXT_MESSAGE_APP"


class RingBuffer:
    def __init__(self, max_len: int = 128, max_id: int = 0) -> None:
        self.deque = deque[Message](maxlen=max_len)
        self.max_id: int = max_id
        self.condition = threading.Condition()

    def append(self, message: Message) -> None:
        """Append a new messsage."""
        with self.condition:
            if last_msg := self.fetch_latest():
                last_dt = datetime.fromtimestamp(last_msg.message["rx_time"])
                dt = datetime.fromtimestamp(message.message["rx_time"])
                if dt.date() != last_dt.date():
                    message.new_day = True

            self.deque.append(message)
            self.max_id = message.id
            self.condition.notify_all()

    def _new_id(self) -> int:
        """Get a new id for Message."""
        return self.max_id + 1

    def fetch_all(self) -> list[Message]:
        """Fetch all messages in queue."""
        return list(self.deque)

    def fetch_latest(self) -> Message | None:
        """Fetch the latest message."""
        if len(self.deque) == 0:
            return None
        return self.deque[-1]

    def fetch_new(self, current_id: int) -> list[Message]:
        """Fetch missed new messages later than current_id."""
        if current_id >= self.max_id:
            return []
        return list(self.deque)[(current_id - self.max_id) :]

    def wait(self, timeout: int | float | None = None) -> bool:
        """Wait for new message."""
        with self.condition:
            return self.condition.wait(timeout)
