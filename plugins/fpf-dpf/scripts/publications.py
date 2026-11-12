"""Select public publications from upstream inventories, never from pattern links."""
from pathlib import PurePosixPath
import posixpath
import re
import urllib.parse


INVENTORY = re.compile(r"^(?:what is in (?:the )?(?:library|repository)\??|publications|published dpfs)$", re.I)
LINK = re.compile(r"\[([^\]]+)\]\(\s*(<[^>]+>|[^)]+)\)")
UNPUBLISHED = re.compile(r"^(?:draft|unpublished|planned|historical|withdrawn|archived|candidate)\b", re.I)
NEW_INVENTORIES = {
    "Readme.md": {"what is available"},
    "DPFs/README.md": {"suites", "further domain frameworks"},
}
SUITE_INVENTORIES = {"frameworks in this suite", "constituent dpfs and their different contributions"}
UNPUBLISHED_PATH = re.compile(r"^(?:drafts?|unpublished|history|historical|archived?|withdrawn)(?:[-_.]|$)", re.I)


def inventory_links(text, catalog=""):
    """Read membership tables and Reference links only within inventory sections."""
    active_level, auxiliary, fence, found, link_count = None, None, None, False, 0
    new_layout, new_sections = False, set()
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif marker[1][0] == fence:
                fence = None
            continue
        if fence:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            level, title = len(heading[1]), heading[2].replace("**", "").strip()
            if active_level is not None and level <= active_level:
                active_level = None
            if auxiliary is not None and level <= auxiliary[0]:
                auxiliary = None
            normalized = title.lower()
            new_section = (normalized in NEW_INVENTORIES.get(catalog, set()) or
                           catalog.startswith("DPFs/") and catalog.endswith("/README.md") and
                           normalized in SUITE_INVENTORIES)
            if INVENTORY.fullmatch(title) or new_section:
                active_level, found = level, True
                new_layout |= new_section
                if new_section:
                    new_sections.add(normalized)
            elif catalog == "Readme.md" and normalized in {
                "how the library is organized and why", "read online or use your own copies"}:
                auxiliary = (level, normalized)
            elif catalog == "DPFs/README.md" and normalized == "how the frameworks fit together":
                auxiliary = (level, normalized)
            elif catalog.startswith("DPFs/") and catalog.endswith("/README.md") and normalized == "how this suite is organized and why":
                auxiliary = (level, normalized)
        if auxiliary is not None and not line.lstrip().startswith("|"):
            for label, target in LINK.findall(line):
                label = label.lower()
                expected = (catalog == "Readme.md" and auxiliary[1] == "read online or use your own copies"
                            and label == "core markdown file and its history" and target == "FPF-Spec.md")
                reference = ("architectural reference" in label and
                             urllib.parse.urlsplit(target).path.lower().endswith("-reference.md"))
                if expected or reference:
                    link_count += 1
                    yield target
        if active_level is None:
            continue
        if line.lstrip().startswith("|"):
            cells = line.strip().strip("|").split("|")
            # A declared non-public status is not a publication, even if linked.
            if any(UNPUBLISHED.match(c.strip().strip("* ")) for c in cells[:2]):
                continue
            # Engineering tables put the publication in column two; root and
            # Foundational tables put it in column one. Inspect both.
            candidates = "|".join(cells[:2])
        else:
            # Suite References may be introduced in prose below the member table.
            candidates = " ".join(m[0] for m in LINK.finditer(line)
                                  if "reference" in m[1].lower() or
                                  new_layout and catalog == "Readme.md" and
                                  m[1].lower() == "dpf catalogue")
        if re.search(r"\[[^\]]+\]\s*\[[^\]]*\]", candidates):
            raise ValueError("Reference-style inventory links require a parser update")
        for match in LINK.finditer(candidates):
            target = match[2].strip()
            if target.startswith("<"):
                target = target[1:-1]
            else:
                target = re.split(r'\s+["\']', target, maxsplit=1)[0]
            link_count += 1
            yield target
    if not found:
        raise ValueError("No recognized public inventory section; inspect upstream README layout")
    if catalog == "DPFs/README.md" and new_sections and new_sections != NEW_INVENTORIES[catalog]:
        raise ValueError("Incomplete public DPF catalogue; inspect upstream README layout")
    if not link_count:
        raise ValueError("Empty or unsupported public inventory; inspect upstream README layout")


def resolve_link(catalog, target, files):
    url = urllib.parse.urlsplit(target)
    path = urllib.parse.unquote(url.path)
    if url.scheme or url.netloc:
        # Resolve repository links in the selected copy, not another live edition.
        prefix = "/ailev/FPF/"
        if url.netloc.lower() != "github.com" or not path.startswith(prefix):
            return None
        parts = path[len(prefix):].split("/", 2)
        if len(parts) != 3 or parts[0] not in ("blob", "tree"):
            return None
        path = parts[2]
    else:
        if not path:
            return None
        path = posixpath.join(posixpath.dirname(catalog), path)
    path = posixpath.normpath(path)
    if path.startswith("/") or path == ".." or path.startswith("../") or "\\" in path or ":" in path:
        raise ValueError("Unsafe inventory link: " + target)
    if PurePosixPath(path).suffix.lower() not in (".md", ".markdown"):
        matches = [p for p in files if posixpath.dirname(p) == path
                   and PurePosixPath(p).name.lower() == "readme.md"]
        if len(matches) != 1:
            raise ValueError("Missing or ambiguous Suite inventory: " + path)
        path = matches[0]
    if path not in files:
        raise ValueError("Missing declared publication: " + path)
    return path


def select_publications(files):
    roots = [p for p in files if "/" not in p and p.lower() == "readme.md"]
    if len(roots) != 1 or "USING-FPF.md" not in files or not files["USING-FPF.md"].strip():
        raise ValueError("Public corpus requires a root README inventory and nonempty USING-FPF.md")
    selected, catalogs, pending = {"USING-FPF.md"}, [], roots[:]
    while pending:
        catalog = pending.pop(0)
        if catalog in catalogs:
            continue
        catalogs.append(catalog)
        selected.add(catalog)
        for target in inventory_links(files[catalog], catalog):
            path = resolve_link(catalog, target, files)
            if path is None:
                continue
            if any(UNPUBLISHED_PATH.match(part) for part in PurePosixPath(path).parts):
                continue
            selected.add(path)
            if PurePosixPath(path).name.lower() == "readme.md":
                pending.append(path)
    # Keep attribution beside the selected publications, without indexing notes.
    parents = {posixpath.dirname(p) for p in selected}
    selected.update(p for p in files if posixpath.dirname(p) in parents
                    and PurePosixPath(p).name.lower() in
                    {"license", "license.md", "licensing.md", "copying", "notice", "notice.md"})
    return {p: files[p] for p in sorted(selected)}, {
        "policy": "public-readme-inventories-v1", "catalogs": sorted(catalogs),
        "excluded_paths": sorted(set(files) - selected),
    }
