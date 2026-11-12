#!/usr/bin/env python3
# /// script
# dependencies = ["sentence-transformers>=3.0", "numpy>=1.26"]
# ///
"""Optional multilingual semantic retrieval, using the original BAAI/bge-m3 model.

Run with uv run, or a Python environment containing sentence-transformers/numpy.
The normal corpus workflow works without these optional downloads.
"""
import argparse
import json
from pathlib import Path
import sys
import uuid

import corpus


def available_index(data):
    folder, _ = corpus.current_snapshot(data)
    meta = corpus.read_json(data / "semantic" / "manifest.json", {})
    if meta.get("snapshot") != folder.name:
        raise ValueError("Semantic index absent or stale; use fulltext search or rebuild.")
    if not __import__("re").fullmatch(r"[a-f0-9]{32}\.npy", meta.get("vectors", "")):
        raise ValueError("Invalid vector filename")
    return meta


def build(data, encoder, np, model_name):
    folder, manifest = corpus.current_snapshot(data)
    with corpus.connection(data) as (con, _):
        rows = [dict(r) for r in con.execute("SELECT c.id,c.body,d.title FROM chunks c JOIN documents d ON c.doc=d.id WHERE d.kind!='LICENSE' ORDER BY c.id")]
    vectors = encoder.encode([r["title"] + "\n" + r["body"] for r in rows], normalize_embeddings=True, batch_size=8, show_progress_bar=True)
    vectors = np.asarray(vectors, dtype=np.float32)
    if len(vectors.shape) != 2 or vectors.shape[0] != len(rows) or not np.isfinite(vectors).all():
        raise ValueError("Invalid embeddings; previous semantic index retained")
    if corpus.current_snapshot(data)[0] != folder:
        raise ValueError("Corpus changed during embedding build; retry against the new snapshot")
    out = data / "semantic"
    out.mkdir(parents=True, exist_ok=True)
    filename = uuid.uuid4().hex + ".npy"
    np.save(out / filename, vectors, allow_pickle=False)
    meta = {"snapshot": folder.name, "commit": manifest["commit"], "model": model_name,
            "vectors": filename, "ids": [r["id"] for r in rows], "created": corpus.now()}
    corpus.atomic_json(out / "manifest.json", meta)
    return {"state": "built", "commit": manifest["commit"], "vectors": len(rows)}


def search(data, query, encoder, np, limit=5):
    meta = available_index(data)
    vectors = np.load(data / "semantic" / meta["vectors"], allow_pickle=False)
    q = encoder.encode([query], normalize_embeddings=True)[0]
    ranked = np.argsort(-(vectors @ q))
    results, seen = [], set()
    with corpus.connection(data) as (con, manifest):
        if corpus.current_snapshot(data)[0].name != meta["snapshot"]:
            raise ValueError("Corpus changed; retry")
        for i in ranked:
            row = con.execute("SELECT c.*,d.path,d.title,d.kind FROM chunks c JOIN documents d ON c.doc=d.id WHERE c.id=?", (meta["ids"][int(i)],)).fetchone()
            r = dict(row)
            key = (r["doc"], r["pid"] or r["start"])
            if key in seen:
                continue
            seen.add(key)
            r["selector"] = r["doc"] + "::" + r["pid"] if r["pid"] else r["doc"]
            r["score"] = float(vectors[int(i)] @ q)
            r["excerpt"] = r.pop("body")[:1200]
            r["url"] = corpus.citation(manifest, r["path"], r["start"], r["end"])
            results.append(r)
            if len(results) >= limit:
                break
    return {"mode": "semantic", "commit": manifest["commit"], "results": results}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, default=corpus.default_data())
    p.add_argument("--model", default="BAAI/bge-m3")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("build")
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=5)
    args = p.parse_args()
    try:
        model = args.model if args.command == "build" else available_index(args.data)["model"]
        import numpy as np
        from sentence_transformers import SentenceTransformer
        encoder = SentenceTransformer(model, trust_remote_code=False)
        result = build(args.data, encoder, np, model) if args.command == "build" else search(args.data, args.query, encoder, np, max(1, min(args.limit, 30)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ImportError:
        print(json.dumps({"error": "Optional sentence-transformers/numpy are not installed. Fulltext search remains available."}))
        return 1
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
