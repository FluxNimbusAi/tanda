#!/usr/bin/env python3
"""Provenance CI gate for FluxNimbusAi/tanda.

Flux ruling 2026-11-22 (board cards t_flux_c4 draft -> t_flux_c2 hardening):

  1. WORKTREE GUARD — reject any commit whose diff touches paths under a
     `.worktrees/` directory (repo root or nested, mirroring
     tools/git-hooks/precommit-worktree-guard.sh) unless that SAME commit
     carries a non-empty `Provenance-Exempt: <reason>` trailer.
     Belt-and-braces: the checked-out tree itself must not track any
     `.worktrees/` path unless the tip commit carries the exemption
     (6955f050 class: dirty-worktree `git add -A` sweeps).
  2. HOOK-BYPASS DISCLOSURE — flag any commit whose message mentions
     `no-verify` (case-insensitive, covers `--no-verify`) without a
     non-empty `Provenance-Exempt:` trailer IN THE SAME MESSAGE.

Hardening over the d6d13cf6 draft (all four gaps regression-tested by
--self-test):
  * draft scanned `git log -n 20` from a default depth-1 checkout, i.e.
    exactly one commit, and re-scanned stale history on main pushes;
    this gate scans the EXACT event range (base..head) with a safe
    tip-only fallback.
  * draft greps ran over concatenated messages, so commit A's
    Provenance-Exempt trailer laundered commit B's undisclosed
    `--no-verify`; this gate pairs trailer against message per commit.
  * draft's worktree leg never honoured the exemption trailer at all.

Exit codes: 0 = clean, 1 = violations (leg fails), 2 = operational error.
Stdlib only; needs `git` on PATH. CI wiring: .github/workflows/ci.yml
(provenance job, fetch-depth: 0).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

WORKTREE_PATH_RE = re.compile(r"(^|/)\.worktrees(/|$)")
# Non-empty reason after the colon; matches anywhere in the message so a
# multi-paragraph body cannot hide an absent trailer, and an empty
# `Provenance-Exempt:` does NOT exempt (provgate schema 2026-11-17.v1).
EXEMPT_RE = re.compile(r"^Provenance-Exempt:[ \t]*\S", re.MULTILINE)
NO_VERIFY_RE = re.compile(r"no-verify", re.IGNORECASE)

ZERO_SHA_RE = re.compile(r"^0+$")  # all-zero (new branch) event bases


class OpError(Exception):
    """Operational failure (git missing, bad range) -> exit 2, never fail-open silently."""


def git(repo: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        p = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:  # pragma: no cover - git missing
        raise OpError("git executable not found on PATH") from exc
    if check and p.returncode != 0:
        raise OpError(
            f"git {' '.join(args)} -> rc={p.returncode}: {p.stderr.strip()}"
        )
    return p


def commit_message(repo: str, sha: str) -> str:
    return git(repo, "log", "-1", "--format=%B", sha).stdout


def changed_paths(repo: str, sha: str) -> list[str]:
    """Paths touched by one commit. Merges: only evil-merge changes (-c);
    root commit handled by --root. Clean merges therefore yield no paths."""
    out = git(
        repo, "diff-tree", "-r", "--no-commit-id", "--name-only", "-c", "--root", sha
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def resolve_rev_args(repo: str, revs: str | None, base: str | None,
                     head: str | None) -> tuple[list[str], str]:
    """Return (rev-list args, human description). Fallback chain:
    explicit --revs > $GATE_BASE..$GATE_HEAD (validated) > tip only."""
    head = head or "HEAD"
    if revs:
        return [revs], f"explicit range {revs}"
    base_s = base or ""
    valid_base = bool(
        base_s
        and not ZERO_SHA_RE.match(base_s)
        and git(repo, "cat-file", "-e", f"{base_s}^{{commit}}", check=False).returncode == 0
        and git(repo, "merge-base", "--is-ancestor", base_s, head, check=False).returncode == 0
    )
    if valid_base:
        return [f"{base_s}..{head}"], f"event range {base_s[:10]}..{head[:10]}"
    if base_s:
        return ["-n", "1", head], (
            f"TIP ONLY (fallback: base {base_s[:10]} missing/unreachable — "
            "new branch, force-push, or shallow checkout)"
        )
    return ["-n", "1", head], "TIP ONLY (no base provided)"


def scan(repo: str, rev_args: list[str]) -> tuple[list[str], list[str], int]:
    """Scan one commit range. Returns (errors, notes, commits_scanned)."""
    errors: list[str] = []
    notes: list[str] = []
    # Tree invariant is evaluated at the checked-out tip (that is exactly what
    # CI hands us: the push head, or the PR merge/head ref).
    tip = git(repo, "rev-parse", "HEAD").stdout.strip()
    tip_msg = commit_message(repo, tip)

    shas = [s for s in git(repo, "rev-list", *rev_args).stdout.split() if s]
    for sha in reversed(shas):  # oldest first: deterministic, readable output
        msg = commit_message(repo, sha)
        exempt = bool(EXEMPT_RE.search(msg))
        paths = changed_paths(repo, sha)
        wt_hits = [p for p in paths if WORKTREE_PATH_RE.search(p)]
        short = sha[:10]
        subject = msg.splitlines()[0][:72] if msg.strip() else "(empty message)"

        if wt_hits and not exempt:
            errors.append(
                f"{short} WORKTREE-STAGED: {len(wt_hits)} path(s) under .worktrees/ "
                f"({', '.join(wt_hits[:5])}{' …' if len(wt_hits) > 5 else ''}) "
                f"without a non-empty Provenance-Exempt trailer — commit from the "
                f"main checkout only (6955f050 class). Subject: {subject!r}"
            )
        elif wt_hits and exempt:
            notes.append(
                f"{short} exempted worktree paths ({len(wt_hits)}): visible "
                f"Provenance-Exempt trailer honoured"
            )

        if NO_VERIFY_RE.search(msg) and not exempt:
            errors.append(
                f"{short} UNDISCLOSED-HOOK-BYPASS: message mentions --no-verify but "
                f"this same commit lacks a non-empty Provenance-Exempt trailer — "
                f"disclose why the hook was bypassed. Subject: {subject!r}"
            )
        elif NO_VERIFY_RE.search(msg) and exempt:
            notes.append(
                f"{short} disclosed hook-bypass mention (Provenance-Exempt present)"
            )

    # Tree invariant: whatever the window, HEAD must not track .worktrees/
    # paths unless the tip commit itself carries the exemption trailer.
    tracked = git(repo, "ls-tree", "-r", "--name-only", tip or "HEAD").stdout.splitlines()
    tree_wt = [p for p in tracked if WORKTREE_PATH_RE.search(p)]
    if tree_wt and not EXEMPT_RE.search(tip_msg):
        errors.append(
            f"HEAD TREE tracks {len(tree_wt)} .worktrees/ path(s) "
            f"({', '.join(tree_wt[:5])}{' …' if len(tree_wt) > 5 else ''}) and the tip "
            f"commit carries no Provenance-Exempt trailer. Remove them via a "
            f"`git rm -r --cached` cleanup commit that discloses via trailer."
        )
    return errors, notes, len(shas)


def emit(errors: list[str], notes: list[str], window: str, scanned: int) -> None:
    for e in errors:
        print(f"::error title=provenance-gate::{e}")
    for n in notes:
        print(f"::notice title=provenance-gate::{n}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write("## Provenance gate\n\n")
                fh.write(f"Window: `{window}` — {scanned} commit(s) scanned.\n\n")
                for e in errors:
                    fh.write(f"- ❌ {e}\n")
                for n in notes:
                    fh.write(f"- ℹ️ {n}\n")
                if not errors and not notes:
                    fh.write("- ✅ no violations\n")
        except OSError:
            pass
    if not errors:
        print(f"PROVENANCE-GATE PASS: {window} — {scanned} commit(s) scanned, "
              f"{len(notes)} disclosure note(s), 0 violation(s).")
    else:
        print(f"PROVENANCE-GATE FAIL: {len(errors)} violation(s) in {window}.")


# --------------------------------------------------------------------------
# Self-test golden matrix (also run by tests/test_provenance_gate.py)
# --------------------------------------------------------------------------

def _mkrepo(tmp: str) -> str:
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "gate-selftest")
    git(repo, "config", "user.email", "gate-selftest@example.invalid")
    return repo


def _commit(repo: str, spec: tuple[str, str], msg: str) -> str:
    """spec = ('add'|'rm', path). 'rm' untracks the path (git rm -r --cached)."""
    op, path = spec
    if op == "add":
        full = os.path.join(repo, *path.split("/"))
        os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("x\n")
        git(repo, "add", "--", path)
    elif op == "rm":
        git(repo, "rm", "-r", "-q", "--cached", "--", path)
    else:  # pragma: no cover
        raise ValueError(f"unknown op {op!r}")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def self_test() -> int:
    # (name, [(op, path) + message], expected error count, expected fragment)
    checks = []

    def run(name, commits, expect_errs, expect_frag=""):
        checks.append((name, commits, expect_errs, expect_frag))

    run("clean history passes",
        [(("add", "src/a.py"), "feat: normal change")], 0)
    run("worktree path without trailer rejected (commit + tree both fire)",
        [(("add", "src/a.py"), "feat: base"),
         (("add", ".worktrees/wt/leak.txt"), "chore: sweep")], 2, "WORKTREE-STAGED")
    run("nested .worktrees rejected (commit + tree both fire)",
        [(("add", "src/a.py"), "feat: base"),
         (("add", "sub/.worktrees/wt/leak.txt"), "chore: sweep")], 2, "WORKTREE-STAGED")
    run("worktree path WITH reason exempted (tip carries the exemption)",
        [(("add", "src/a.py"), "feat: base"),
         (("add", ".worktrees/wt/leak.txt"),
          "chore: intentional\n\nProvenance-Exempt: auditable exception")], 0)
    run("--no-verify mention without trailer flagged",
        [(("add", "src/a.py"), "fix: typo (--no-verify to escape broken hook)")], 1,
        "UNDISCLOSED-HOOK-BYPASS")
    run("--no-verify mention WITH trailer passes",
        [(("add", "src/a.py"),
          "fix: typo (--no-verify to escape broken hook)\n\n"
          "Provenance-Exempt: hook crash class b7e6fb4, disclosed")], 0)
    run("no cross-commit laundering (A undisclosed, B exempt)",
        [(("add", "src/a.py"), "fix: bypass with --no-verify"),
         (("add", "src/b.py"), "docs: cleanup\n\nProvenance-Exempt: unrelated reason")],
        1, "UNDISCLOSED-HOOK-BYPASS")
    run("empty-reason exemption does NOT exempt",
        [(("add", "src/a.py"), "fix: bypass with --no-verify\n\nProvenance-Exempt:")], 1)
    run("tree scar: worktree file survives into later clean tip -> tree error",
        [(("add", "src/a.py"), "feat: base"),
         (("add", ".worktrees/wt/leak.txt"),
          "chore: exempted add\n\nProvenance-Exempt: visible exemption"),
         (("add", "src/b.py"), "feat: later clean commit")], 1, "HEAD TREE tracks")
    run("tree scar removed by disclosed cleanup commit",
        [(("add", "src/a.py"), "feat: base"),
         (("add", ".worktrees/wt/leak.txt"),
          "chore: exempted add\n\nProvenance-Exempt: visible exemption"),
         (("rm", ".worktrees"),
          "fix: drop worktree litter\n\nProvenance-Exempt: scar cleanup")], 0)

    failed = 0
    tmp = tempfile.mkdtemp(prefix="provgate-selftest-")
    try:
        for name, commits, expect_errs, frag in checks:
            repo = _mkrepo(tempfile.mkdtemp(dir=tmp))
            for spec, msg in commits:
                _commit(repo, spec, msg)
            errors, _notes, n = scan(repo, ["HEAD"])
            ok = len(errors) == expect_errs and (not frag or frag in " ".join(errors))
            print(f"{'PASS' if ok else 'FAIL'}: {name} "
                  f"({len(errors)} error(s), expected {expect_errs}, scanned {n})")
            if not ok:
                failed += 1
                for e in errors:
                    print(f"    got: {e}")

        # Range resolution: pure-logic fallback chain in one scratch repo.
        repo = _mkrepo(tempfile.mkdtemp(dir=tmp))
        _commit(repo, ("add", "src/a.py"), "feat: one")
        _commit(repo, ("add", "src/b.py"), "feat: two")
        args, window = resolve_rev_args(repo, None, None, "HEAD")
        ok1 = args == ["-n", "1", "HEAD"]
        args, _w = resolve_rev_args(repo, "HEAD~1..HEAD", None, None)
        ok2 = args == ["HEAD~1..HEAD"]
        args, window = resolve_rev_args(repo, None, "0" * 40, "HEAD")
        ok3 = window.startswith("TIP ONLY")
        dead = "d" * 40
        args, window = resolve_rev_args(repo, None, dead, "HEAD")
        ok4 = window.startswith("TIP ONLY")
        real = git(repo, "rev-parse", "HEAD~1").stdout.strip()
        args, window = resolve_rev_args(repo, None, real, "HEAD")
        ok5 = args == [f"{real}..HEAD"] and window.startswith("event range")
        range_ok = all([ok1, ok2, ok3, ok4, ok5])
        print(f"{'PASS' if range_ok else 'FAIL'}: "
              f"range resolution fallback chain (no-base/--revs/zero/dead/valid)")
        if not range_ok:
            failed += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"SELF-TEST {'FAIL' if failed else 'OK'}: {failed} case(s) failed")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="git repo to scan (default: cwd)")
    ap.add_argument("--revs", default=None,
                    help="explicit rev-list range (overrides GATE_BASE/GATE_HEAD)")
    ap.add_argument("--self-test", action="store_true", help="run golden matrix")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if git(args.repo, "rev-parse", "--git-dir", check=False).returncode != 0:
        print(f"::error title=provenance-gate::{args.repo} is not a git repository")
        return 2

    try:
        rev_args, window = resolve_rev_args(
            args.repo, args.revs,
            os.environ.get("GATE_BASE") or None,
            os.environ.get("GATE_HEAD") or None,
        )
        errors, notes, scanned = scan(args.repo, rev_args)
    except OpError as exc:
        print(f"::error title=provenance-gate::operational error: {exc}")
        return 2

    emit(errors, notes, window, scanned)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
