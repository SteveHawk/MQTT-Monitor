import json
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Callable, Iterable, Self

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


class Packet:
    def __init__(
        self,
        pkt_id: int,
        msg_id: int,
        packet: dict[str, Any] | str,
        timestamp: int | None = None,
    ) -> None:
        self.packet = packet if isinstance(packet, dict) else json.loads(packet)
        _decoded = self.packet["decoded"]
        self.payload: dict[str, Any] | str | None = _decoded.get("payload")
        self.portnum: str | None = _decoded.get("portnum")
        self.is_text = bool(self.portnum == "TEXT_MESSAGE_APP")

        self.pkt_id = pkt_id
        self.msg_id = msg_id if self.is_text else None

        self.pkt_new_day = False
        self.msg_new_day = False

        self.timestamp = timestamp if timestamp else int(time.time())

    def __str__(self) -> str:
        return str(self.packet)

    def __repr__(self) -> str:
        return str(
            {
                "pkt_id": self.pkt_id,
                "msg_id": self.msg_id,
                "packet": self.packet,
                "timestamp": self.timestamp,
            }
        )

    def set_pkt_new_day(self) -> None:
        self.pkt_new_day = True

    def set_msg_new_day(self) -> None:
        self.msg_new_day = True

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


class RingBuffer:
    def __init__(self, max_len: int = 128, max_id: int = 0) -> None:
        self.deque = deque[Packet](maxlen=max_len)
        self.max_id: int = max_id
        self.condition = threading.Condition()

    def append(
        self, packet: Packet, max_id: int, new_day_setter: Callable[[], None]
    ) -> None:
        """Append a new Packet."""
        if last_msg := self.fetch_latest():
            last_dt = datetime.fromtimestamp(last_msg.timestamp)
            dt = datetime.fromtimestamp(packet.timestamp)
            if dt.date() != last_dt.date():
                new_day_setter()

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
            return []  # TODO: return oob error instead
        return list(self.deque)[(current_id - self.max_id) :]

    def wait(self, timeout: int | float | None = None) -> bool:
        """Wait for new Packet."""
        with self.condition:
            return self.condition.wait(timeout)


class SQLiteStore:
    def __init__(self) -> None:
        self.con = sqlite3.connect("mqtt-monitor.db", autocommit=False)
        self.con.row_factory = sqlite3.Row

        with self.con:
            self.con.execute(
                "CREATE TABLE IF NOT EXISTS packets(pkt_id INTEGER PRIMARY KEY, msg_id UNIQUE, packet, timestamp)"
            )
            self.con.execute(
                "CREATE TABLE IF NOT EXISTS nodedb(node_num INTEGER PRIMARY KEY, id, long_name, short_name)"
            )
            self.con.execute(
                "INSERT INTO nodedb VALUES(0xFFFFFFFF, 'Broadcast', 'Broadcast 📢', '📢')"
            )

    def close(self) -> None:
        self.con.close()

    def insert_nodeinfo(self, node_info: dict[str, str | int]) -> None:
        with self.con:
            self.con.execute(
                "INSERT INTO nodedb VALUES(:node_num, :id, :long_name, :short_name)"
                " ON CONFLICT(node_num) DO UPDATE SET"
                " id=excluded.id, long_name=excluded.long_name, short_name=excluded.short_name",
                node_info,
            )

    def fetch_nodeinfo(self, node_num: int) -> dict[str, str | int]:
        result: sqlite3.Row = self.con.execute(
            "SELECT * FROM nodedb WHERE node_num=?", (node_num,)
        ).fetchone()
        return dict(result)

    def fetch_nodedb(self) -> dict[int, dict[str, str | int]]:
        results: list[sqlite3.Row] = self.con.execute("SELECT * FROM nodedb").fetchall()
        return {r["node_num"]: dict(r) for r in results}

    def insert_packet(self, packet: Packet) -> None:
        with self.con:
            _pkt = json.dumps(packet.packet, separators=(",", ":"))
            _values = (packet.pkt_id, packet.msg_id, _pkt, packet.timestamp)
            self.con.execute("INSERT INTO packets VALUES(?, ?, ?, ?)", _values)

    def fetch_packets(self, pkt_id: int) -> list[Packet]:
        results: list[sqlite3.Row] = self.con.execute(
            "SELECT * FROM packets WHERE pkt_id<? LIMIT 10", (pkt_id,)
        ).fetchall()
        return [Packet(**r) for r in results]

    def fetch_messages(self, msg_id: int) -> list[Packet]:
        results: list[sqlite3.Row] = self.con.execute(
            "SELECT * FROM packets WHERE msg_id<? LIMIT 10", (msg_id,)
        ).fetchall()
        return [Packet(**r) for r in results]


class PacketStore:
    def __init__(self) -> None:
        self.pkt_ring = RingBuffer()
        self.msg_ring = RingBuffer()
        self.sql_store = SQLiteStore()
        self.node_db = self.sql_store.fetch_nodedb()

    def close(self) -> None:
        self.sql_store.close()

    def append(self, packet: Packet) -> None:
        """Append a new Packet."""
        # TODO: insert nodedb here
        self.pkt_ring.append(packet, packet.pkt_id, packet.set_pkt_new_day)
        if packet.is_text:
            assert packet.msg_id is not None
            self.msg_ring.append(packet, packet.msg_id, packet.set_msg_new_day)

    def new_id(self) -> tuple[int, int]:
        """Get a new id for Packet."""
        return self.pkt_ring.new_id(), self.msg_ring.new_id()

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
        # TODO: catch oob error, do db lookup
        if text_only:
            return self.msg_ring.fetch_new(current_id)
        return self.pkt_ring.fetch_new(current_id)

    def wait(self, timeout: int | float | None = None, text_only: bool = False) -> bool:
        """Wait for new Packet."""
        if text_only:
            return self.msg_ring.wait(timeout)
        return self.pkt_ring.wait(timeout)

    def insert_nodeinfo(self, packet: Packet) -> None:
        """Insert nodeinfo into NodeDB."""
        _from = packet.packet["from"]
        if packet.portnum == "NODEINFO_APP":
            assert isinstance((_p := packet.payload), dict)
            self._insert_nodeinfo(_from, (_p["id"], _p["long_name"], _p["short_name"]))
        else:
            self._insert_nodeinfo(_from)
        self._insert_nodeinfo(packet.packet["to"])

    def _insert_nodeinfo(
        self, node_num: int, node_info: tuple[str, str, str] | None = None
    ) -> None:
        """Assemble node info dict and insert into in-memory NodeDB and sql nodedb table."""
        if node_info is None:
            if node_num not in self.node_db:
                self.node_db[node_num] = {
                    "node_num": node_num,
                    "id": (node_id := f"!{hex(node_num)[2:]}"),
                    "long_name": f"Node {node_id}",
                    "short_name": node_id[-4:],
                }
                self.sql_store.insert_nodeinfo(self.node_db[node_num])
        else:
            _node_info: Iterable[tuple[str, str | int]] = zip(
                ("node_num", "id", "long_name", "short_name"),
                (node_num, *node_info),
            )
            self.node_db[node_num] = dict(_node_info)
            self.sql_store.insert_nodeinfo(self.node_db[node_num])

    def fetch_nodeinfo(self, node_num: int) -> dict[str, str | int]:
        return self.node_db[node_num]
