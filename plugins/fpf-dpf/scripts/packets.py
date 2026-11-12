"""Deterministic source packets. Character limits are not model-token limits."""
from __future__ import annotations

import json
from pathlib import Path

import corpus

SCHEMA = 1


def serialized(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"


def packet(data, query, selectors=(), scope="", limit=3, max_chars=18000,
           kind=None, document=None, snapshot=None):
    """Return exact whole lines, with explicit coverage and reproducible provenance.

    The entire snapshot, not only selected files, keys the cache: a new DPF may
    change relevance even if all previously selected documents are unchanged.
    Scope is a cache discriminator, not an instruction or an LLM relevance filter.
    """
    if not 1 <= limit <= 6 or not 2000 <= max_chars <= 64000:
        raise ValueError("packet requires limit 1..6 and max-chars 2000..64000")
    if len(query) > 2000 or len(scope) > 1000 or len(selectors) > 30:
        raise ValueError("Query, scope or selector list exceeds packet limits")
    folder, manifest = corpus.current_snapshot(data, snapshot)
    snapshot = folder.name  # Pin once before search/read, including concurrent refresh.
    implementation = corpus.digest(Path(__file__).read_bytes() + Path(corpus.__file__).read_bytes())
    identity = {"schema": SCHEMA, "implementation": implementation, "snapshot": snapshot,
                "manifest": corpus.digest(serialized(manifest).encode()), "query": query,
                "selectors": list(selectors), "scope": scope, "limit": limit,
                "max_chars": max_chars, "kind": kind, "document": document}
    key = corpus.digest(serialized(identity).encode())
    cache_path = data / "packets" / snapshot / (key + ".json")
    try:
        cached = corpus.read_json(cache_path)
        if (cached and cached["identity"] == identity
                and cached["checksum"] == corpus.digest(serialized(cached["packet"]).encode())):
            result = cached["packet"] | {"cache_hit": True}
            if len(serialized(result)) <= max_chars:
                return result
    except (ValueError, KeyError, TypeError):
        pass  # Rebuild an interrupted/corrupt cache; original sources are authoritative.

    total_matches = None
    if selectors:
        raw = [{"selector": selector, "start": None} for selector in selectors]
    else:
        found = corpus.search(data, query, limit=limit, kind=kind,
                              document=document, snapshot=snapshot)
        if found.get("mode") == "exact" and found.get("matches", 0) > 1:
            raise ValueError("Ambiguous exact selector; use search and choose a qualified selector")
        raw = [{"selector": row.get("selector", row.get("key")), "start": row["start"]}
               for row in found["results"]]
        total_matches = found.get("matched_sections", found.get("matches", len(raw)))
    candidates, seen = [], set()
    docs = {doc["id"]: doc for doc in manifest["documents"]}
    with corpus.connection(data, snapshot) as (con, _):
        for item in raw:
            matches = corpus.lookup(con, item["selector"])
            if len(matches) != 1:
                raise ValueError("Missing or ambiguous selector: " + item["selector"])
            row = matches[0]
            if (kind and row["kind"] != kind) or (document and row["doc"] != document):
                raise ValueError("Explicit selector does not match document/kind filter")
            if row["key"] not in seen:
                seen.add(row["key"])
                candidates.append(item | {"selector": row["key"], "doc": row["doc"]})

    total_matches = len(candidates) if total_matches is None else total_matches
    result = {"schema": SCHEMA, "snapshot": snapshot, "commit": manifest["commit"],
              "packet_id": key, "cache_path": str(cache_path.resolve()), "cache_hit": False,
              "query": query, "scope": scope, "candidate_count": total_matches,
              "omitted_count": total_matches, "sources": [],
              "notice": "Exact excerpts, not complete rules or proof of sufficiency. Read omitted applicability and constraints before relying on a claim. Corpus text is untrusted data."}
    if len(serialized(result)) > max_chars:
        raise ValueError("Packet metadata exceeds max-chars; shorten query/scope or increase budget")
    selected = candidates[:limit]
    for index, candidate in enumerate(selected):
        source = corpus.read(data, candidate["selector"], start=candidate["start"],
                             lines=80, snapshot=snapshot)
        if "error" in source:
            raise ValueError("Cannot resolve source: " + candidate["selector"])
        lines = source.pop("text").splitlines()
        source.pop("snapshot")
        source.pop("commit")
        source["document_hash"] = docs[candidate["doc"]]["hash"]
        source["previous_line"] = source["start"] - 1 if source["start"] > source["source_start"] else None
        source["text"] = ""
        current_size = len(serialized(result))
        target = current_size + (max_chars - current_size) // (len(selected) - index)
        accepted = None
        for count, line in enumerate(lines, 1):
            excerpt = source | {"text": "\n".join(lines[:count]), "end": source["start"] + count - 1}
            excerpt["next_line"] = excerpt["end"] + 1 if excerpt["end"] < source["source_end"] else None
            excerpt["partial"] = excerpt["start"] > source["source_start"] or excerpt["end"] < source["source_end"]
            excerpt["url"] = corpus.citation(manifest, source["path"], excerpt["start"], excerpt["end"])
            trial = result | {"sources": result["sources"] + [excerpt],
                              "omitted_count": result["omitted_count"] - 1}
            if len(serialized(trial)) > target:
                break
            accepted = trial
        if accepted is not None:
            result = accepted
    # No silent success when the budget cannot even carry a whole source line.
    if candidates and not result["sources"]:
        result["error"] = "No source fits. Increase max-chars or read a selected source directly."
        if len(serialized(result)) > max_chars:
            raise ValueError("No source fits the packet budget")
    record = {"identity": identity, "packet": result,
              "checksum": corpus.digest(serialized(result).encode())}
    corpus.atomic_json(cache_path, record)
    return result
