"""Anonymize the replication artifact: rewrite identifying paths/names to placeholders.

Dry-run by default; pass --apply to write. Text files only (binaries reported, not touched).
Handles gzip members by decompressing, scrubbing, and recompressing.
"""
from __future__ import annotations

import argparse
import gzip
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Longest-first so specific paths win over the generic tail.
RULES: list[tuple[str, str]] = [
    (r"C:\Users\11428\Desktop\testvdb_paper", "<ARTIFACT_ROOT>"),
    ("C:/Users/11428/Desktop/testvdb_paper", "<ARTIFACT_ROOT>"),
    (r"C:\Users\11428\Desktop\mftui\TestVDB", "<PIPELINE_SOURCE>"),
    ("C:/Users/11428/Desktop/mftui/TestVDB", "<PIPELINE_SOURCE>"),
    (r"C:\Users\11428\Desktop\testvdb4exp", "<PIPELINE_SOURCE>"),
    ("C:/Users/11428/Desktop/testvdb4exp", "<PIPELINE_SOURCE>"),
    (r"C:\Users\11428\Desktop\tvdb_sessions", "<INTEL_ROOT>"),
    ("C:/Users/11428/Desktop/tvdb_sessions", "<INTEL_ROOT>"),
    (r"C:\Users\11428\Desktop\VDBFuzz", "<BASELINE_ROOT>"),
    ("C:/Users/11428/Desktop/VDBFuzz", "<BASELINE_ROOT>"),
    (r"C:\Users\11428\Desktop", "<DESKTOP>"),
    ("C:/Users/11428/Desktop", "<DESKTOP>"),
    (r"C:\Users\11428", "<HOME>"),
    ("C:/Users/11428", "<HOME>"),
    (r"Users\11428", "<HOME>"),
    ("Users/11428", "<HOME>"),
    ("yihui504/TestVDB_artifact", "TestVDB-artifact"),
    ("yihui504/TestVDB", "TestVDB"),
    ("yihui504/testvdb_paper", "TestVDB-paper"),
    ("yihui504/testvdb4exp", "TestVDB-pipeline"),
    ("github.com/yihui504/", "github.com/"),
    ("gitee.com/RelSys/testvdb_paper", "<ARTIFACT_REPO>"),
    ("gitee.com/tcse-intern/TestVDB", "<PIPELINE_REPO>"),
    ("testvdb4exp", "pipeline"),
    ("tvdb_sessions", "intel-sessions"),
    ("mftui", "pipelinehost"),
    ("11428", "<user>"),
    # GitHub account used by the authors to file the upstream issues; it appears
    # verbatim in the raw issue JSON captured from the GitHub API.
    ("yihui504-vdbms-issues.csv", "vdbms-issues.csv"),
    ("yihui504-TestVDB", "TestVDB-pipeline"),
    ("yihui504", "<submitter>"),
    # Bare (drive-less) path tails: the rules above consume the "C:/Users/11428/Desktop"
    # prefix, leaving these fragments behind in otherwise-scrubbed strings.
    (r"Desktop\testvdb_paper", r"<ARTIFACT_ROOT>"),
    ("Desktop/testvdb_paper", "<ARTIFACT_ROOT>"),
    (r"Desktop\mftui\TestVDB", "<PIPELINE_SOURCE>"),
    ("Desktop/mftui/TestVDB", "<PIPELINE_SOURCE>"),
    (r"Desktop\testvdb4exp", "<PIPELINE_SOURCE>"),
    ("Desktop/testvdb4exp", "<PIPELINE_SOURCE>"),
    (r"Desktop\tvdb_sessions", "<INTEL_ROOT>"),
    ("Desktop/tvdb_sessions", "<INTEL_ROOT>"),
    (r"Desktop\VDBFuzz", "<BASELINE_ROOT>"),
    ("Desktop/VDBFuzz", "<BASELINE_ROOT>"),
    (r"Desktop\pipeline", r"<PIPELINE_SOURCE>"),
    ("Desktop/pipeline", "<PIPELINE_SOURCE>"),
    (r"Desktop)", "<DESKTOP>)"),
]

BINARY_EXT = {".gz", ".xlsx", ".pdf", ".png", ".jpg", ".jpeg", ".zip", ".ico", ".woff", ".ttf"}


def scrub_text(text: str) -> tuple[str, int]:
    hits = 0
    for old, new in RULES:
        n = text.count(old)
        if n:
            hits += n
            text = text.replace(old, new)
        # Drive-letter paths appear with either case in the captured logs and
        # scripts (c:\ and C:\). Re-apply path-shaped rules case-insensitively
        # so the lowercase variant is not skipped.
        if len(old) > 3 and ("\\" in old or "/" in old):
            lo = old.lower()
            if lo != old:
                m = text.lower().count(lo)
                if m:
                    hits += m
                    idx = 0
                    out = []
                    low = text.lower()
                    while True:
                        j = low.find(lo, idx)
                        if j < 0:
                            out.append(text[idx:])
                            break
                        out.append(text[idx:j])
                        out.append(new)
                        idx = j + len(old)
                    text = "".join(out)
    return text, hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    text_files = gz_files = binary_files = 0
    total_hits = 0
    unchanged = 0

    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if path.name == Path(__file__).name:
            continue

        if path.suffix in BINARY_EXT:
            if path.suffix == ".gz":
                try:
                    raw = gzip.decompress(path.read_bytes())
                except Exception:
                    binary_files += 1
                    continue
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    binary_files += 1
                    continue
                new_text, hits = scrub_text(text)
                if hits:
                    total_hits += hits
                    gz_files += 1
                    if args.apply:
                        buf = io.BytesIO()
                        with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
                            gz.write(new_text.encode("utf-8"))
                        path.write_bytes(buf.getvalue())
                else:
                    unchanged += 1
            else:
                binary_files += 1
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            binary_files += 1
            continue

        new_text, hits = scrub_text(text)
        if hits:
            total_hits += hits
            text_files += 1
            if args.apply:
                path.write_text(new_text, encoding="utf-8")
        else:
            unchanged += 1

    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"[{mode}] text files rewritten: {text_files} | gz members rewritten: {gz_files}")
    print(f"           unchanged: {unchanged} | binary/skipped: {binary_files}")
    print(f"           total replacements: {total_hits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
