"""Local publication checks for tracked and unignored candidates; no file contents printed."""
from pathlib import Path
import argparse
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RULES = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "GitHub credential": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "provider credential": re.compile(r"\b(?:sk-[A-Za-z0-9_-]{24,}|hf_[A-Za-z0-9]{25,})\b"),
    "credential in URL": re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]{8,}@", re.I),
    "credential assignment": re.compile(
        r'''(?i)(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|wifi[_-]?password)\s*[=:]\s*["']([A-Za-z0-9+/=_-]{16,})["']'''),
}
PLACEHOLDERS = ("example", "placeholder", "your_", "your-", "changeme", "replace", "test", "dummy")
MODEL_SUFFIXES = {".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".gguf", ".ggml"}
GENERATED_PARTS = {".venv", "venv", "__pycache__", ".pio", "node_modules"}


def inspect_file(path, content):
    """Return locations/rules only. Never return or print matched values."""
    issues = []
    name = Path(path).name.lower()
    parts = set(Path(path).parts)
    if (name == ".env" or name.startswith(".env.")) and not name.endswith((".example", ".template", ".sample")):
        issues.append((0, "machine-local environment file"))
    if parts & GENERATED_PARTS or Path(path).suffix.lower() in MODEL_SUFFIXES:
        issues.append((0, "environment/build artifact or model weights"))
    if Path(path).suffix.lower() in {".db", ".sqlite", ".sqlite3"} and not str(path).replace("\\", "/").startswith("tests/fixtures/"):
        issues.append((0, "runtime database; inspect privacy and use a scoped ignore rule"))
    if str(path).replace("\\", "/").startswith(("data/", "dataset/", "sentinelai_dataset/")):
        issues.append((0, "private runtime data or dataset"))
    if b"\0" in content:
        return issues
    text = content.decode("utf-8-sig", errors="replace")
    for number, line in enumerate(text.splitlines(), 1):
        for rule, pattern in RULES.items():
            match = pattern.search(line)
            if match and not (rule == "credential assignment" and any(x in match.group(1).lower() for x in PLACEHOLDERS)):
                issues.append((number, rule))
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='Scan actual indexed blobs rather than working files')
    args = parser.parse_args(argv)
    command = ["git", "ls-files", "-z", "--cached"]
    if not args.staged:
        command.extend(["--others", "--exclude-standard"])
    raw = subprocess.check_output(command, cwd=ROOT)
    paths = sorted(set(p.decode("utf-8") for p in raw.split(b"\0") if p))
    failures = 0
    sizes = []
    for relative in paths:
        path = ROOT / relative
        if not args.staged and not path.is_file():
            continue  # A reviewed deletion may still be in the index.
        content = subprocess.check_output(["git", "show", ":" + relative], cwd=ROOT) if args.staged else path.read_bytes()
        size = len(content)
        sizes.append((size, relative))
        if size > 50 * 1024 * 1024:
            print(f"BLOCK {relative}: exceeds 50 MiB publication limit")
            failures += 1
            continue
        for line, rule in inspect_file(relative, content):
            print(f"REVIEW {relative}:{line}: {rule}")
            failures += 1
    print(f"Scanned {len(sizes)} tracked/unignored files locally; {failures} findings.")
    for size, path in sorted(sizes, reverse=True)[:5]:
        print(f"Largest: {path} ({size:,} bytes)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
