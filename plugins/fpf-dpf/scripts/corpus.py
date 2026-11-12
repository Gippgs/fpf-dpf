#!/usr/bin/env python3
"""FPF + DPF corpus: pinned downloads, atomic snapshots and bounded retrieval.

Standard library only. Upstream Markdown is data, never executable configuration.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

from publications import select_publications

ROOT = Path(__file__).resolve().parents[1]
REPO = "ailev/FPF"
SCHEMA = 2
MAX_ARCHIVE = 80 * 1024 * 1024
MAX_CONTENT = 160 * 1024 * 1024
PATTERN = re.compile(r"^([A-Z][A-Z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)+)(?:\s+[-–—]\s+|\s*$)")


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(content):
    return hashlib.sha256(content).hexdigest()


def default_data():
    if os.environ.get("FPF_DPF_DATA"):
        return Path(os.environ["FPF_DPF_DATA"]).expanduser().resolve()
    # Works with Codex's stripped shell environment as well as a normal terminal.
    for parent in ROOT.parents:
        if (parent / ".codex").is_dir():
            return parent / "Documents" / "Codex" / "fpf-dpf-data"
    return Path.home() / "Documents" / "Codex" / "fpf-dpf-data"


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as out:
            json.dump(value, out, ensure_ascii=False, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def request_bytes(url, limit=MAX_ARCHIVE):
    req = urllib.request.Request(url, headers={"User-Agent": "fpf-dpf/1.0", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=45) as response:
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("Upstream response exceeds size limit")
    return body


def safe_path(name):
    p = PurePosixPath(name)
    return not (p.is_absolute() or ".." in p.parts or "\\" in name or ":" in name)


def wanted(path):
    p = PurePosixPath(path)
    return p.suffix.lower() in (".md", ".markdown") or p.name.upper() in ("LICENSE", "COPYING", "NOTICE")


def archive_files(data):
    """Read source text without extracting or executing repository files."""
    result, total = {}, 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            if not safe_path(item.filename):
                raise ValueError("Unsafe archive path")
            parts = PurePosixPath(item.filename).parts
            if len(parts) < 2:
                continue
            path = "/".join(parts[1:])
            if not wanted(path):
                continue
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Symlink in source text set")
            total += item.file_size
            if total > MAX_CONTENT:
                raise ValueError("Expanded corpus exceeds size limit")
            if path in result:
                raise ValueError("Duplicate source path")
            result[path] = archive.read(item).decode("utf-8-sig")
    return result


def local_files(directory):
    result = {}
    for file in sorted(directory.rglob("*")):
        if file.is_file() and wanted(file.name):
            if file.is_symlink():
                raise ValueError("Symlink in local source")
            result[file.relative_to(directory).as_posix()] = file.read_text(encoding="utf-8-sig")
    return result


def headings(text):
    result, fence = [], None
    for line_number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            char, width = marker[1][0], len(marker[1])
            if fence is None:
                fence = (char, width)
            elif char == fence[0] and width >= fence[1]:
                fence = None
            continue
        if fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if match:
            label = match[2].replace("**", "").replace("`", "").strip()
            found = PATTERN.match(label)
            result.append({"line": line_number, "level": len(match[1]), "title": label,
                           "pid": found[1] if found else None})
    return result


def describe(path, text):
    hs = headings(text)
    title = hs[0]["title"] if hs else PurePosixPath(path).stem
    intro = text[:6000]
    if "reference" in title.lower() or PurePosixPath(path).name.lower() in ("readme.md", "using-fpf.md"):
        kind = "REFERENCE"
    elif PurePosixPath(path).name == "FPF-Spec.md" or "first principles framework" in title.lower():
        kind = "FPF"
    elif "licens" in path.lower() or PurePosixPath(path).name.upper() in ("COPYING", "NOTICE"):
        kind = "LICENSE"
    elif re.search(r"\bDPF\b|domain (?:principle|pattern)|principles framework", title + "\n" + intro, re.I):
        kind = "DPF"
    else:
        kind = "DOCUMENT"
    pids = sorted({h["pid"] for h in sections(text)})
    return {"path": path, "title": title, "kind": kind, "hash": digest(text.encode()),
            "patterns": pids, "lines": len(text.splitlines()), "intro": intro[:2000]}


def reconcile(documents, previous):
    """Conservative one-to-one identity matching; ambiguous cases stay new."""
    old = {d["id"]: d for d in previous}
    assigned, remaining, changes = {}, set(old), {"added": [], "changed": [], "renamed": [], "removed": [], "ambiguous": []}
    for doc in documents:
        matches = [key for key in remaining if old[key]["path"] == doc["path"]]
        if len(matches) == 1:
            assigned[doc["path"]] = matches[0]
            remaining.remove(matches[0])
    for doc in documents:
        if doc["path"] in assigned:
            continue
        candidates = [key for key in remaining if old[key]["hash"] == doc["hash"]]
        if not candidates:
            current = set(doc["patterns"])
            for key in remaining:
                prior = old[key]
                ids = set(prior["patterns"])
                # A matching title alone is not a semantic identity guarantee.
                overlap = len(current & ids) / max(1, len(current | ids))
                if doc["title"] == prior["title"] and len(current & ids) >= 3 and overlap >= .8:
                    candidates.append(key)
        if len(candidates) == 1:
            key = candidates[0]
            # Multiple new copies of a removed file must not receive a guessed lineage.
            rivals = [d for d in documents if d["path"] not in assigned and d["hash"] == doc["hash"]]
            if len(rivals) == 1:
                assigned[doc["path"]] = key
                remaining.remove(key)
            else:
                changes["ambiguous"].append(doc["path"])
        elif candidates:
            changes["ambiguous"].append(doc["path"])
    used = set(old)
    for doc in documents:
        key = assigned.get(doc["path"])
        if key:
            prior = old[key]
            doc["id"] = key
            doc["aliases"] = list(dict.fromkeys(prior.get("aliases", []) + [prior["path"], prior["title"]]))
            if prior["path"] != doc["path"]:
                changes["renamed"].append({"from": prior["path"], "to": doc["path"], "id": key})
            if prior["hash"] != doc["hash"]:
                changes["changed"].append(doc["path"])
        else:
            key = "doc-" + digest(doc["path"].encode())[:12]
            if key in used:
                key += "-" + doc["hash"][:8]
            doc["id"], doc["aliases"] = key, []
            changes["added"].append(doc["path"])
        used.add(doc["id"])
    changes["removed"] = [old[key]["path"] for key in sorted(remaining)]
    return changes


def sections(text):
    lines, hs = text.splitlines(), headings(text)
    found = []
    pattern_level = min((h["level"] for h in hs if h["pid"]), default=0)
    for i, h in enumerate(hs):
        if not h["pid"] or h["level"] != pattern_level:
            continue
        end = len(lines)
        for other in hs[i + 1:]:
            if other["level"] <= h["level"] or other["title"].startswith(h["pid"] + ":End"):
                end = other["line"] - 1
                break
        found.append({**h, "end": end})
    return found


def chunks(text, pattern_sections):
    lines = text.splitlines()
    boundaries = {s["line"] - 1 for s in pattern_sections} | {s["end"] for s in pattern_sections}
    # All lines remain searchable, including unfamiliar formats and prefaces.
    pos = 0
    while pos < len(lines):
        start, length = pos, 0
        while pos < len(lines) and (length < 5500 or pos == start):
            if pos != start and pos in boundaries:
                break
            length += len(lines[pos]) + 1
            pos += 1
        owner = next((s for s in reversed(pattern_sections) if s["line"] <= start + 1 <= s["end"]), None)
        yield start + 1, pos, owner, "\n".join(lines[start:pos])


def make_database(path, files, documents, commit):
    hints = read_json(ROOT / "references" / "core-hints.json", {})
    con = sqlite3.connect(path)
    try:
        con.executescript("""
        CREATE TABLE documents(id TEXT PRIMARY KEY, path TEXT UNIQUE, title TEXT, kind TEXT, body TEXT, aliases TEXT);
        CREATE TABLE sections(key TEXT PRIMARY KEY, doc TEXT, pid TEXT, title TEXT, start INTEGER, end INTEGER);
        CREATE INDEX pattern_ids ON sections(pid);
        CREATE TABLE chunks(id INTEGER PRIMARY KEY, doc TEXT, pid TEXT, start INTEGER, end INTEGER, body TEXT);
        CREATE VIRTUAL TABLE search USING fts5(title, body, tokenize='porter unicode61');
        """)
        count = 0
        for doc in documents:
            text = files[doc["path"]]
            con.execute("INSERT INTO documents VALUES(?,?,?,?,?,?)", (doc["id"], doc["path"], doc["title"], doc["kind"], text, json.dumps(doc["aliases"])))
            ss, seen = sections(text), {}
            for s in ss:
                n = seen.get(s["pid"], 0)
                seen[s["pid"]] = n + 1
                key = doc["id"] + "::" + s["pid"] + (f"~{n + 1}" if n else "")
                con.execute("INSERT INTO sections VALUES(?,?,?,?,?,?)", (key, doc["id"], s["pid"], s["title"], s["line"], s["end"]))
            doc["duplicate_pattern_ids"] = [p for p, n in seen.items() if n > 1]
            for start, end, owner, body in chunks(text, ss):
                pattern_id = owner["pid"] if owner else ""
                title = doc["title"] + " " + doc["path"] + " " + " ".join(doc["aliases"])
                if owner:
                    title += " " + owner["title"]
                if doc["kind"] == "FPF" and pattern_id in hints:
                    title += " " + " ".join(hints[pattern_id].get("keywords", []) + hints[pattern_id].get("queries", []))
                count += 1
                con.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?)", (count, doc["id"], pattern_id, start, end, body))
                con.execute("INSERT INTO search(rowid,title,body) VALUES(?,?,?)", (count, title, body))
        con.commit()
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Database integrity check failed")
        total = con.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
        if not total:
            raise ValueError("No recognizable patterns; keeping previous snapshot")
        return {"documents": len(documents), "patterns": total, "chunks": count}
    finally:
        con.close()


@contextlib.contextmanager
def update_lock(data):
    data.mkdir(parents=True, exist_ok=True)
    lock = data / "update.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError("Another refresh may be running. Inspect update.lock before removing a stale lock.")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(json.dumps({"pid": os.getpid(), "started": now()}))
        yield
    finally:
        lock.unlink(missing_ok=True)


def current_snapshot(data, snapshot=None):
    if snapshot is None:
        pointer = read_json(data / "current.json")
        if not pointer:
            raise FileNotFoundError("No active snapshot. Run refresh first.")
        snapshot = pointer.get("snapshot", "")
    if not re.fullmatch(r"[a-f0-9]{32}", snapshot):
        raise ValueError("Invalid snapshot ID")
    folder = data / "snapshots" / snapshot
    manifest = read_json(folder / "manifest.json")
    if not manifest or not (folder / "corpus.sqlite").is_file():
        raise ValueError("Incomplete active snapshot")
    return folder, manifest


def publish(data, files, commit, source):
    if not files:
        raise ValueError("Empty corpus; previous snapshot retained")
    files, publication_scope = select_publications(files)
    documents = [describe(path, text) for path, text in sorted(files.items())]
    if sum(d["kind"] == "FPF" for d in documents) != 1:
        raise ValueError("Expected exactly one FPF Core document; inspect upstream layout")
    try:
        _, prior = current_snapshot(data)
    except FileNotFoundError:
        prior = {"documents": []}
    changes = reconcile(documents, prior["documents"])
    if prior.get("schema") == SCHEMA and prior["documents"] and len(documents) < len(prior["documents"]) / 2:
        raise ValueError("More than half the source set disappeared; inspect before accepting")
    folder = data / "snapshots" / uuid.uuid4().hex
    folder.mkdir(parents=True)
    counts = make_database(folder / "corpus.sqlite", files, documents, commit)
    manifest = {"schema": SCHEMA, "repo": REPO, "commit": commit, "source": source, "created": now(),
                "publication_scope": publication_scope,
                "counts": counts, "documents": documents, "changes": changes,
                "warnings": [d["path"] for d in documents if (d["kind"] in ("DPF", "DOCUMENT") and not d["patterns"]) or d["duplicate_pattern_ids"]]}
    atomic_json(folder / "manifest.json", manifest)
    # The old snapshot remains untouched; a failed build never changes this pointer.
    atomic_json(data / "current.json", {"snapshot": folder.name})
    return manifest


def refresh(data, if_stale=False, offline=False, source_dir=None, archive=None, commit=None):
    status = read_json(data / "refresh.json", {})
    try:
        _, active = current_snapshot(data)
    except FileNotFoundError:
        active = None
    if offline:
        return {"state": "offline", "active": active["commit"] if active else None, "last_check": status}
    if if_stale and active and status.get("error") and time.time() - status.get("attempt_epoch", 0) < 3600:
        return {"state": "retry_deferred", "commit": active["commit"], "last_check": status}
    with update_lock(data):
        try:
            if source_dir:
                files = local_files(source_dir)
                commit = commit or "local-" + digest(json.dumps(files, sort_keys=True).encode())[:16]
                source = "local"
            elif archive:
                if not commit or not re.fullmatch(r"[a-f0-9]{40}", commit):
                    raise ValueError("An archive import requires its 40-character upstream commit")
                files, source = archive_files(archive.read_bytes()), "archive"
            else:
                response = json.loads(request_bytes(f"https://api.github.com/repos/{REPO}/commits/main", 4 * 1024 * 1024))
                commit = response["sha"]
                if not re.fullmatch(r"[a-f0-9]{40}", commit):
                    raise ValueError("Invalid upstream commit")
                if active and active["commit"] == commit and active["schema"] == SCHEMA:
                    atomic_json(data / "refresh.json", {"checked": now(), "attempt_epoch": time.time(), "commit": commit, "error": None})
                    return {"state": "unchanged", "commit": commit, "counts": active["counts"]}
                files = archive_files(request_bytes(f"https://codeload.github.com/{REPO}/zip/{commit}"))
                source = "github"
            manifest = publish(data, files, commit, source)
            atomic_json(data / "refresh.json", {"checked": now(), "attempt_epoch": time.time(), "commit": commit, "error": None})
            return {"state": "updated", "commit": commit, "counts": manifest["counts"], "changes": manifest["changes"], "warnings": manifest["warnings"]}
        except Exception as exc:
            atomic_json(data / "refresh.json", {"checked": now(), "attempt_epoch": time.time(), "error": str(exc), "retained_commit": active["commit"] if active else None})
            raise


@contextlib.contextmanager
def connection(data, snapshot=None):
    folder, manifest = current_snapshot(data, snapshot)
    con = sqlite3.connect((folder / "corpus.sqlite").as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        yield con, manifest | {"snapshot": folder.name}
    finally:
        con.close()


def citation(manifest, path, start, end):
    if not re.fullmatch(r"[a-f0-9]{40}", manifest["commit"]):
        return None
    return f"https://github.com/{REPO}/blob/{manifest['commit']}/{urllib.parse.quote(path)}#L{start}-L{end}"


def catalog(data, query="", snapshot=None):
    folder, manifest = current_snapshot(data, snapshot)
    terms = re.findall(r"\w+", query.lower())
    rows = []
    for doc in manifest["documents"]:
        hay = " ".join([doc["title"], doc["path"], doc["intro"], *doc["aliases"]]).lower()
        score = sum(term in hay for term in terms)
        if terms and not score:
            continue
        rows.append({k: doc[k] for k in ("id", "path", "title", "kind", "aliases")} | {"patterns": len(doc["patterns"]), "score": score})
    return {"snapshot": folder.name, "commit": manifest["commit"], "documents": sorted(rows, key=lambda d: (-d["score"], d["kind"], d["title"]))}


def lookup(con, selector):
    rows = con.execute("SELECT s.*,d.path,d.kind FROM sections s JOIN documents d ON s.doc=d.id WHERE s.key=? OR s.pid=?", (selector, selector)).fetchall()
    if rows:
        return [dict(r) for r in rows]
    rows = con.execute("SELECT id AS doc,id AS key,path,title,kind,1 AS start FROM documents WHERE id=? OR path=? OR title=?", (selector, selector, selector)).fetchall()
    if not rows:
        rows = [r for r in con.execute("SELECT id AS doc,id AS key,path,title,kind,1 AS start,aliases FROM documents") if selector in json.loads(r["aliases"])]
    return [dict(r) for r in rows]


def search(data, query, limit=5, kind=None, document=None, snapshot=None):
    with connection(data, snapshot) as (con, manifest):
        version = {"snapshot": manifest["snapshot"], "commit": manifest["commit"]}
        exact = [r for r in lookup(con, query.strip()) if (not kind or r["kind"] == kind) and (not document or r["doc"] == document)]
        if exact:
            return version | {"mode": "exact", "results": exact[:limit], "matches": len(exact)}
        words = list(dict.fromkeys(re.findall(r"[\w]+", query, re.UNICODE)))[:32]
        if not words:
            return version | {"results": []}
        expr = " OR ".join('"' + w + '"' for w in words)
        from_sql = """FROM search JOIN chunks c ON c.id=search.rowid JOIN documents d ON d.id=c.doc
                 LEFT JOIN sections s ON s.doc=c.doc AND s.pid=c.pid AND c.start BETWEEN s.start AND s.end
                 WHERE search MATCH ?"""
        params = [expr]
        if kind:
            from_sql += " AND d.kind=?"
            params.append(kind)
        if document:
            from_sql += " AND d.id=?"
            params.append(document)
        matched_sections = con.execute("SELECT COUNT(*) FROM (SELECT DISTINCT c.doc, "
                                       "COALESCE(s.key, 'line-' || c.start) " + from_sql + ")", params).fetchone()[0]
        sql = "SELECT c.*,s.key AS section_key,d.path,d.title,d.kind,bm25(search,3,1) AS rank " + from_sql + " ORDER BY rank LIMIT ?"
        params.append(limit * 6)
        results, seen = [], set()
        for row in con.execute(sql, params):
            r = dict(row)
            section_key = r.pop("section_key")
            dedup = (r["doc"], section_key or r["start"])
            if dedup in seen:
                continue
            seen.add(dedup)
            r["selector"] = section_key or r["doc"]
            r["excerpt"] = r.pop("body")[:1200]
            r["url"] = citation(manifest, r["path"], r["start"], r["end"])
            results.append(r)
            if len(results) >= limit:
                break
        return version | {"mode": "fulltext", "results": results, "matched_sections": matched_sections,
                "query_note": "Sources are mostly English. Translate Russian concepts to English or use optional semantic retrieval."}


def read(data, selector, start=None, lines=180, snapshot=None):
    if lines < 1:
        raise ValueError("lines must be positive")
    with connection(data, snapshot) as (con, manifest):
        candidates = lookup(con, selector)
        if len(candidates) != 1:
            return {"error": "ambiguous" if candidates else "not_found", "candidates": candidates}
        row = candidates[0]
        text = con.execute("SELECT body FROM documents WHERE id=?", (row["doc"],)).fetchone()[0].splitlines()
        low, high = row["start"], row.get("end", len(text))
        start = max(low, start if start is not None else low)
        end = min(high, start + lines - 1)
        if start > high:
            raise ValueError(f"Start line is beyond this result ({low}..{high})")
        return {"snapshot": manifest["snapshot"], "commit": manifest["commit"], "selector": row["key"], "path": row["path"], "title": row["title"],
                "source_start": low, "source_end": high, "partial": start > low or end < high,
                "start": start, "end": end, "next_line": end + 1 if end < high else None,
                "url": citation(manifest, row["path"], start, end),
                "text": "\n".join(f"{i + 1}: {text[i]}" for i in range(start - 1, end))}


def routes(data, number=None, snapshot=None):
    definitions = read_json(ROOT / "references" / "routes.json", [])
    if number is not None:
        definitions = [r for r in definitions if r["number"] == number]
        if not definitions:
            raise ValueError("Unknown route")
    with connection(data, snapshot) as (con, manifest):
        result = []
        for route in definitions:
            items = []
            for item in route["patterns"]:
                matches = [r for r in lookup(con, item["id"]) if r["kind"] == "FPF"]
                items.append(item | {"available": bool(matches), "matches": matches})
            result.append(route | {"patterns": items})
        return {"snapshot": manifest["snapshot"], "commit": manifest["commit"], "routes": result, "note": "Optional entry points, never a mandatory project sequence."}


def status(data, snapshot=None):
    try:
        folder, manifest = current_snapshot(data, snapshot)
    except FileNotFoundError:
        return {"state": "empty", "data": str(data)}
    semantic = read_json(data / "semantic" / "manifest.json", {})
    scope = manifest.get("publication_scope", {"policy": "legacy-unfiltered", "catalogs": []})
    guide = next((d for d in manifest["documents"] if d["path"] == "USING-FPF.md"), None)
    return {"state": "ready", "data": str(data), "snapshot": folder.name, "commit": manifest["commit"],
            "is_active": read_json(data / "current.json", {}).get("snapshot") == folder.name,
            "created": manifest["created"], "counts": manifest["counts"], "warnings": manifest["warnings"],
            "publication_scope": {"policy": scope["policy"], "catalogs": scope["catalogs"],
                                  "excluded_count": len(scope.get("excluded_paths", []))},
            "usage_guide": ({"selector": guide["id"], "path": guide["path"], "hash": guide["hash"]}
                            if guide else None),
            "last_refresh": read_json(data / "refresh.json", {}),
            "semantic": "current" if semantic.get("snapshot") == folder.name else "absent_or_stale"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=default_data())
    parser.add_argument("--snapshot", help="Pin all reads to this snapshot; never silently use current")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    p = sub.add_parser("refresh")
    p.add_argument("--if-stale", action="store_true", help="Compatibility flag: defer failed-check retries for one hour; successful checks never skip a new check")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--source-dir", type=Path)
    p.add_argument("--archive", type=Path)
    p.add_argument("--commit")
    p = sub.add_parser("catalog")
    p.add_argument("query", nargs="?", default="")
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--kind", choices=["FPF", "DPF", "REFERENCE", "DOCUMENT", "LICENSE"])
    p.add_argument("--document")
    p = sub.add_parser("read")
    p.add_argument("selector")
    p.add_argument("--start-line", type=int)
    p.add_argument("--lines", type=int, default=180)
    p = sub.add_parser("route")
    p.add_argument("number", type=int, nargs="?")
    p = sub.add_parser("packet", help="Cached, size-bounded exact source excerpts; not a semantic summary")
    p.add_argument("query")
    p.add_argument("--selector", action="append", default=[])
    p.add_argument("--scope", default="")
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--max-chars", type=int, default=18000)
    p.add_argument("--kind", choices=["FPF", "DPF", "REFERENCE", "DOCUMENT", "LICENSE"])
    p.add_argument("--document")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            result = status(args.data, args.snapshot)
        elif args.command == "refresh":
            if args.snapshot:
                raise ValueError("--snapshot is for reads; refresh creates or selects the current snapshot")
            result = refresh(args.data, args.if_stale, args.offline, args.source_dir, args.archive, args.commit)
        elif args.command == "catalog":
            result = catalog(args.data, args.query, args.snapshot)
        elif args.command == "search":
            result = search(args.data, args.query, max(1, min(args.limit, 30)), args.kind, args.document, args.snapshot)
        elif args.command == "read":
            result = read(args.data, args.selector, args.start_line, max(1, min(args.lines, 500)), args.snapshot)
        elif args.command == "packet":
            from packets import packet
            result = packet(args.data, args.query, args.selector, args.scope, args.limit,
                            args.max_chars, args.kind, args.document, args.snapshot)
        else:
            result = routes(args.data, args.number, args.snapshot)
        # Compact packets have an enforced serialized character budget, including newline.
        print(json.dumps(result, ensure_ascii=False, **({"separators": (",", ":")} if args.command == "packet" else {"indent": 2})))
        return 1 if "error" in result else 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "active_snapshot_retained": (args.data / "current.json").exists()}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
