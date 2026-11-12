"""Minimal published distribution for retrieval tests."""
import urllib.parse


def published(files):
    files = dict(files)
    intro = files.get("Readme.md", "# Library\n")
    files["Readme.md"] = intro + "\n## What is in the Library?\n\n| Publication | Status |\n| --- | --- |\n" + "".join(
        f"| [Publication]({urllib.parse.quote(p)}) | Published |\n"
        for p in sorted(files) if p not in ("Readme.md", "USING-FPF.md"))
    files.setdefault("USING-FPF.md", "# Using the Library\nRead selected methods and necessary dependencies.\n")
    return files
