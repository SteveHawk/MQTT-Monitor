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


class Packet:
    def __init__(self, pkt_id: int, msg_id: int, packet: dict[str, Any]) -> None:
        self.pkt_id = pkt_id
        self.packet = packet
        self.payload = self.packet["decoded"].get("payload")
        self.is_text = self.filter(packet["decoded"]["portnum"])
        self.msg_id = msg_id if self.is_text else None
        self.new_day = False

    def __str__(self) -> str:
        return str(self.packet)

    @classmethod
    def from_mesh_packet(
        cls, ids: tuple[int, int], packet: mesh_pb2.MeshPacket, payload: Payload
    ) -> Self:
        """Create a new Packet instance from mesh_pb2.MeshPacket and Payload."""
        packet_dict = cls.to_dict(packet, payload)
        return cls(*ids, packet_dict)

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
    def _to_dict(cls, packet: google.protobuf.message.Message) -> dict[str, Any]:
        """Convert google.protobuf.message.Message to dictionary."""
        result = dict[str, Any]()
        for desc, val in packet.ListFields():
            if enum_type := desc.enum_type:  # Use enum name instead of value
                val = enum_type.values_by_number[val].name
            result[desc.name] = val
            if isinstance(val, google.protobuf.message.Message):
                result[desc.name] = cls._to_dict(val)
        return result

    def filter(self, portnum: str) -> bool:
        """Filter packets, load NodeDB, determine which packets to display and how to display."""
        if portnum == "NODEINFO_APP":
            NodeDB[self.packet["from"]] = {
                "id": self.payload.get("id"),
                "long_name": self.payload.get("long_name"),
                "short_name": self.payload.get("short_name"),
            }
        else:
            if (node_num := self.packet["from"]) not in NodeDB:
                NodeDB[node_num] = node_num_to_nodedb_entry(node_num)
            if (node_num := self.packet["to"]) not in NodeDB:
                NodeDB[node_num] = node_num_to_nodedb_entry(node_num)
        return portnum == "TEXT_MESSAGE_APP"


class RingBuffer:
    def __init__(self, max_len: int = 128, max_id: int = 0) -> None:
        self.deque = deque[Packet](maxlen=max_len)
        self.max_id: int = max_id
        self.condition = threading.Condition()

    def append(self, packet: Packet, max_id: int) -> None:
        """Append a new Packet."""
        with self.condition:
            self.deque.append(packet)
            self.max_id = max_id
            self.condition.notify_all()

    def new_id(self) -> int:
        """Get a new id for Packet."""
        return self.max_id + 1

    def fetch_all(self) -> list[Packet]:
        """Fetch all Packets in queue."""
        return list(self.deque)

    def fetch_latest(self) -> Packet | None:
        """Fetch the latest Packet."""
        if len(self.deque) == 0:
            return None
        return self.deque[-1]

    def fetch_new(self, current_id: int) -> list[Packet]:
        """Fetch missed new Packets later than current_id."""
        if current_id >= self.max_id:
            return []
        return list(self.deque)[(current_id - self.max_id) :]

    def wait(self, timeout: int | float | None = None) -> bool:
        """Wait for new Packet."""
        with self.condition:
            return self.condition.wait(timeout)


class PacketStore:
    def __init__(self) -> None:
        self.pkt_ring = RingBuffer()
        self.msg_ring = RingBuffer()

    def append(self, packet: Packet) -> None:
        """Append a new Packet."""
        if last_msg := self.fetch_latest(text_only=False):
            last_dt = datetime.fromtimestamp(last_msg.packet["rx_time"])
            dt = datetime.fromtimestamp(packet.packet["rx_time"])
            if dt.date() != last_dt.date():
                packet.new_day = True

        self.pkt_ring.append(packet, packet.pkt_id)
        if packet.is_text:
            assert packet.msg_id is not None
            self.msg_ring.append(packet, packet.msg_id)

    def new_id(self) -> tuple[int, int]:
        """Get a new id for Packet."""
        return self.pkt_ring.max_id, self.msg_ring.max_id

    def fetch_all(self, text_only: bool) -> list[Packet]:
        """Fetch all Packets in queue."""
        if text_only:
            return self.msg_ring.fetch_all()
        return self.pkt_ring.fetch_all()

    def fetch_latest(self, text_only: bool) -> Packet | None:
        """Fetch the latest Packet."""
        if text_only:
            return self.msg_ring.fetch_latest()
        return self.pkt_ring.fetch_latest()

    def fetch_new(self, current_id: int, text_only: bool) -> list[Packet]:
        """Fetch missed new Packets later than current_id."""
        if text_only:
            return self.msg_ring.fetch_new(current_id)
        return self.pkt_ring.fetch_new(current_id)

    def wait(self, timeout: int | float | None = None, text_only: bool = False) -> bool:
        """Wait for new Packet."""
        if text_only:
            return self.msg_ring.wait(timeout)
        return self.pkt_ring.wait(timeout)
