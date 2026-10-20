"""Prepare only reviewed V6 source files in a fresh upload checkout.

Run under verify_offline.py. This tool never uses credentials or network and
does not stage, commit, push, run source code, or copy research data. It refuses
symlinks, unknown file types, credential-shaped content and notebook outputs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


TOP = ("README.md", "LICENSE", "pyproject.toml", "requirements.txt", "requirements-build.txt", ".gitignore")
TREES = ("src/quarry", "docs", "tests", "examples", "tools")
SUFFIXES = {".py", ".md", ".json", ".html", ".js", ".css", ".ipynb", ".txt", ".sb", ".yaml"}
PDFS = {"src/quarry/fixtures/jargon.pdf", "src/quarry/fixtures/broken.pdf"}
LOCAL_DIRECTORIES = {"verification", "projects", "studies", "v6-studies", "my-study",
                     "output", "outputs", "exports", "datasets", "dist", "build", "__pycache__"}
SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{50,}"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{35,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{30,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]{80,}?-----END"),
)
ARTIFACT_LINK = re.compile(r"\[([^\]\n]+)\]\((\.\./(?:verification|dist)/[^)\n]+)\)")
IGNORES = """\n# Local researcher data and harness settings\n.DS_Store\n.env*\n!.env.example\n*.pem\n*.key\n*.log\n.codex/\n.claude/\n.agents/\n.mcp.json\nv6-mcp.json\n.v6-connect.lock\nagent-handoff/\nstudies/\nv6-studies/\nmy-study/\noutputs/\nexports/\ndatasets/\nintegrations/\nBUILD_CONTRACT.md\n"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    checkout = args.checkout.absolute()
    if not checkout.is_relative_to(root / "verification") or not (checkout / ".git").is_dir():
        parser.error("Use the separate verification upload checkout")
    if checkout.is_symlink() or any(p.is_symlink() for p in checkout.parents):
        parser.error("The checkout path must not be symlinked")
    target = checkout / "V6-community-term-finder"
    if target.exists():
        parser.error("The publication folder already exists; preserve it")
    candidates = [root / name for name in TOP]
    for tree in TREES:
        candidates.extend(sorted((root / tree).rglob("*")))
    approved = []
    for path in candidates:
        relative = path.relative_to(root)
        if LOCAL_DIRECTORIES.intersection(relative.parts):
            continue
        if path.is_symlink():
            raise ValueError("Symlink in publication inputs: " + relative.as_posix())
        if not path.is_file() or any(p.startswith(".") for p in relative.parts if p != ".gitignore") or "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.name not in TOP and path.suffix not in SUFFIXES and relative.as_posix() not in PDFS:
            raise ValueError("Unreviewed publication file type: " + relative.as_posix())
        data = path.read_bytes()
        if len(data) > 3_000_000:
            raise ValueError("Oversized publication file: " + relative.as_posix())
        if relative.as_posix() not in PDFS:
            text = data.decode("utf-8")
            if any(pattern.search(text) for pattern in SECRET_PATTERNS):
                raise ValueError("Credential-shaped content requires review: " + relative.as_posix())
            if re.search(r"/(?:Users|home)/[^/\s]+/", text):
                raise ValueError("Personal absolute path requires review: " + relative.as_posix())
            if path.suffix == ".ipynb":
                notebook = json.loads(text)
                if any(cell.get("outputs") or cell.get("execution_count") is not None for cell in notebook["cells"]):
                    raise ValueError("Clear notebook outputs before publication: " + relative.as_posix())
        transformed = data
        if relative.parts[0] == "docs" and path.suffix == ".md":
            text = data.decode("utf-8")
            transformed = ARTIFACT_LINK.sub(lambda match: "`" + match[2] + "` (local artifact)", text).encode("utf-8")
        if relative.as_posix() == ".gitignore":
            transformed = data + IGNORES.encode()
        approved.append((relative, data, transformed))
    # Validate every input before creating or writing the fresh V6 folder.
    target.mkdir()
    inventory = []
    for relative, source, published in approved:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(published)
        inventory.append({"path": relative.as_posix(), "source_sha256": digest(source),
                          "published_sha256": digest(published), "documentation_adapted": source != published})
    manifest = {"schema_version": 1, "package_version": "6.5.0", "origin": "source_publication_preparation",
        "collector_code_changed": False, "files": inventory, "raw_data_uploaded": False,
        "excluded": ["environments", "wheelhouses", "build outputs", "raw verification", "studies and datasets",
                     "credentials and host settings", "generated handoff", "legacy integration", "internal coordination"]}
    (target / "docs" / "SOURCE_UPLOAD_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(inventory), "collector_code_changed": False,
        "documentation_adaptations": sum(row["documentation_adapted"] for row in inventory),
        "raw_data_uploaded": False}))


if __name__ == "__main__":
    main()
