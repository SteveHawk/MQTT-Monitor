import random
import time

import pytest

from src.packet_store import Packet, SQLiteStore


@pytest.fixture
def sql_store() -> SQLiteStore:
    sql_store = SQLiteStore(":memory:")
    sql_store.init_tables()
    return sql_store


def test_table_creation(sql_store: SQLiteStore) -> None:
    with sql_store.con:
        tables = sql_store.con.execute("SELECT name FROM sqlite_master").fetchall()
        names = [t["name"] for t in tables]
        assert "packets" in names and "nodedb" in names

        broadcast = sql_store.con.execute(
            "SELECT * FROM nodedb WHERE node_num=0xFFFFFFFF"
        ).fetchone()
        assert dict(broadcast) == {
            "node_num": 0xFFFFFFFF,
            "id": "Broadcast",
            "long_name": "Broadcast 📢",
            "short_name": "📢",
        }


def test_nodeinfo(sql_store: SQLiteStore) -> None:
    node_num = random.randint(10000000, 10000000000000)
    node_id = hex(node_num)
    node_info: dict[str, int | str] = {
        "node_num": node_num,
        "id": (node_id := f"!{hex(node_num)[2:]}"),
        "long_name": f"Node {node_id}",
        "short_name": node_id[-4:],
    }

    sql_store.insert_nodeinfo(node_info)
    assert sql_store.fetch_nodeinfo(node_num) == node_info
    assert sql_store.fetch_nodedb()[node_num] == node_info


def test_packets(sql_store: SQLiteStore) -> None:
    packets = list[Packet]()
    messages = list[Packet]()
    for i in range(1, 20, 2):
        p = Packet(
            i,
            -1,
            {
                "from": random.randint(10000, 10000000),
                "to": 0xFFFFFFFF,
                "channel": 8,
                "decoded": {
                    "portnum": "POSITION_APP",
                    "payload": {"location_source": "LOC_MANUAL"},
                    "bitfield": 0,
                },
            },
            False,
            False,
            int(time.time()),
        )
        sql_store.insert_packet(p)
        packets.append(p)

        p = Packet(
            i + 1,
            (msg_id := i // 2 + 1),
            {
                "from": random.randint(10000, 10000000),
                "to": 0xFFFFFFFF,
                "channel": 8,
                "decoded": {
                    "portnum": "TEXT_MESSAGE_APP",
                    "payload": f"{msg_id} Test message hello 73",
                    "bitfield": 0,
                },
            },
            False,
            False,
            int(time.time()),
        )
        sql_store.insert_packet(p)
        packets.append(p)
        messages.append(p)

    assert packets == sql_store.fetch_new_packets(0)
    assert packets != sql_store.fetch_new_packets(1)
    assert packets[7:] == sql_store.fetch_new_packets(7)

    assert packets == sql_store.fetch_old_packets(21, 20)
    assert packets == sql_store.fetch_old_packets(25, 10000)
    assert packets != sql_store.fetch_old_packets(20, 20)
    assert packets != sql_store.fetch_old_packets(21, 19)
    assert packets[7:15] == sql_store.fetch_old_packets(16, 8)
    assert packets[:12] == sql_store.fetch_old_packets(13, 8888)
    assert packets[-1:] == sql_store.fetch_old_packets(13333, 1)

    assert packets == sql_store.fetch_latest_packets(20)
    assert packets == sql_store.fetch_latest_packets(500)
    assert packets != sql_store.fetch_latest_packets(19)
    assert packets[-7:] == sql_store.fetch_latest_packets(7)
    assert packets[-1:] == sql_store.fetch_latest_packets(1)

    assert messages == sql_store.fetch_new_messages(0)
    assert messages != sql_store.fetch_new_messages(1)
    assert messages[10:] == sql_store.fetch_new_messages(10)

    assert messages == sql_store.fetch_old_messages(11, 10)
    assert messages == sql_store.fetch_old_messages(19, 1000)
    assert messages != sql_store.fetch_old_messages(10, 10)
    assert messages != sql_store.fetch_old_messages(11, 9)
    assert messages[1:7] == sql_store.fetch_old_messages(8, 6)
    assert messages[:2] == sql_store.fetch_old_messages(3, 20)
    assert messages[-1:] == sql_store.fetch_old_messages(2000, 1)

    assert messages == sql_store.fetch_latest_messages(10)
    assert messages == sql_store.fetch_latest_messages(10000)
    assert messages != sql_store.fetch_latest_messages(9)
    assert messages[-5:] == sql_store.fetch_latest_messages(5)
    assert messages[-1:] == sql_store.fetch_latest_messages(1)
