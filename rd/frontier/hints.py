"""Harvest Lean deprecation hints from compiler output and apply them to the compiled source.

Lean 4.36 prints, for a use of a deprecated name:

  FILE:L:C: warning: `Old.name` has been deprecated: Use `New.name` instead

  Hint: Replace the deprecated name:
    o̵l̵d̵n̲e̲w̲

The hint line spells the text as written in the source: a character followed by U+0335 is
deleted, one followed by U+0332 is inserted. When a hint is present it is applied verbatim at
(L, C); otherwise the replacement in the message ("Use `X`", "Prefer using `X`", "use `X`") is
applied to the identifier at (L, C). Deprecations with no named replacement are skipped.
"""
import re

STRIKE, UNDER = "̵", "̲"
WARN_RE = re.compile(r"^[^\n]*?:(\d+):(\d+): warning: `([^`]+)` has been deprecated([^\n]*)$", re.M)
USE_RE = re.compile(r"(?:[Uu]se|[Pp]refer using|[Ss]imply use) `([^`]+)`")
IDENT_AT = re.compile(r"[^\s()\[\]{},;:⟨⟩@]+")


def decode(diff):
    old, new, i = [], [], 0
    while i < len(diff):
        ch = diff[i]
        nxt = diff[i + 1] if i + 1 < len(diff) else ""
        if nxt == STRIKE:
            old.append(ch); i += 2
        elif nxt == UNDER:
            new.append(ch); i += 2
        else:
            old.append(ch); new.append(ch); i += 1
    return "".join(old), "".join(new)


def harvest(log):
    """Return a list of (line, col, old_text_or_None, new_text_or_None, deprecated, replacement)."""
    out = []
    for m in WARN_RE.finditer(log):
        line, col, dep, rest = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
        um = USE_RE.search(rest)
        repl = um.group(1) if um else None
        tail = log[m.end():m.end() + 2000]
        old = new = None
        hm = re.match(r"\n\nHint: Replace the deprecated name:\n  ([^\n]*)", tail)
        if hm:
            old, new = decode(hm.group(1))
        out.append((line, col, old, new, dep, repl))
    return out


def apply_hints(src, hints):
    """Apply harvested hints; returns (new_src, number_applied)."""
    lines = src.split("\n")
    edits = {}
    for line, col, old, new, dep, repl in hints:
        if not (1 <= line <= len(lines)):
            continue
        text = lines[line - 1]
        if old is not None and new is not None and old != new:
            if text[col:col + len(old)] == old:
                edits[(line, col)] = (len(old), new)
            continue
        if repl is None:
            continue
        m = IDENT_AT.match(text, col)
        if not m:
            continue
        written = m.group(0)
        if written == dep:
            edits[(line, col)] = (len(written), repl)
        elif dep.endswith("." + written):
            prefix = dep[:-len(written)]
            edits[(line, col)] = (len(written), repl[len(prefix):] if repl.startswith(prefix) else repl)
    n = 0
    for (line, col), (ln, new) in sorted(edits.items(), reverse=True):
        t = lines[line - 1]
        lines[line - 1] = t[:col] + new + t[col + ln:]
        n += 1
    return "\n".join(lines), n
