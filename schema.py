"""Canonical provenance-trailer schema — 2026-11-17.v1.

Single source of truth for both enforcement layers:
  provgate.py       (local, uses git interpret-trailers --parse for parity)
  glassbox_sweep.py (remote, anonymous API, pure-Python mirror parser)

tests/test_provgate.py cross-checks the two parsers on fixtures, so the
mirror cannot silently drift from git's own trailer semantics.
"""
import re

SCHEMA_VERSION = "2026-11-17.v1"
CUTOFF_UTC = "2026-11-17T00:00:00Z"

ROSTER = r"(Flux|Nimbus|Harley|Xixi|d3b0m3n|Farrow)"

# (key, value regex) — required exactly once each in the trailer block
REQUIRED = [
    ("Swarm-Card", re.compile(r"^t_[0-9a-f]{8}$")),
    ("Executed-By", re.compile(r"^" + ROSTER + r"\b.*$", re.DOTALL)),
    ("Adjudicated-By", re.compile(r"^(?:" + ROSTER + r"\b.*|pending)$", re.DOTALL)),
    ("Receipt-SHA256", re.compile(r"^[0-9a-f]{64}$")),
]
EXEMPT_KEY = "Provenance-Exempt"

_TRAILER_LINE = re.compile(r"^([A-Za-z0-9-]+):[ \t]*([^\n]*)$")


def parse_trailer_block(msg):
    """Mirror `git interpret-trailers --parse`: trailers are the FINAL paragraph
    of the message; every line must be a `Key: value` trailer or a whitespace
    continuation of the previous one. Returns list[(key, value)] or []."""
    lines = msg.rstrip("\n").rstrip("\r").split("\n")
    end = len(lines)
    while end > 0 and not lines[end - 1].strip():
        end -= 1
    if end == 0:
        return []
    start = end
    while start > 0 and lines[start - 1].strip():
        start -= 1
    out = []
    for ln in lines[start:end]:
        if ln[:1] in (" ", "\t") and out:          # continuation line
            out[-1] = (out[-1][0], out[-1][1] + " " + ln.strip())
            continue
        m = _TRAILER_LINE.match(ln)
        if m:
            out.append((m.group(1), m.group(2).rstrip()))
        else:
            return []                              # non-trailer line => no block
    return out


def check_class(sha, committer_iso, parents, author_name, author_email, cutoff_iso):
    """Skip classes evaluated before schema. Returns status or None (= must conform)."""
    if len([p for p in parents.split() if p]) > 1:
        return "merge_skipped"
    idblob = f"{author_name} {author_email}"
    if "[bot]" in idblob:
        return "bot_skipped"
    # ISO-8601 dates with fixed offsets: normalize to UTC for comparison
    if _to_utc(committer_iso) < _to_utc(cutoff_iso):
        return "legacy_skipped"
    return None


def _to_utc(iso):
    iso = iso.strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$", iso)
    if not m:
        raise ValueError(f"unparseable ISO date: {iso!r}")
    from datetime import datetime, timedelta, timezone
    dt = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
    off = m.group(2) or "Z"
    if off == "Z":
        delta = timedelta(0)
    else:
        sign = 1 if off[0] == "+" else -1
        digits = off[1:].replace(":", "")          # "+05:45"/"+0545" -> "0545"
        delta = sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4] or 0))
    return dt.replace(tzinfo=timezone.utc) - delta


def check_trailers(pairs):
    """Schema-check a parsed [(key, value)] block.
    Returns (status, reasons): status in {"conformant","exempt","violations"}."""
    keys = [k for k, _ in pairs]
    if EXEMPT_KEY in keys:
        val = dict(pairs)[EXEMPT_KEY].strip()
        if val:
            return "exempt", [f"Provenance-Exempt: {val}"]
        return "violations", ["Provenance-Exempt present but reason is empty"]
    reasons = []
    d = dict(pairs)
    for key, rx in REQUIRED:
        n = keys.count(key)
        if n == 0:
            reasons.append(f"missing {key}")
            continue
        if n > 1:
            reasons.append(f"duplicate {key} (x{n})")
        v = d[key].strip()
        if not rx.match(v):
            reasons.append(f"bad {key}: {v[:40]!r}")
    return ("conformant", []) if not reasons else ("violations", reasons)


def evaluate(sha, subject, committer_iso, parents, author_name, author_email,
             pairs, cutoff_iso=CUTOFF_UTC):
    """Full verdict for one commit. Returns dict."""
    skip = check_class(sha, committer_iso, parents, author_name, author_email, cutoff_iso)
    if skip:
        return {"sha": sha, "subject": subject, "status": skip, "reasons": []}
    status, reasons = check_trailers(pairs)
    return {"sha": sha, "subject": subject, "status": status, "reasons": reasons}


# ---------------- residue blocklist ----------------

# fnmatch patterns against the full lowercased repo-relative path
RESIDUE_GLOBS = [
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*",
    "*secret*", "*credential*", "*apikey*", "*api-key*", "*api_key*",
    "*mnemonic*", "*seedphrase*", "*.kdbx", "*.sqlite", "*.sqlite3",
    "state.db", "kanban.db", "*.pyc", "*.pyo", ".ds_store", "thumbs.db", "*.log",
]
# exact single-path-segment matches (artifact dirs)
RESIDUE_SEGMENTS = {
    "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    "out", "cache", "target", ".next", ".foundry",
}
_RESIDUE_ALLOW = {".env.example", ".env.sample", "build/README.md"}  # full-path exact allows


def _import_fnm():
    from fnmatch import fnmatch
    return fnmatch


def residue_hit(path):
    """Return matched pattern if tracked path is residue, else None. Path-level only."""
    p = path.lower().replace("\\", "/")
    if p in _RESIDUE_ALLOW:
        return None
    fnmatch = _import_fnm()
    segs = p.split("/")
    for pat in RESIDUE_GLOBS:
        if fnmatch(p, pat) or any(fnmatch(s, pat) for s in segs[-1:]):
            return pat
    for s in segs[:-1]:
        if s in RESIDUE_SEGMENTS:
            return f"{s}/"
    return None
