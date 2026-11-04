"""One profile's connection is shared by every request thread. Statements must not trip over each other: the
dashboard asks for the graph, the insights and the to-dos at the same moment."""
import json
import threading

from app import db


def test_many_threads_share_one_connection_without_tearing_rows(tmp_path):
    conn = db.connect(str(tmp_path / "shared.db"))
    for i in range(40):
        conn.execute("INSERT INTO consent_grants(grant_id, grantor, scope, scope_ref, purposes, token_hash, granted_at)"
                     " VALUES (?,?,?,?,?,?,?)", (f"g{i}", "me", "capture_session", f"s{i}", json.dumps(["personal_recall"]), "h", "t"))
    conn.commit()
    errors: list[BaseException] = []

    def reader(n: int) -> None:
        try:
            for _ in range(300):
                rows = conn.execute("SELECT grant_id, purposes FROM consent_grants ORDER BY grant_id").fetchall()
                assert len(rows) == 40
                for r in rows:
                    assert json.loads(r["purposes"]) == ["personal_recall"]
                conn.execute("SELECT COUNT(*) FROM claims").fetchone()
        except BaseException as e:  # noqa: BLE001 - any failure in a worker is a failure of the test
            errors.append(e)

    threads = [threading.Thread(target=reader, args=(n,)) for n in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []


def test_a_statement_hands_back_its_rows_already_fetched(tmp_path):
    conn = db.connect(str(tmp_path / "rows.db"))
    conn.execute("INSERT INTO blocked_hashes(content_hash, reason) VALUES ('a','x'), ('b','y')")
    cur = conn.execute("SELECT content_hash FROM blocked_hashes ORDER BY content_hash")
    conn.execute("DELETE FROM blocked_hashes")             # a later statement cannot change what this one returned
    assert [r["content_hash"] for r in cur.fetchall()] == ["a", "b"]
    assert conn.execute("INSERT INTO blocked_hashes(content_hash, reason) VALUES ('c','z')").rowcount == 1
