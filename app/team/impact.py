"""Deterministic review attention hints, never an automatic approval decision."""

import json
from collections import Counter

from app.workspace.comparison import compare


def changed_sections(before: dict, after: dict) -> list[dict]:
    old, new = before["sections"], after["sections"]
    counts = Counter(s["heading"] for s in old + new)
    unique_old = {s["heading"]: (i, s) for i, s in enumerate(old)
                  if sum(x["heading"] == s["heading"] for x in old) == 1}
    used = set()
    changes = []
    for index, section in enumerate(new):
        match = unique_old.get(section["heading"])
        # Duplicate headings are ambiguous: don't pretend to track their identity.
        if match and counts[section["heading"]] == 2:
            previous_index, previous = match
            used.add(previous_index)
            if previous != section or previous_index != index:
                changes.append({"heading": section["heading"], "kind":
                                "changed" if previous != section else "moved", "section": index})
        else:
            changes.append({"heading": section["heading"], "kind": "added_or_renamed", "section": index})
    changes.extend({"heading": s["heading"], "kind": "removed_or_renamed", "section": None}
                   for i, s in enumerate(old) if i not in used)
    return changes


def review_impact(store, doc_id: str) -> dict:
    with store.connection() as conn:
        conn.execute("BEGIN")
        row = conn.execute("SELECT payload FROM documents WHERE id=?", (doc_id,)).fetchone()
        if row is None:
            raise KeyError(doc_id)
        doc = json.loads(row[0])
        approval = conn.execute(
            "SELECT * FROM review_decisions WHERE document_id=? AND decision='approved' "
            "AND version<? ORDER BY version DESC, created_at DESC LIMIT 1",
            (doc_id, doc["version"]),
        ).fetchone()
        result = {"current_version": doc["version"], "baseline_version": None,
                  "changes": [], "changed_fields": [], "open_feedback": []}
        if not approval or not doc["artifact"]:
            return result
        baseline = conn.execute("SELECT title, draft FROM versions WHERE document_id=? AND number=?",
                                (doc_id, approval["version"])).fetchone()
        if baseline is None:
            return result
        old, current = json.loads(baseline["draft"]), doc["artifact"]["draft"]
        result.update(baseline_version=approval["version"],
                      approved_by=json.loads(approval["author"])["name"],
                      changes=changed_sections(old, current))
        result["text_changes"] = compare(
            {"number": approval["version"], "title": baseline["title"], "draft": old},
            {"number": doc["version"], "title": doc["title"], "draft": current},
        )
        result["changed_fields"] = [name for name in ("executive_summary", "conclusion")
                                    if old[name] != current[name]]
        if baseline["title"] != doc["title"]:
            result["changed_fields"].append("title")
        feedback = conn.execute(
            "SELECT version, section_title, body FROM review_threads "
            "WHERE document_id=? AND version>=? AND version<? AND resolved=0 ORDER BY created_at",
            (doc_id, approval["version"], doc["version"]),
        ).fetchall()
        result["open_feedback"] = [dict(item) for item in feedback]
        return result
