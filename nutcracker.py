#!/usr/bin/env python3
"""NUTCRACKER: persistent human review state."""

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from magpie_overlay import (
    require,
    read_json,
    verify_link,
    verify_schema,
    timestamp,
)


SCHEMA_VERSION = 1

STATUSES = (
    "pending",
    "accepted",
    "rejected",
    "corrected",
    "deferred",
    "unresolvable",
)

TIERS = (
    "focused",
    "balanced",
    "comprehensive",
)


# ------------------------------------------------------------
# Identity and serialization
# ------------------------------------------------------------

def utc_now():

    return datetime.now(
        timezone.utc
    ).isoformat()


def canonical_json(value):

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def fingerprint(value):

    return hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


def evidence_identity(
    source_hash,
    kind,
    item,
):

    # Conservative identity: changing the actual
    # evidence creates a different identity.
    #
    # Scheduling settings are not included.

    content = {
        key: value
        for key, value in item.items()
        if key != "id"
    }

    return fingerprint({
        "source_sha256": source_hash,
        "kind": kind,
        "evidence": content,
    })


# ------------------------------------------------------------
# Database
# ------------------------------------------------------------

def connect(path):

    require(
        path.is_file(),
        f"Database does not exist: {path}",
    )

    db = sqlite3.connect(path)

    db.row_factory = sqlite3.Row

    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")

    version = db.execute(
        "PRAGMA user_version"
    ).fetchone()[0]

    require(
        version == SCHEMA_VERSION,
        f"Unsupported database version: {version}",
    )

    return db


def initialize_database(path):

    # Exclusive creation prevents overwriting
    # an existing human review database.

    with path.open("xb"):
        pass

    db = sqlite3.connect(path)

    db.row_factory = sqlite3.Row

    db.execute("PRAGMA foreign_keys = ON")

    db.executescript("""
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE evidence (
            identity TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            source_id TEXT NOT NULL,
            start REAL NOT NULL,
            end REAL NOT NULL,
            payload TEXT NOT NULL,
            imported_at TEXT NOT NULL,

            UNIQUE(kind, source_id)
        );

        CREATE TABLE decisions (
            evidence_identity TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (
                status IN (
                    'pending',
                    'accepted',
                    'rejected',
                    'corrected',
                    'deferred',
                    'unresolvable'
                )
            ),
            selected_hypothesis INTEGER,
            correction TEXT,
            notes TEXT,
            updated_at TEXT NOT NULL,

            FOREIGN KEY(evidence_identity)
                REFERENCES evidence(identity)
        );

        CREATE TABLE decision_history (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            evidence_identity TEXT NOT NULL,
            previous_state TEXT NOT NULL,
            new_state TEXT NOT NULL,
            recorded_at TEXT NOT NULL,

            FOREIGN KEY(evidence_identity)
                REFERENCES evidence(identity)
        );

        CREATE TABLE windows (
            tier TEXT NOT NULL,
            window_id TEXT NOT NULL,
            start REAL NOT NULL,
            end REAL NOT NULL,
            payload TEXT NOT NULL,

            PRIMARY KEY(tier, window_id)
        );

        CREATE TABLE window_evidence (
            tier TEXT NOT NULL,
            window_id TEXT NOT NULL,
            evidence_identity TEXT NOT NULL,
            relationship TEXT NOT NULL,

            PRIMARY KEY(
                tier,
                window_id,
                evidence_identity
            ),

            FOREIGN KEY(tier, window_id)
                REFERENCES windows(tier, window_id),

            FOREIGN KEY(evidence_identity)
                REFERENCES evidence(identity)
        );

        CREATE INDEX evidence_time
            ON evidence(start, end);

        CREATE INDEX decision_status
            ON decisions(status);

        CREATE INDEX window_evidence_identity
            ON window_evidence(evidence_identity);

        PRAGMA user_version = 1;
    """)

    return db


# ------------------------------------------------------------
# Evidence import
# ------------------------------------------------------------

def import_evidence(
    db,
    source_hash,
    kind,
    items,
):

    identities = {}

    for item in items:

        identity = evidence_identity(
            source_hash,
            kind,
            item,
        )

        source_id = item["id"]

        require(
            source_id not in identities,
            f"Duplicate evidence ID: {source_id}",
        )

        require(
            0 <= item["start"] <= item["end"],
            f"Invalid evidence interval: {source_id}",
        )

        identities[source_id] = identity

        now = utc_now()

        db.execute("""
            INSERT INTO evidence (
                identity,
                kind,
                source_id,
                start,
                end,
                payload,
                imported_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            identity,
            kind,
            source_id,
            item["start"],
            item["end"],
            canonical_json(item),
            now,
        ))

        db.execute("""
            INSERT INTO decisions (
                evidence_identity,
                status,
                updated_at
            )
            VALUES (?, 'pending', ?)
        """, (
            identity,
            now,
        ))

    return identities


def import_windows(
    db,
    audit,
    magpie_ids,
    hunt_ids,
):

    for tier in TIERS:

        windows = audit["results"][tier][
            "windows"
        ]

        for window in windows:

            window_id = window["id"]

            db.execute("""
                INSERT INTO windows (
                    tier,
                    window_id,
                    start,
                    end,
                    payload
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                tier,
                window_id,
                window["start"],
                window["end"],
                canonical_json(window),
            ))

            associations = {}

            for source_id in window[
                "magpie_region_ids"
            ]:

                associations[
                    magpie_ids[source_id]
                ] = "contained"

            for source_id in window[
                "hunt_partial_ids"
            ]:

                associations[
                    hunt_ids[source_id]
                ] = "partial"

            for source_id in window[
                "hunt_contained_ids"
            ]:

                associations[
                    hunt_ids[source_id]
                ] = "contained"

            for identity, relationship in (
                associations.items()
            ):

                db.execute("""
                    INSERT INTO window_evidence (
                        tier,
                        window_id,
                        evidence_identity,
                        relationship
                    )
                    VALUES (?, ?, ?, ?)
                """, (
                    tier,
                    window_id,
                    identity,
                    relationship,
                ))


# ------------------------------------------------------------
# Integrity checks
# ------------------------------------------------------------

def audit_database(db):

    result = db.execute(
        "PRAGMA integrity_check"
    ).fetchone()[0]

    require(
        result == "ok",
        "SQLite integrity check failed",
    )

    require(
        not db.execute(
            "PRAGMA foreign_key_check"
        ).fetchall(),
        "Foreign key integrity failed",
    )

    evidence_count = db.execute("""
        SELECT COUNT(*) FROM evidence
    """).fetchone()[0]

    decision_count = db.execute("""
        SELECT COUNT(*) FROM decisions
    """).fetchone()[0]

    require(
        evidence_count == decision_count,
        "Evidence/decision count mismatch",
    )

    comprehensive_count = db.execute("""
        SELECT COUNT(DISTINCT evidence_identity)
        FROM window_evidence
        WHERE tier = 'comprehensive'
          AND relationship = 'contained'
    """).fetchone()[0]

    require(
        comprehensive_count == evidence_count,
        "Comprehensive coverage incomplete",
    )

    return evidence_count


# ------------------------------------------------------------
# Initialize review state
# ------------------------------------------------------------

def command_init(args):

    overlay, overlay_input = read_json(
        args.overlay
    )

    hunt, hunt_input = read_json(
        args.hunt
    )

    audit, audit_input = read_json(
        args.audit
    )

    verify_schema(
        overlay,
        "hehawk.magpie.overlay",
    )

    verify_schema(
        hunt,
        "hehawk.hunt.shared_gaps",
    )

    verify_schema(
        audit,
        "hehawk.nutcracker.queue_audit",
    )

    verify_link(
        audit["inputs"]["overlay"],
        overlay_input,
        "queue audit -> overlay",
    )

    verify_link(
        audit["inputs"]["hunt"],
        hunt_input,
        "queue audit -> HUNT",
    )

    verify_link(
        hunt["inputs"]["overlay"],
        overlay_input,
        "HUNT -> overlay",
    )

    hashes = {
        item["source_sha256"]
        for item in (overlay, hunt, audit)
    }

    require(
        len(hashes) == 1,
        "Episode source mismatch",
    )

    source_hash = next(iter(hashes))

    db = initialize_database(args.database)

    try:

        with db:

            metadata = {
                "source_sha256": source_hash,
                "created_at": utc_now(),
                "overlay": overlay_input,
                "hunt": hunt_input,
                "queue_audit": audit_input,
                "schema_version": SCHEMA_VERSION,
            }

            for key, value in metadata.items():

                db.execute("""
                    INSERT INTO metadata (
                        key, value
                    )
                    VALUES (?, ?)
                """, (
                    key,
                    canonical_json(value),
                ))

            magpie_ids = import_evidence(
                db,
                source_hash,
                "magpie",
                overlay["regions"],
            )

            hunt_ids = import_evidence(
                db,
                source_hash,
                "hunt",
                hunt["candidates"],
            )

            import_windows(
                db,
                audit,
                magpie_ids,
                hunt_ids,
            )

            count = audit_database(db)

        print("NUTCRACKER initialized")
        print(f"MAGPIE regions: {len(magpie_ids)}")
        print(f"HUNT candidates: {len(hunt_ids)}")
        print(f"Total evidence: {count}")
        print("All decisions: pending")
        print("Integrity: PASS")
        print(f"Database: {args.database}")

    finally:
        db.close()


# ------------------------------------------------------------
# Status reporting
# ------------------------------------------------------------

def command_status(args):

    db = connect(args.database)

    try:

        count = audit_database(db)

        print("NUTCRACKER review status")
        print("=" * 72)
        print(f"Evidence items: {count}")

        print("\nDecision counts")

        rows = db.execute("""
            SELECT
                e.kind,
                d.status,
                COUNT(*) AS count
            FROM evidence e
            JOIN decisions d
              ON d.evidence_identity = e.identity
            GROUP BY e.kind, d.status
            ORDER BY e.kind, d.status
        """)

        for row in rows:

            print(
                f"  {row['kind']:10}"
                f" {row['status']:15}"
                f" {row['count']:6}"
            )

        print("\nPending review windows")

        for tier in TIERS:

            row = db.execute("""
                SELECT
                    COUNT(*) AS count,
                    COALESCE(
                        SUM(w.end - w.start), 0
                    ) AS seconds
                FROM windows w
                WHERE w.tier = ?
                  AND EXISTS (
                      SELECT 1
                      FROM window_evidence we
                      JOIN decisions d
                        ON d.evidence_identity
                         = we.evidence_identity
                      WHERE we.tier = w.tier
                        AND we.window_id = w.window_id
                        AND d.status = 'pending'
                        AND we.relationship = 'contained'
                  )
            """, (tier,)).fetchone()

            seconds = row["seconds"]

            print(
                f"  {tier:15}"
                f" {row['count']:4} windows"
                f" {timestamp(seconds)}"
                f" ({seconds:.3f}s)"
            )

        events = db.execute("""
            SELECT COUNT(*)
            FROM decision_history
        """).fetchone()[0]

        print(f"\nDecision history events: {events}")
        print("Integrity: PASS")

    finally:
        db.close()


# ------------------------------------------------------------
# Retrieve next review window
# ------------------------------------------------------------

def command_next(args):

    db = connect(args.database)

    try:

        window = db.execute("""
            SELECT w.*
            FROM windows w
            WHERE w.tier = ?
              AND EXISTS (
                  SELECT 1
                  FROM window_evidence we
                  JOIN decisions d
                    ON d.evidence_identity
                     = we.evidence_identity
                  WHERE we.tier = w.tier
                    AND we.window_id = w.window_id
                    AND we.relationship = 'contained'
                    AND d.status = 'pending'
              )
            ORDER BY w.start
            LIMIT 1
        """, (args.tier,)).fetchone()

        if window is None:

            print(
                f"No pending windows in {args.tier}."
            )

            return

        print(
            f"{args.tier.upper()} "
            f"{window['window_id']}"
        )

        print(
            f"{timestamp(window['start'])}"
            f" - {timestamp(window['end'])}"
        )

        print(
            f"({window['start']:.3f}"
            f" - {window['end']:.3f}s)"
        )

        rows = db.execute("""
            SELECT
                e.*,
                d.status,
                we.relationship
            FROM window_evidence we
            JOIN evidence e
              ON e.identity = we.evidence_identity
            JOIN decisions d
              ON d.evidence_identity = e.identity
            WHERE we.tier = ?
              AND we.window_id = ?
            ORDER BY e.start, e.kind
        """, (
            args.tier,
            window["window_id"],
        ))

        print("\nAssociated evidence")

        for row in rows:

            print(
                f"  {row['source_id']:8}"
                f" {row['kind']:8}"
                f" {row['status']:13}"
                f" {row['relationship']:10}"
                f" {timestamp(row['start'])}"
                f" - {timestamp(row['end'])}"
            )

    finally:
        db.close()


# ------------------------------------------------------------
# Inspect individual evidence
# ------------------------------------------------------------

def get_evidence(db, source_id):

    rows = db.execute("""
        SELECT *
        FROM evidence
        WHERE source_id = ?
    """, (source_id,)).fetchall()

    require(
        len(rows) == 1,
        f"Evidence ID not uniquely found: {source_id}",
    )

    return rows[0]


def command_show(args):

    db = connect(args.database)

    try:

        row = get_evidence(
            db,
            args.evidence_id,
        )

        decision = db.execute("""
            SELECT *
            FROM decisions
            WHERE evidence_identity = ?
        """, (row["identity"],)).fetchone()

        print(json.dumps({
            "identity": row["identity"],
            "kind": row["kind"],
            "evidence": json.loads(row["payload"]),
            "decision": dict(decision),
        }, ensure_ascii=False, indent=2))

    finally:
        db.close()


# ------------------------------------------------------------
# Record human decisions
# ------------------------------------------------------------

def command_decide(args):

    db = connect(args.database)

    try:

        # Acquire the write lock before reading
        # the previous decision.

        db.execute("BEGIN IMMEDIATE")

        row = get_evidence(
            db,
            args.evidence_id,
        )

        evidence = json.loads(
            row["payload"]
        )

        identity = row["identity"]

        if args.hypothesis is not None:

            require(
                row["kind"] == "magpie",
                "Only MAGPIE has hypotheses",
            )

            require(
                1 <= args.hypothesis
                <= len(evidence["hypotheses"]),
                "Invalid hypothesis number",
            )

            require(
                args.status == "accepted",
                "Hypothesis requires accepted status",
            )

        if (
            row["kind"] == "magpie"
            and args.status == "accepted"
        ):

            require(
                args.hypothesis is not None,
                "Select a MAGPIE hypothesis",
            )

        if args.status == "corrected":

            require(
                args.correction is not None
                and bool(args.correction.strip()),
                "Correction text required",
            )

        else:

            require(
                args.correction is None,
                "Correction requires corrected status",
            )

        previous = dict(db.execute("""
            SELECT *
            FROM decisions
            WHERE evidence_identity = ?
        """, (identity,)).fetchone())

        now = utc_now()

        current = {
            "evidence_identity": identity,
            "status": args.status,
            "selected_hypothesis": args.hypothesis,
            "correction": args.correction,
            "notes": args.notes,
            "updated_at": now,
        }

        comparable = (
            "status",
            "selected_hypothesis",
            "correction",
            "notes",
        )

        if all(
            previous[key] == current[key]
            for key in comparable
        ):

            db.rollback()
            print("Decision unchanged.")
            return

        db.execute("""
            UPDATE decisions
            SET
                status = ?,
                selected_hypothesis = ?,
                correction = ?,
                notes = ?,
                updated_at = ?
            WHERE evidence_identity = ?
        """, (
            current["status"],
            current["selected_hypothesis"],
            current["correction"],
            current["notes"],
            current["updated_at"],
            identity,
        ))

        db.execute("""
            INSERT INTO decision_history (
                evidence_identity,
                previous_state,
                new_state,
                recorded_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            identity,
            canonical_json(previous),
            canonical_json(current),
            now,
        ))

        db.commit()

        print(
            f"{args.evidence_id}: "
            f"{previous['status']} -> "
            f"{args.status}"
        )

        print("Decision committed.")
        print("Previous state preserved.")

    except Exception:

        db.rollback()
        raise

    finally:
        db.close()


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=__doc__
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    init = commands.add_parser("init")

    init.add_argument("overlay", type=Path)
    init.add_argument("hunt", type=Path)
    init.add_argument("audit", type=Path)
    init.add_argument("database", type=Path)

    init.set_defaults(handler=command_init)

    status = commands.add_parser("status")

    status.add_argument("database", type=Path)

    status.set_defaults(handler=command_status)

    next_window = commands.add_parser("next")

    next_window.add_argument(
        "database", type=Path
    )

    next_window.add_argument(
        "--tier",
        choices=TIERS,
        default="focused",
    )

    next_window.set_defaults(
        handler=command_next
    )

    show = commands.add_parser("show")

    show.add_argument("database", type=Path)
    show.add_argument("evidence_id")

    show.set_defaults(handler=command_show)

    decide = commands.add_parser("decide")

    decide.add_argument("database", type=Path)
    decide.add_argument("evidence_id")
    decide.add_argument(
        "status",
        choices=STATUSES,
    )

    decide.add_argument(
        "--hypothesis",
        type=int,
    )

    decide.add_argument("--correction")
    decide.add_argument("--notes")

    decide.set_defaults(
        handler=command_decide
    )

    args = parser.parse_args()

    args.handler(args)


if __name__ == "__main__":
    main()

