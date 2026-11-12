# FPF + DPF

A plugin for Codex and Claude Code for FPF Core and domain frameworks from
[ailev/FPF](https://github.com/ailev/FPF).

Retains the previous FPF-agent's ten analysis routes and adds a dynamic DPF
catalog, corpus-wide search, pattern-ID lookup, and version-pinned citations.
Uses the minimum sufficient level of detail.

Start a new chat and ask: "Apply FPF and a relevant DPF to my task..."
To inspect sources, ask: "Show corpus freshness and available DPFs."

## Updates

At the start of each new task, the skill checks the upstream commit and downloads
only changed content (or rebuilds after an index-schema change). Public publications
are selected from root/Suite README inventories, including their References;
unlisted drafts and working notes do not enter the index. New and changed
publications enter automatically. A broken inventory preserves the old snapshot.
Ordinary renames retain old names as search aliases; ambiguous changes are
reported explicitly. Download or indexing failures preserve the previous
working snapshot. No background service is installed.

The corpus lives separately in `Documents/Codex/fpf-dpf-data`.
Project files and user questions are not sent to the repository or a search service.
Use `scripts/run.ps1 status` to inspect status and `scripts/run.ps1 refresh` to
update manually. On other systems, use Python 3.10+ and `scripts/corpus.py`.

Primary search requires no neural model download. The optional multilingual
semantic module remains available; install its dependencies and model only
when warranted. See `references/maintenance.md`.

Before choosing methods, the agent reads the pinned `USING-FPF.md` completely.
It reuses that reading while the guide and access are unchanged and available
in working context. Required inputs, applicability conditions and relevant
method connections must be read even when they span several retrieval pages.

## Models and context

The Codex subagent presets described below are specific to Codex. Claude Code
uses the same corpus and skill in the main session.

The main chat handles simple tasks. When warranted, the skill requests native
Codex subagents: Terra low for discovery, Sol medium for analysis, Astra high
for difficult interpretation, and Sol high for focused review. Increase effort
for a stated reason. Run at most two subagents at once, without further delegation.
The skill does not switch the main chat's model. Report unavailable tools or
models explicitly.

`scripts/run.ps1 role scout` returns one preset and its instructions; `--deep`
selects greater reasoning effort. Presets live in `references/roles.json`.
The skill uses them when spawning agents; it installs no global agents or
Codex settings. See `references/harness.md`.

After the freshness check, `status` returns a snapshot ID. Pin every read:
`scripts/run.ps1 --snapshot ID read C.19.2`.
`--snapshot ID packet 'English query' --max-chars 18000` returns bounded exact
source excerpts. Repeat `--selector ID` to choose specific sources. Partial
coverage and omissions are explicit; read remaining applicability conditions
from the original source when needed.

Packets are cached locally with the corpus and keyed by the entire snapshot,
query parameters, and builder version. A new DPF also invalidates the old
packet for a new task. An ongoing task retains its selected snapshot.
Query and scope text are cached locally: omit project secrets.
The cache holds source material, not verified conclusions about the project.

The JSON size limit is in characters. Agent count, reasoning effort, and response
length are governed by skill instructions, not a separate spending controller.
Overall token or quota savings are not guaranteed. Dots is not included.

## Limits

New source formats may require parser changes. Unrecognized published Markdown documents
remain searchable and readable. One legacy route contains `A.6.Q`, an ID already
missing in the previous plugin; it is flagged rather than silently replaced.

Run tests with `python -m unittest discover -s tests`.
One optional semantic-module test uses NumPy and a test encoder; it checks index
and retrieval integration, not model quality. See `NOTICE.md` for attribution.
