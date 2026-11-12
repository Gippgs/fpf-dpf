"""Print one role's preset and instructions; orchestration stays in native Codex."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEEP = {"scout": "medium", "analyst": "high", "expert": "xhigh", "reviewer": "high"}


def role(name, deep=False):
    roles = json.loads((ROOT / "references/roles.json").read_text(encoding="utf-8"))["roles"]
    if name not in roles:
        raise ValueError("Unknown role: " + name)
    preset = roles[name].copy()
    path = (ROOT / preset.pop("instructions")).resolve()
    path.relative_to(ROOT.resolve())
    if deep:
        preset["reasoning_effort"] = DEEP[name]
    return {"role": name, **preset, "instruction_file": str(path),
            "instructions": path.read_text(encoding="utf-8"),
            "runtime_policy": {"max_simultaneous_subagents": 2, "recursive_delegation": False,
                               "token_budget": "soft; no hard model-token cap is enforced by this helper"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("role")
    p.add_argument("name", choices=list(DEEP))
    p.add_argument("--deep", action="store_true", help="Use only for a stated difficulty or required guarantee")
    args = parser.parse_args()
    print(json.dumps(role(args.name, args.deep), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
