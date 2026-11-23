"""provgate.py — local Quality & Provenance Gate (home turf).

  python provgate.py lint [repo] [--range A..B] [--max N] [--json]
  python provgate.py residue [repo]
  python provgate.py check-message -F <file>      (commit-msg hook mode)

Trailer parsing uses `git interpret-trailers --parse` (canonical); schema and
residue rules live in schema.py (shared with glassbox_sweep.py).
Exit codes: 0 clean, 1 violations found, 2 usage/environment error.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schema  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CUTOFF = schema.CUTOFF_UTC


def run(args, cwd=None, stdin=None):
    p = subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def git(repo, *args, stdin=None):
    rc, out, err = run(["git", "-C", repo, *args], stdin=stdin)
    if rc != 0:
        raise RuntimeError(f"git {' '.join(args)}: {err.strip()[:200]}")
    return out


def interpret_trailers(repo, msg):
    """Canonical parse via git itself. Returns [(key, value)]."""
    rc, out, _ = run(["git", "interpret-trailers", "--parse"], cwd=repo, stdin=msg)
    pairs = []
    for ln in out.rstrip("\n").split("\n"):
        if ": " in ln:
            k, v = ln.split(": ", 1)
            pairs.append((k, v))
        elif ln.endswith(":"):
            pairs.append((ln[:-1], ""))
    return pairs


def load_commits(repo, rev_range, max_n):
    fmt = "%H%x1f%h%x1f%s%x1f%an%x1f%ae%x1f%cI%x1f%P%x1f%B%x1e"
    args = ["log", f"--pretty=format:{fmt}", f"--max-count={max_n}"]
    if rev_range:
        args.append(rev_range)
    raw = git(repo, *args)
    commits = []
    for rec in raw.split("\x1e"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        fields = rec.split("\x1f")
        if len(fields) < 8:
            continue
        full, short, subject, an, ae, cdate, parents, body = fields[:8]
        msg = f"{subject}\n\n{body}" if body else subject
        commits.append({"full": full, "short": short, "subject": subject.strip(),
                        "author_name": an, "author_email": ae, "committer_iso": cdate,
                        "parents": parents, "msg": msg})
    return commits


def cutoff_for(repo):
    """targets.json next to the script wins; CLI --since overrides upstream."""
    tpath = os.path.join(HERE, "targets.json")
    try:
        with open(tpath, encoding="utf-8") as f:
            return json.load(f).get("cutoff_utc", DEFAULT_CUTOFF)
    except Exception:
        return DEFAULT_CUTOFF


def cmd_lint(repo, rev_range, max_n, as_json, since):
    repo = os.path.abspath(repo)
    if not os.path.isdir(os.path.join(repo, ".git")) and \
       subprocess.run(["git", "-C", repo, "rev-parse", "--git-dir"],
                      capture_output=True).returncode != 0:
        print(f"not a git repo: {repo}", file=sys.stderr)
        return 2
    cutoff = since or cutoff_for(repo)
    violations, exempt, skipped, conformant, residue = [], [], {"merge_skipped": 0, "bot_skipped": 0, "legacy_skipped": 0}, [], []

    for c in load_commits(repo, rev_range, max_n):
        pairs = interpret_trailers(repo, c["msg"])
        v = schema.evaluate(c["short"], c["subject"], c["committer_iso"], c["parents"],
                            c["author_name"], c["author_email"], pairs, cutoff)
        if v["status"] == "violations":
            violations.append(v)
        elif v["status"] == "exempt":
            exempt.append(v)
        elif v["status"] == "conformant":
            conformant.append(v)
        else:
            skipped[v["status"]] += 1

    for path, pat in residue_hits(repo):
        residue.append({"path": path, "pattern": pat})

    report = {
        "schema_version": schema.SCHEMA_VERSION, "repo": repo, "cutoff": cutoff,
        "counts": {"conformant": len(conformant), "violations": len(violations),
                   "exempt": len(exempt), **skipped, "residue": len(residue)},
        "violations": violations, "exempt": exempt, "residue": residue,
    }
    if as_json:
        print(json.dumps(report, indent=1))
    else:
        for v in violations:
            print(f"VIOLATION {v['sha']} \"{v['subject'][:60]}\" :: " + "; ".join(v["reasons"]))
        for r in residue:
            print(f"RESIDUE   {r['path']} (matched {r['pattern']})")
        for e in exempt:
            print(f"exempt    {e['sha']} :: {e['reasons'][0]}")
        print(f"lint {os.path.basename(repo)}: conformant={len(conformant)} "
              f"violations={len(violations)} exempt={len(exempt)} "
              f"merge={skipped['merge_skipped']} bot={skipped['bot_skipped']} "
              f"legacy={skipped['legacy_skipped']} residue={len(residue)}")
    return 1 if (violations or residue) else 0


def residue_hits(repo):
    out = []
    raw = git(repo, "ls-files")
    for path in raw.splitlines():
        pat = schema.residue_hit(path)
        if pat:
            out.append((path, pat))
    return out


def cmd_residue(repo, as_json):
    repo = os.path.abspath(repo)
    hits = residue_hits(repo)
    if as_json:
        print(json.dumps([{"path": p, "pattern": pat} for p, pat in hits]))
    else:
        for p, pat in hits:
            print(f"RESIDUE {p} (matched {pat})")
        print(f"residue: {len(hits)} tracked file(s) in {os.path.basename(repo)}")
    return 1 if hits else 0


def cmd_check_message(path):
    if path == "-":
        msg = sys.stdin.read()
    else:
        with open(path, encoding="utf-8", errors="replace") as f:
            msg = f.read()
    subject = msg.split("\n", 1)[0].strip()
    pairs = interpret_trailers(".", msg)
    status, reasons = schema.check_trailers(pairs)
    if status == "violations":
        print(f"commit-msg REJECTED ({schema.SCHEMA_VERSION}): " + "; ".join(reasons),
              file=sys.stderr)
        print("  See TRAILER_SCHEMA.md; emergency skip: add trailer "
              "'Provenance-Exempt: <reason>'", file=sys.stderr)
        return 1
    print(f"commit-msg ok ({status})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    lp = sub.add_parser("lint")
    lp.add_argument("repo", nargs="?", default=".")
    lp.add_argument("--range", dest="rev_range", default=None, help="e.g. origin/main..HEAD")
    lp.add_argument("--max", type=int, default=50)
    lp.add_argument("--since", default=None, help="override cutoff ISO date")
    lp.add_argument("--json", action="store_true")
    rp = sub.add_parser("residue")
    rp.add_argument("repo", nargs="?", default=".")
    rp.add_argument("--json", action="store_true")
    cp = sub.add_parser("check-message")
    cp.add_argument("-F", "--file", default="-")
    a = ap.parse_args(argv)
    if a.cmd == "lint":
        return cmd_lint(a.repo, a.rev_range, a.max, a.json, a.since)
    if a.cmd == "residue":
        return cmd_residue(a.repo, a.json)
    return cmd_check_message(a.file)


if __name__ == "__main__":
    sys.exit(main())
