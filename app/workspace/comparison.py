"""Readable, deterministic comparison of immutable document snapshots."""

from difflib import SequenceMatcher


def lines(revision: dict) -> list[str]:
    draft = revision["draft"]
    result = ["Title: " + revision["title"], "Summary: " + draft["executive_summary"]]
    for section in draft["sections"]:
        result.append("Section: " + section["heading"])
        result.extend(section.get("paragraphs", []))
        result.extend("• " + item for item in section.get("bullets", []))
        result.extend(f"{i}. {item}" for i, item in enumerate(section.get("numbered_items", []), 1))
        table = section.get("table")
        if table:
            # repr preserves cell boundaries even when text contains a pipe or tab.
            result.append("Table columns: " + repr(table["headers"]))
            result.extend("Table row: " + repr(row) for row in table["rows"])
    result.append("Conclusion: " + draft["conclusion"])
    return result


def compare(before: dict, after: dict) -> dict:
    old, new = lines(before), lines(after)
    changes = []
    added = removed = 0
    for kind, a, b, c, d in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        changes.append({"kind": kind, "before": old[a:b], "after": new[c:d]})
        if kind != "equal":
            removed += b - a
            added += d - c
    return {"from_version": before["number"], "to_version": after["number"],
            "added": added, "removed": removed, "changes": changes}
