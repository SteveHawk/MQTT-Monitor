import contextlib
import json
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Generator, Iterable


class Packet:
    def __init__(
        self,
        pkt_id: int,
        msg_id: int,
        packet: dict[str, Any] | str,
        pkt_new_day: bool = False,
        msg_new_day: bool = False,
        timestamp: int | None = None,
    ) -> None:
        self.packet = packet if isinstance(packet, dict) else json.loads(packet)
        _decoded = self.packet["decoded"]
        self.payload: dict[str, Any] | str | None = _decoded.get("payload")
        self.portnum: str | None = _decoded.get("portnum")
        self.is_text = bool(self.portnum == "TEXT_MESSAGE_APP")

        self.pkt_id = pkt_id
        self.msg_id = msg_id if self.is_text else -1

        self.pkt_new_day = pkt_new_day
        self.msg_new_day = msg_new_day

        self.timestamp = timestamp if timestamp else int(time.time())

    def __str__(self) -> str:
        return str(self.packet)

    def to_dict(self, json_packet: bool = False) -> dict[str, Any]:
        _pkt = self.packet
        if json_packet:
            _pkt = json.dumps(self.packet, separators=(",", ":"))
        return {
            "pkt_id": self.pkt_id,
            "msg_id": self.msg_id if self.msg_id > 0 else None,
            "packet": _pkt,
            "pkt_new_day": self.pkt_new_day,
            "msg_new_day": self.msg_new_day,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        return str(self.to_dict())

    def set_new_day(self, last_packet: Packet | None, is_text: bool) -> None:
        if last_packet is None:  # no previous packet, set as new day
            return self._set_new_day(is_text)

        last_dt = datetime.fromtimestamp(last_packet.timestamp)
        dt = datetime.fromtimestamp(self.timestamp)
        if dt.date() != last_dt.date():
            self._set_new_day(is_text)

    def _set_new_day(self, is_text: bool) -> None:
        if is_text:
            self.msg_new_day = True
        else:
            self.pkt_new_day = True


class RingBuffer:
    def __init__(
        self, packets: list[Packet] = [], max_len: int = 128, max_id: int = 0
    ) -> None:
        self.deque = deque[Packet](packets, maxlen=max_len)
        self.max_id = max_id
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

    @property
    def min_id(self) -> int:
        """Minimum id of this ring."""
        return self.max_id - len(self.deque) + 1

    def fetch_all(self) -> list[Packet]:
        """Fetch all Packets in queue."""
        return list(self.deque)

    def fetch_last(self) -> Packet | None:
        """Fetch the last Packet."""
        if len(self.deque) == 0:
            return None
        return self.deque[-1]

    def fetch_latest(self, count: int) -> list[Packet]:
        """Fetch the lastest Packets."""
        return list(self.deque)[-count:]

    def fetch_new(self, current_id: int) -> list[Packet]:
        """Fetch missed new Packets later than current_id."""
        if current_id >= self.max_id:  # already latest
            return []
        if current_id + 1 < self.min_id:  # not enough cache
            raise IndexError
        return list(self.deque)[(current_id - self.max_id) :]

    def fetch_old(self, current_id: int, count: int) -> list[Packet]:
        """Fetch old Packets earlier than current_id."""
        if current_id - count < self.min_id:  # not enough cache
            raise IndexError
        if current_id > self.max_id:
            raise RuntimeError(f"{current_id=} > {self.max_id=}")
        return list(self.deque)[
            (current_id - count - self.max_id - 1) : (current_id - self.max_id - 1)
        ]

    def wait(self, timeout: int | float | None = None) -> bool:
        """Wait for new Packet."""
        with self.condition:
            return self.condition.wait(timeout)


class SQLiteStore:
    def __init__(self) -> None:
        self.con = sqlite3.connect("mqtt-monitor.db", autocommit=False)
        self.con.row_factory = sqlite3.Row

    def close(self) -> None:
        self.con.close()

    def init_tables(self) -> None:
        with self.con:
            self.con.execute(
                "CREATE TABLE IF NOT EXISTS packets(pkt_id INTEGER PRIMARY KEY,"
                " msg_id UNIQUE, packet, pkt_new_day, msg_new_day, timestamp)"
            )
            self.con.execute(
                "CREATE TABLE IF NOT EXISTS"
                " nodedb(node_num INTEGER PRIMARY KEY, id, long_name, short_name)"
            )
            self.con.execute(
                "INSERT INTO nodedb VALUES(0xFFFFFFFF, 'Broadcast', 'Broadcast 📢', '📢')"
                " ON CONFLICT(node_num) DO NOTHING"
            )

    def insert_nodeinfo(self, node_info: dict[str, str | int]) -> None:
        with self.con:
            self.con.execute(
                "INSERT INTO nodedb VALUES(:node_num, :id, :long_name, :short_name)"
                " ON CONFLICT(node_num) DO UPDATE SET id=excluded.id,"
                " long_name=excluded.long_name, short_name=excluded.short_name",
                node_info,
            )

    def fetch_nodeinfo(self, node_num: int) -> dict[str, str | int]:
        with self.con:
            result: sqlite3.Row = self.con.execute(
                "SELECT * FROM nodedb WHERE node_num=?", (node_num,)
            ).fetchone()
        return dict(result)

    def fetch_nodedb(self) -> dict[int, dict[str, str | int]]:
        with self.con:
            results: list[sqlite3.Row] = self.con.execute(
                "SELECT * FROM nodedb"
            ).fetchall()
        return {r["node_num"]: dict(r) for r in results}

    def insert_packet(self, packet: Packet) -> None:
        with self.con:
            self.con.execute(
                "INSERT INTO packets VALUES"
                "(:pkt_id, :msg_id, :packet, :pkt_new_day, :msg_new_day, :timestamp)",
                packet.to_dict(True),
            )

    def fetch_new_packets(self, pkt_id: int) -> list[Packet]:
        with self.con:
            results: list[sqlite3.Row] = self.con.execute(
                "SELECT * FROM packets WHERE pkt_id>?", (pkt_id,)
            ).fetchall()
        return [Packet(**r) for r in results]

    def fetch_old_packets(self, pkt_id: int, count: int) -> list[Packet]:
        with self.con:
            results: list[sqlite3.Row] = self.con.execute(
                "SELECT * FROM packets WHERE pkt_id<? LIMIT ?", (pkt_id, count)
            ).fetchall()
        return [Packet(**r) for r in results]

    def fetch_latest_packets(self, count: int) -> list[Packet]:
        with self.con:
            results: list[sqlite3.Row] = self.con.execute(
                "SELECT * FROM packets ORDER BY pkt_id DESC LIMIT ?", (count,)
            ).fetchall()
        return [Packet(**r) for r in results][::-1]

    def fetch_new_messages(self, msg_id: int) -> list[Packet]:
        with self.con:
            results: list[sqlite3.Row] = self.con.execute(
                "SELECT * FROM packets WHERE msg_id>?", (msg_id,)
            ).fetchall()
        return [Packet(**r) for r in results]

    def fetch_old_messages(self, msg_id: int, count: int) -> list[Packet]:
        with self.con:
            results: list[sqlite3.Row] = self.con.execute(
                "SELECT * FROM packets WHERE msg_id<? LIMIT ?", (msg_id, count)
            ).fetchall()
        return [Packet(**r) for r in results]

    def fetch_latest_messages(self, count: int) -> list[Packet]:
        with self.con:
            results: list[sqlite3.Row] = self.con.execute(
                "SELECT * FROM packets WHERE msg_id IS NOT NULL"
                " ORDER BY msg_id DESC LIMIT ?",
                (count,),
            ).fetchall()
        return [Packet(**r) for r in results][::-1]


class PacketStore:
    def __init__(self) -> None:
        self.sql_store = SQLiteStore()  # SQLite connection for the main thread
        self.sql_store.init_tables()  # Only run init in main thread
        self.sql_store_t = dict[int, SQLiteStore]()  # SQLite conn for different threads

        # Prefill rings
        self.pkt_ring = RingBuffer(
            (_pkts := self.sql_store.fetch_latest_packets(30)),
            max_id=_pkts[-1].pkt_id if _pkts else 0,
        )
        self.msg_ring = RingBuffer(
            (_pkts := self.sql_store.fetch_latest_messages(30)),
            max_id=_pkts[-1].msg_id if _pkts else 0,
        )

        # Sync nodedb
        self.node_db = self.sql_store.fetch_nodedb()

    def close(self) -> None:
        """Close the main SQLite connection."""
        self.sql_store.close()

    def thread_init(self) -> None:
        """Initialize a new SQLite connection for current thread."""
        if (ident := threading.get_ident()) in self.sql_store_t:
            return
        self.sql_store_t[ident] = SQLiteStore()

    def thread_close(self) -> None:
        """Close the SQLite connection for current thread."""
        if (ident := threading.get_ident()) not in self.sql_store_t:
            return
        self.sql_store_t.pop(ident).close()

    @contextlib.contextmanager
    def thread_sql_store(self) -> Generator[None]:
        """Switch to the SQLite connection for this thread."""
        try:
            _ori = self.sql_store
            self.sql_store = self.sql_store_t[threading.get_ident()]
            yield
        finally:
            self.sql_store = _ori

    def append(self, packet: Packet) -> None:
        """Append a new Packet."""
        # Insert nodeinfo
        self.insert_nodeinfo(packet)

        # Check if new day
        packet.set_new_day(self.pkt_ring.fetch_last(), False)
        if packet.is_text:
            packet.set_new_day(self.msg_ring.fetch_last(), True)

        # Insert into sql and rings
        self.sql_store.insert_packet(packet)
        self.pkt_ring.append(packet, packet.pkt_id)
        if packet.is_text:
            self.msg_ring.append(packet, packet.msg_id)

    def new_id(self) -> tuple[int, int]:
        """Get a new id for Packet."""
        return self.pkt_ring.new_id(), self.msg_ring.new_id()

    def fetch_all(self, text_only: bool) -> list[Packet]:
        """Fetch all Packets in queue."""
        if text_only:
            return self.msg_ring.fetch_all()
        return self.pkt_ring.fetch_all()

    def fetch_last(self, text_only: bool) -> Packet | None:
        """Fetch the last Packet."""
        if text_only:
            return self.msg_ring.fetch_last()
        return self.pkt_ring.fetch_last()

    def fetch_latest(self, text_only: bool, count: int) -> list[Packet]:
        """Fetch the lastest Packets."""
        if text_only:
            return self.msg_ring.fetch_latest(count)
        return self.pkt_ring.fetch_latest(count)

    def fetch_new(self, current_id: int, text_only: bool) -> list[Packet]:
        """Fetch missed new Packets later than current_id."""
        if text_only:
            try:
                return self.msg_ring.fetch_new(current_id)
            except IndexError:
                return self.sql_store.fetch_new_messages(current_id)
        try:
            return self.pkt_ring.fetch_new(current_id)
        except IndexError:
            return self.sql_store.fetch_new_packets(current_id)

    def fetch_old(self, current_id: int, text_only: bool, count: int) -> list[Packet]:
        if text_only:
            try:
                return self.msg_ring.fetch_old(current_id, count)
            except IndexError:
                return self.sql_store.fetch_old_messages(current_id, count)
        try:
            return self.pkt_ring.fetch_old(current_id, count)
        except IndexError:
            return self.sql_store.fetch_old_packets(current_id, count)

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
