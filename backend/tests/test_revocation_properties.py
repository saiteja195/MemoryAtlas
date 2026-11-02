"""Property tests: revocation on random support graphs, including cyclic ones.

The graphs are random mixes of sources (owned by one of up to three grants) and claims, each
justified by a source and/or by a derivation over other claims. Premises may point anywhere,
so cycles (A supports B, B supports A) are common. After revoking a random set of grants:

 (a) every surviving claim has a well-founded support path (a finite proof with no cycle);
 (b) every claim that has such a path survives (nothing is lost that did not have to be);
 (c) the survivors equal an independent oracle computed from the original data;
 (d) revoking again changes nothing, and
 (e) the order in which grants are revoked does not matter;
 plus: other people's sources are untouched and no leak probe fails.
"""
import hypothesis.strategies as st
from hypothesis import HealthCheck, example, given, settings

from app import db
from app.embed import embed
from app.privacy.consent import create_grant
from app.privacy.revocation import RevocationEngine

SECRET = "prop-secret"


@st.composite
def graphs(draw):
    n_grants = draw(st.integers(1, 3))
    n_sources = draw(st.integers(1, 6))
    n_claims = draw(st.integers(1, 10))
    source_grant = [draw(st.integers(0, n_grants - 1)) for _ in range(n_sources)]
    justs = []
    for _ in range(n_claims):
        k = draw(st.integers(1, 2))
        js = []
        for _ in range(k):
            if draw(st.booleans()):
                js.append(("s", draw(st.integers(0, n_sources - 1))))
            else:       # premises may include the claim itself or later claims: cycles happen
                js.append(("d", frozenset(draw(st.lists(st.integers(0, n_claims - 1),
                                                        min_size=1, max_size=3, unique=True)))))
        justs.append(js)
    revoked = draw(st.lists(st.integers(0, n_grants - 1), unique=True, max_size=n_grants))
    return {"n_grants": n_grants, "source_grant": source_grant, "justs": justs, "revoked": revoked}


def build(g):
    conn = db.connect()
    conn.execute("INSERT INTO entities VALUES ('e0','object','thing',NULL)")
    tokens = {}
    for i in range(g["n_grants"]):
        _, tokens[i] = create_grant(conn, SECRET, f"person{i}", f"sess{i}", grant_id=f"G{i}")
    for i, gi in enumerate(g["source_grant"]):
        conn.execute("INSERT INTO sources(source_id, kind, session_id, grant_id, captured_at,"
                     " ingested_at, text, content_hash) VALUES (?,?,?,?,?,?,?,?)",
                     (f"S{i}", "frame_observation", f"sess{gi}", f"G{gi}", "2026-10-29T10:00:00",
                      "t", f"source number zebra{i}", f"h{i}"))
    for c, js in enumerate(g["justs"]):
        text = f"claim wording qux{c}"
        conn.execute("INSERT INTO claims VALUES (?,?,?,NULL,?,NULL,NULL,NULL,'direct_observation',"
                     "0.9,NULL,?,'active',NULL,'t')", (f"C{c}", "e0", "said", f"value qux{c}", text))
        conn.execute("INSERT INTO claim_index(claim_id, text) VALUES (?,?)", (f"C{c}", text))
        conn.execute("INSERT INTO claim_vectors VALUES (?,?)", (f"C{c}", embed(text).tobytes()))
    for c, js in enumerate(g["justs"]):
        for k, (kind, ref) in enumerate(js):
            jid = f"J{c}_{k}"
            if kind == "s":
                conn.execute("INSERT INTO justifications VALUES (?,?,'source',?,NULL)",
                             (jid, f"C{c}", f"S{ref}"))
            else:
                conn.execute("INSERT INTO justifications VALUES (?,?,'derivation',NULL,'rule')",
                             (jid, f"C{c}"))
                conn.executemany("INSERT INTO justification_premises VALUES (?,?)",
                                 [(jid, f"C{p}") for p in sorted(ref)])
    conn.commit()
    return conn, tokens


def provable(g, live_sources):
    """Independent oracle: which claims have a finite, cycle-free proof from live sources.
    Plain recursion with an explicit 'currently proving' stack, unlike the engine's fixpoint."""
    def prove(c, stack):
        if c in stack:
            return False
        for kind, ref in g["justs"][c]:
            if kind == "s" and ref in live_sources:
                return True
            if kind == "d" and all(prove(p, stack | {c}) for p in ref):
                return True
        return False
    return {c for c in range(len(g["justs"])) if prove(c, frozenset())}


def initially_valid(g):
    """The pipeline never writes a claim without support, so start from graphs where every
    claim has a finite proof from the original sources. Cycles are still allowed."""
    return provable(g, set(range(len(g["source_grant"])))) == set(range(len(g["justs"])))


def survivors(conn):
    return {int(r[0][1:]) for r in conn.execute("SELECT claim_id FROM claims")}


def snapshot(conn):
    return {t: sorted(map(tuple, conn.execute(f"SELECT * FROM {t}").fetchall()))
            for t in ("claims", "sources", "entities", "justifications", "justification_premises",
                      "claim_index", "claim_vectors", "blocked_hashes")}


def revoke_all(conn, tokens, order):
    eng = RevocationEngine(conn, SECRET, None)
    return [eng.revoke(f"G{i}", tokens[i], run_red_team=False) for i in order]


# The graph that once made the export probe see a phrase created by JSON layout ("said value").
@example({"n_grants": 3, "source_grant": [0, 2, 0, 1],
          "justs": [[("s", 0)], [("d", frozenset({0}))], [("d", frozenset({0, 3})), ("s", 0)],
                    [("s", 3)], [("d", frozenset({0}))], [("s", 1)]], "revoked": [1, 0]})
@settings(max_examples=1000, deadline=None, suppress_health_check=list(HealthCheck))
@given(graphs().filter(lambda g: initially_valid(g)))
def test_revocation_is_exactly_well_founded_support(g):
    conn, tokens = build(g)
    live = {i for i, gi in enumerate(g["source_grant"]) if gi not in g["revoked"]}
    receipts = revoke_all(conn, tokens, g["revoked"])

    left = survivors(conn)
    expected = provable(g, live)
    assert left == expected                       # (c) matches the oracle exactly
    assert left <= expected                       # (a) nothing survives without a proof
    assert expected <= left                       # (b) nothing with a proof is lost

    # (a) again, from the post-state tables only: every survivor has a live source or a
    # derivation whose premises are all survivors that are themselves proven without it.
    rows = conn.execute("SELECT j.claim_id, j.justification_id, j.kind, j.source_id FROM"
                        " justifications j").fetchall()
    prem = {}
    for p in conn.execute("SELECT justification_id, premise_claim_id FROM justification_premises"):
        prem.setdefault(p[0], []).append(p[1])
    live_ids = {f"S{i}" for i in live}
    assert {r["claim_id"] for r in rows} == {f"C{c}" for c in left}   # no justification for the dead
    for r in rows:
        if r["kind"] == "source":
            assert r["source_id"] in live_ids
        else:
            assert all(int(p[1:]) in left for p in prem[r["justification_id"]])

    # sources of grants that were not revoked are untouched; revoked ones are blank
    for i, gi in enumerate(g["source_grant"]):
        text, status = conn.execute("SELECT text, status FROM sources WHERE source_id=?",
                                    (f"S{i}",)).fetchone()
        assert (text is None, status) == ((True, "revoked") if gi in g["revoked"] else (False, "active"))

    # no leak probe ever fails (the red-team probe is skipped here: no model)
    for r in receipts:
        assert r["summary"]["probes_failed"] == 0, r["probes"]
        assert r["summary"]["probes_skipped"] == 1

    # (d) idempotent: revoking again changes nothing and returns the same receipts
    state = snapshot(conn)
    again = revoke_all(conn, tokens, g["revoked"])
    assert snapshot(conn) == state
    assert [a["receipt_id"] for a in again] == [r["receipt_id"] for r in receipts]
    assert all(a["already_revoked"] for a in again)


@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck))
@given(graphs().filter(lambda g: initially_valid(g)), st.randoms(use_true_random=False))
def test_the_order_of_revocations_does_not_matter(g, rnd):
    order = list(g["revoked"])
    shuffled = order[:]
    rnd.shuffle(shuffled)
    a, ta = build(g)
    b, tb = build(g)
    revoke_all(a, ta, order)
    revoke_all(b, tb, shuffled)
    assert survivors(a) == survivors(b)
    assert {r[0] for r in a.execute("SELECT entity_id FROM entities")} == \
        {r[0] for r in b.execute("SELECT entity_id FROM entities")}
    assert sorted(r[0] for r in a.execute("SELECT content_hash FROM blocked_hashes")) == \
        sorted(r[0] for r in b.execute("SELECT content_hash FROM blocked_hashes"))


@settings(max_examples=200, deadline=None, suppress_health_check=list(HealthCheck))
@given(graphs().filter(lambda g: initially_valid(g)))
def test_revoking_everything_leaves_nothing_behind(g):
    conn, tokens = build(g)
    revoke_all(conn, tokens, list(range(g["n_grants"])))
    assert survivors(conn) == set()
    for t in ("claims", "claim_index", "claim_vectors", "justifications", "justification_premises"):
        assert conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sources WHERE text IS NOT NULL").fetchone()[0] == 0
