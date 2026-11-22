"""Shared loaders for the mechanical-fixer experiment.

Inputs (all read-only):
  UP      an extracted `git archive origin/main port tracker` of the upstream replay repo
  ADDLOG  output of `git log origin/main --diff-filter=A --name-only --format=COMMIT_%H_%ct -- port/patches/`
  SRC     pinned source trees, tried in order; a file is used only if its SHA-256 matches
          tracker/modules.jsonl.gz
"""
import gzip, hashlib, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
UP = os.environ.get("FIXER_UP", os.path.join(HERE, "cache", "up"))
ADDLOG = os.environ.get("FIXER_ADDLOG", os.path.join(HERE, "cache", "addlog.txt"))
SRC = os.environ.get("FIXER_SRC", "").split(os.pathsep) if os.environ.get("FIXER_SRC") else []


def load_modules():
    out = {}
    with gzip.open(os.path.join(UP, "tracker", "modules.jsonl.gz"), "rt") as f:
        for line in f:
            r = json.loads(line)
            out[r["id"]] = r
    return out


def load_merge_times(ext=".patch"):
    """id -> (unix time, commit) of the earliest commit that added port/patches/<id><ext>.

    Earliest, not latest: origin/main contains a second root commit (a full-tree snapshot dated
    after most merges) that "adds" ~1,000 patches again; the latest add would collapse the order."""
    t = {}
    cur = None
    with open(ADDLOG) as f:
        for line in f:
            line = line.strip()
            if line.startswith("COMMIT_"):
                _, h, ts = line.split("_")
                cur = (int(ts), h)
            elif line.endswith(ext):
                mid = os.path.basename(line)[:-len(ext)]
                if mid not in t or cur[0] < t[mid][0]:
                    t[mid] = cur
    return t


def patch_ids():
    d = os.path.join(UP, "port", "patches")
    return sorted(n[:-6] for n in os.listdir(d) if n.endswith(".patch"))


def read_patch(mid):
    with open(os.path.join(UP, "port", "patches", mid + ".patch"), encoding="utf-8") as f:
        return f.read()


def read_record(mid):
    p = os.path.join(UP, "port", "patches", mid + ".json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def unchanged_ids():
    d = os.path.join(UP, "port", "patches")
    out = []
    for n in os.listdir(d):
        if n.endswith(".json") and not os.path.exists(os.path.join(d, n[:-5] + ".patch")):
            r = read_record(n[:-5])
            if r and r.get("notes") == "unchanged":
                out.append(n[:-5])
    return sorted(out)


def pinned_source(mod):
    """Return pinned source text for module record, or None if no tree has a hash-matching copy."""
    rel = mod["module"].replace(".", "/") + ".lean"
    for root in SRC:
        p = os.path.join(root, rel)
        if os.path.exists(p):
            b = open(p, "rb").read()
            if hashlib.sha256(b).hexdigest() == mod["source_sha256"]:
                return b.decode("utf-8")
    return None


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_patch(text):
    """Return list of hunks: dict(old_start, lines=[(tag, text)]) with tag in ' -+'."""
    hunks = []
    cur = None
    for line in text.split("\n"):
        if line.startswith("--- ") or line.startswith("+++ "):
            if cur is None or not cur["lines"] or line.startswith("--- "):
                continue
        m = HUNK_RE.match(line)
        if m:
            cur = {"old_start": int(m.group(1)), "lines": []}
            hunks.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("\\"):
            continue
        if line == "":
            # trailing split artefact or genuine empty context line w/o leading space
            cur["lines"].append((" ", ""))
            continue
        tag, body = line[0], line[1:]
        if tag in " -+":
            cur["lines"].append((tag, body))
    # strip artefactual trailing empty context lines beyond declared hunk length
    for h in hunks:
        while h["lines"] and h["lines"][-1] == (" ", ""):
            h["lines"].pop()
    return hunks


def apply_patch(src, hunks):
    """Strict application. Returns patched text or None if context does not match."""
    lines = src.split("\n")
    out = []
    pos = 0  # 0-based index into lines
    for h in hunks:
        start = h["old_start"] - 1 if h["old_start"] > 0 else 0
        # pure-insert hunks with old count 0 use start = old_start (insert after)
        old = [b for t, b in h["lines"] if t in " -"]
        new = [b for t, b in h["lines"] if t in " +"]
        if not old:
            start = h["old_start"]
        if lines[start:start + len(old)] != old:
            # allow trailing context that was eaten as empty
            return None
        out.extend(lines[pos:start])
        out.extend(new)
        pos = start + len(old)
    out.extend(lines[pos:])
    return "\n".join(out)


def change_blocks(hunks):
    """Yield (old_lineno_start, removed_lines, added_lines) for each contiguous -/+ block."""
    for h in hunks:
        ln = h["old_start"]
        rem, add, bstart = [], [], None
        for t, b in h["lines"] + [(" ", None)]:
            if t == " ":
                if rem or add:
                    yield (bstart, rem, add)
                rem, add, bstart = [], [], None
                ln += 1
            elif t == "-":
                if bstart is None:
                    bstart = ln
                rem.append(b)
                ln += 1
            else:
                if bstart is None:
                    bstart = ln
                add.append(b)


# Lean-ish tokenizer: identifiers (with dots, unicode letters, subscripts, ', !, ?), numbers,
# whitespace, and single other characters.
IDENT = r"(?:«[^»]*»|[A-Za-z_À-ɏͰ-Ͽᴀ-ᶿἀ-῿℀-⅏\U0001D400-\U0001D7FF][A-Za-z0-9_'!?À-ɏͰ-Ͽᴀ-ᶿἀ-῿₀-ₜ℀-⅏\U0001D400-\U0001D7FF]*)"
QIDENT = IDENT + r"(?:\." + IDENT + r")*"
TOK_RE = re.compile(r"(" + QIDENT + r")|(\d+)|(\s+)|(.)", re.S)
IDENT_FULL_RE = re.compile("^" + QIDENT + "$")
# characters that continue an identifier: word-boundary guard for substitutions
CONT = r"A-Za-z0-9_'!?.À-ɏͰ-Ͽᴀ-ᶿἀ-῿₀-ₜ℀-⅏\U0001D400-\U0001D7FF"


def tokens(s):
    return [m.group(0) for m in TOK_RE.finditer(s)]


def is_ident(t):
    return bool(IDENT_FULL_RE.match(t))


def ident_re(tok):
    """Regex matching tok as a whole identifier (not part of a longer dotted name)."""
    return re.compile(r"(?<![" + CONT + r"])" + re.escape(tok) + r"(?![" + CONT + r"])")


def strip_comments(s):
    """Rough removal of Lean comments for counting occurrences (line and block, non-nested ok)."""
    s = re.sub(r"/-.*?-/", " ", s, flags=re.S)
    s = re.sub(r"--[^\n]*", " ", s)
    return s
