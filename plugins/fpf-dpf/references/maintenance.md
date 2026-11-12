# Corpus maintenance

`scripts/run.ps1 refresh` checks the full `ailev/FPF` main commit once at the
start of each new task. A successful recent check does not suppress the next
task's check. Unchanged commits reuse the index unless its schema changed.
The legacy `--if-stale` flag only defers failed-check retries for one hour.
`status` reports the active version, last check, publication scope and guide hash.
Updates affect public reference data, never this plugin's executable code.

The downloader pins every file to one commit and selects publications through
the root README's Library/repository inventory and each linked Suite README's
Publications/Published DPFs tables, including References named in that inventory.
Only those catalogs determine membership: ordinary publication cross-links do
not admit drafts. The guide and adjacent attribution files are retained.
The selection policy, catalogs and excluded paths are recorded in the manifest.
No fixed DPF filenames or Suite names are required. New inventory layouts require
an explicit parser update; absent catalogs, missing declared files or a missing
USING-FPF.md block promotion. Unknown published formats remain readable, with a
warning if no patterns are parsed. Nothing from upstream is executed.

A missing or ambiguous Core or loss of over half a same-schema corpus also blocks
promotion. The first migration from the old unfiltered schema allows a smaller
public set, after all new inventory checks pass. Status labels old unfiltered
snapshots explicitly; do not claim they passed publication selection.

Each successful build creates a self-contained SQLite snapshot. The active
pointer changes only after integrity checking and manifest creation. Old
snapshots are retained for manual rollback, not automatically deleted. The data
folder can therefore grow; `status` reports its location. A refresh lock avoids
overlapping updates. If a crashed process leaves `update.lock`, verify that its
recorded process is no longer working before removing that one file.

Identity matching uses a current path, unique exact content, or a matching title
plus at least three shared pattern IDs and 80% ID-set overlap. Old paths/titles
remain aliases. Ambiguous changes are reported as additions/removals, never
silently asserted to be a rename. Removed text leaves the active index but stays
in previous snapshots. Large semantic reorganizations may need human maintenance.

## Optional multilingual embeddings

Normal operation needs only Python 3.10+ with SQLite FTS5. Fulltext retrieval and
agent-side translation cover ordinary Russian-language use without model downloads.
To retain the previous plugin's optional multilingual semantic capability, this
package supplies `scripts/semantic.py` with the same BAAI/bge-m3 embedding model.
When the model/dependencies are already available or their setup is warranted:

```text
uv run <ROOT>/scripts/semantic.py build
uv run <ROOT>/scripts/semantic.py search "How should responsibility be divided between teams?"
```

Alternatively run with Python containing `sentence-transformers` and `numpy`.
No paid API is needed. First use can download a large model. Index vectors are
normalized and ranked by inner product (the same cosine ranking as the previous
FAISS index), with NumPy rather than an additional FAISS dependency. A semantic
index is accepted only for its exact corpus snapshot; after an update, rebuild
it or use fulltext. Never use stale vectors against new section IDs.

## Installation and recovery

Install from the repository marketplace for your client. Both clients use the
same bundled corpus helper. The local corpus lives outside the plugin cache and
refreshes on use. To update the plugin itself, refresh its marketplace and load
the updated plugin in a new session.
