#!/usr/bin/env python3
"""Build-gated fixer experiment on ready-but-unported modules.

Stages (each resumable; results appended to OUT/results/<stage>.jsonl):
  prepare  put every module of the import closure in its merged state (patched or pinned) and
           every target in its pinned state, in TREE/src (hash-verified)
  closure  compile the import closure (recorded modules), depth by depth
  base     compile every target unchanged
  A        failing targets: fixer rule table (rd/fixer/fix.py logic), rebuild
  B        failing targets: apply Lean's deprecation hints from the base log, rebuild
  C        failing targets: A, then hints harvested from A's log, rebuild
  restore  put target sources back to pinned

Lean is invoked directly, the way Lake does (`lean --tstack=400000 FILE -o OLEAN -i ILEAN -c C
--setup SETUP`), with a fixed pool of at most JOBS processes, so the process count is exact.

  python3 -I run.py --tree TREE --out OUT --src PINNED_SRC [--jobs 6] STAGE [STAGE...]
Environment: FIXER_UP (upstream snapshot, default rd/fixer/cache/up), LEAN (lean binary),
LEAN_PATH (from `lake env printenv LEAN_PATH` in TREE).
"""
import argparse, collections, concurrent.futures as cf, hashlib, json, os, random, re, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "fixer"))
sys.path.insert(0, HERE)
os.environ.setdefault("FIXER_UP", os.path.join(HERE, "..", "fixer", "cache", "up"))
from common import load_modules, parse_patch, apply_patch, UP  # noqa
from mine import select  # noqa
from backtest import apply_all  # noqa
from hints import harvest, apply_hints  # noqa

OPTIONS = {"relaxedAutoImplicit": False, "pp.unicode.fun": True, "maxSynthPendingDepth": 3,
           "maxHeartbeats": 4000000, "autoImplicit": False}
TIMEOUT = int(os.environ.get("FRONTIER_TIMEOUT", "900"))
# Lean 4.36 tags some errors: `FILE:L:C: error(lean.unknownIdentifier): ...`
ERR_RE = re.compile(r"^[^\n]*?:\d+:\d+: error(?:\([^)]*\))?: ?(.*)$", re.M)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def rel(mod):
    return mod["module"].replace(".", "/") + ".lean"


class Ctx:
    def __init__(self, a):
        self.a = a
        self.tree = os.path.abspath(a.tree)
        self.out = os.path.abspath(a.out)
        self.mods = load_modules()
        pdir = os.path.join(UP, "port", "patches")
        self.records = {n[:-5] for n in os.listdir(pdir) if n.endswith(".json")}
        self.patches = {n[:-6] for n in os.listdir(pdir) if n.endswith(".patch")}
        pruned = set(open(os.path.join(UP, "port", "pruned.txt")).read().split())
        self.targets = sorted(m for m, r in self.mods.items()
                              if m not in self.records and m not in pruned
                              and all(i in self.records for i in r["imports"]))
        seen, st = set(), [i for m in self.targets for i in self.mods[m]["imports"]]
        while st:
            i = st.pop()
            if i not in seen:
                seen.add(i)
                st.extend(self.mods[i]["imports"])
        self.closure = sorted(seen)
        if a.sample:
            rnd = random.Random(a.seed)
            by = collections.defaultdict(list)
            for m in self.targets:
                by[self.mods[m]["depth"]].append(m)
            pick = []
            for d, xs in by.items():
                k = max(1, round(len(xs) * a.sample / len(self.targets)))
                pick += rnd.sample(xs, min(k, len(xs)))
            self.targets = sorted(pick)
        os.makedirs(os.path.join(self.out, "results"), exist_ok=True)
        os.makedirs(os.path.join(self.out, "setup"), exist_ok=True)
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- sources
    def pinned(self, m):
        p = os.path.join(self.a.src, rel(self.mods[m]))
        b = open(p, "rb").read()
        if sha(b) != self.mods[m]["source_sha256"]:
            raise SystemExit(f"pinned source hash mismatch for {m} in {self.a.src}")
        return b.decode("utf-8")

    def merged(self, m):
        s = self.pinned(m)
        if m in self.patches:
            p = apply_patch(s, parse_patch(open(os.path.join(UP, "port", "patches", m + ".patch"),
                                                encoding="utf-8").read()))
            if p is None:
                raise SystemExit(f"patch for {m} does not apply")
            return p
        return s

    def put(self, m, text):
        p = os.path.join(self.tree, "src", rel(self.mods[m]))
        try:
            if open(p, encoding="utf-8").read() == text:
                return False
        except FileNotFoundError:
            pass
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return True

    # ---------------------------------------------------------------- results
    def done(self, stage):
        p = os.path.join(self.out, "results", stage + ".jsonl")
        if not os.path.exists(p):
            return {}
        return {r["id"]: r for r in map(json.loads, open(p))}

    def record(self, stage, row):
        with self.lock:
            with open(os.path.join(self.out, "results", stage + ".jsonl"), "a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ---------------------------------------------------------------- compile
    def compile(self, m, stage):
        mod = self.mods[m]
        r = rel(mod)
        base = r[:-5]
        lib = os.path.join(self.tree, ".lake", "build", "lib", "lean")
        ir = os.path.join(self.tree, ".lake", "build", "ir")
        os.makedirs(os.path.dirname(os.path.join(lib, base)), exist_ok=True)
        os.makedirs(os.path.dirname(os.path.join(ir, base)), exist_ok=True)
        setup = os.path.join(self.out, "setup", m + ".json")
        if not os.path.exists(setup):
            json.dump({"plugins": [], "package": "tree", "options": OPTIONS, "name": mod["module"],
                       "isModule": False, "importArts": {}, "dynlibs": []}, open(setup, "w"))
        cmd = [os.environ["LEAN"], "--tstack=400000", os.path.join(self.tree, "src", r),
               "-o", os.path.join(lib, base + ".olean"), "-i", os.path.join(lib, base + ".ilean"),
               "-c", os.path.join(ir, base + ".c"), "--setup", setup]
        self.wait_load()
        t0 = time.monotonic()
        try:
            p = subprocess.run(cmd, cwd=self.tree, capture_output=True, text=True, timeout=TIMEOUT)
            out, rc = p.stdout + p.stderr, p.returncode
        except subprocess.TimeoutExpired as e:
            out, rc = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout"
        secs = round(time.monotonic() - t0, 2)
        logdir = os.path.join(self.out, "logs", stage)
        os.makedirs(logdir, exist_ok=True)
        open(os.path.join(logdir, m + ".log"), "w").write(out)
        errs = ERR_RE.findall(out)
        ok = rc == 0 and not errs
        return {"id": m, "stage": stage, "ok": ok, "rc": rc, "secs": secs, "errors": len(errs),
                "first_error": errs[0][:200] if errs else ("timeout" if rc == "timeout" else ""),
                "deprecations": out.count("has been deprecated")}

    def wait_load(self):
        while os.getloadavg()[0] > self.a.max_load:
            time.sleep(20)

    def pool(self, ids, stage, fn):
        """Run fn(m) -> row over ids with JOBS workers, recording rows; skips ids already done."""
        have = self.done(stage)
        todo = [m for m in ids if m not in have]
        t0 = time.time()
        n = 0
        with cf.ThreadPoolExecutor(self.a.jobs) as ex:
            futs = {ex.submit(fn, m): m for m in todo}
            for f in cf.as_completed(futs):
                row = f.result()
                self.record(stage, row)
                n += 1
                if n % 100 == 0:
                    el = time.time() - t0
                    print(f"[{stage}] {n}/{len(todo)} {el:.0f}s {3600 * n / el:.0f}/h load {os.getloadavg()[0]:.1f}",
                          flush=True)
        self.timing(stage, len(todo), time.time() - t0)
        have.update(self.done(stage))
        return have

    def timing(self, stage, n, secs):
        with open(os.path.join(self.out, "results", "timing.jsonl"), "a") as f:
            f.write(json.dumps({"stage": stage, "modules": n, "wall_s": round(secs, 1),
                                "per_hour": round(3600 * n / secs) if secs and n else None,
                                "jobs": self.a.jobs, "at": time.time()}) + "\n")


# -------------------------------------------------------------------- stages

def st_prepare(c):
    t0 = time.time()
    changed = 0
    for m in c.closure:
        changed += c.put(m, c.merged(m))
    for m in c.targets:
        changed += c.put(m, c.pinned(m))
    c.timing("prepare", len(c.closure) + len(c.targets), time.time() - t0)
    json.dump({"targets": c.targets, "closure": c.closure},
              open(os.path.join(c.out, "results", "selection.json"), "w"))
    print(f"prepare: {len(c.closure)} closure, {len(c.targets)} targets, {changed} files written")


def st_closure(c):
    have = c.done("closure")
    failed = {m for m, r in have.items() if not r["ok"]}
    by = collections.defaultdict(list)
    for m in c.closure:
        by[c.mods[m]["depth"]].append(m)
    for d in sorted(by):
        ids = [m for m in by[d] if not any(i in failed for i in c.mods[m]["imports"])]
        res = c.pool(ids, "closure", lambda m: c.compile(m, "closure"))
        failed |= {m for m, r in res.items() if not r["ok"]}
        print(f"closure depth {d}: {len(ids)} built, {len(failed)} failed so far", flush=True)


def blocked(c):
    cl = c.done("closure")
    bad = {m for m, r in cl.items() if not r["ok"]}
    missing = {m for m in c.closure if m not in cl}
    return bad | missing


def st_base(c):
    bad = blocked(c)
    ids = [m for m in c.targets if not any(i in bad for i in c.mods[m]["imports"])]
    for m in ids:
        c.put(m, c.pinned(m))
    c.pool(ids, "base", lambda m: c.compile(m, "base"))


def failing(c):
    return [m for m, r in sorted(c.done("base").items()) if not r["ok"]]


def table():
    rows = json.load(open(os.path.join(HERE, "..", "fixer", "data", "rules_all.json")))
    return select(rows, 2, 0.9)


def st_A(c):
    tab = table()

    def run(m):
        src = c.pinned(m)
        new = apply_all(src, tab, [], True, True)
        if new == src:
            return {"id": m, "stage": "A", "fired": False}
        c.put(m, new)
        row = c.compile(m, "A")
        row["fired"] = True
        os.makedirs(os.path.join(c.out, "edits", "A"), exist_ok=True)
        open(os.path.join(c.out, "edits", "A", m + ".lean"), "w").write(new)
        c.put(m, src)
        return row
    c.pool(failing(c), "A", run)


def st_B(c):
    def run(m):
        src = c.pinned(m)
        log = open(os.path.join(c.out, "logs", "base", m + ".log")).read()
        hs = harvest(log)
        new, napplied = apply_hints(src, hs)
        if new == src:
            return {"id": m, "stage": "B", "fired": False, "hints": len(hs)}
        c.put(m, new)
        row = c.compile(m, "B")
        row.update(fired=True, hints=len(hs), applied=napplied)
        os.makedirs(os.path.join(c.out, "edits", "B"), exist_ok=True)
        open(os.path.join(c.out, "edits", "B", m + ".lean"), "w").write(new)
        c.put(m, src)
        return row
    c.pool(failing(c), "B", run)


def st_C(c):
    tab = table()
    a = c.done("A")

    def run(m):
        src = c.pinned(m)
        ra = a.get(m)
        if ra and ra.get("fired"):
            mid = open(os.path.join(c.out, "edits", "A", m + ".lean")).read()
            if ra["ok"]:
                return {"id": m, "stage": "C", "fired": True, "ok": True, "from": "A"}
            log = open(os.path.join(c.out, "logs", "A", m + ".log")).read()
        else:
            mid = src
            log = open(os.path.join(c.out, "logs", "base", m + ".log")).read()
        new, napplied = apply_hints(mid, harvest(log))
        if new == src:
            return {"id": m, "stage": "C", "fired": False}
        if new == mid and ra and ra.get("fired"):
            r = dict(ra); r.update(stage="C", fired=True, **{"from": "A-no-hints"})
            return r
        c.put(m, new)
        row = c.compile(m, "C")
        row.update(fired=True, applied=napplied)
        os.makedirs(os.path.join(c.out, "edits", "C"), exist_ok=True)
        open(os.path.join(c.out, "edits", "C", m + ".lean"), "w").write(new)
        c.put(m, src)
        return row
    c.pool(failing(c), "C", run)


UNKNOWN_RE = re.compile(r"error\(lean\.unknownIdentifier\): Unknown (?:identifier|constant) `([^`]+)`")


def st_D(c):
    """Error-gated rules: for modules still failing after A, apply any mined rename (support >= 1,
    no precision threshold) whose old name the compiler reports as an unknown identifier or
    constant; rebuild; repeat up to 3 rounds."""
    rows = json.load(open(os.path.join(HERE, "..", "fixer", "data", "rules_all.json")))
    full = {r["old"]: r["new"] for r in rows}
    a = c.done("A")

    def run(m):
        src = c.pinned(m)
        ra = a.get(m)
        if ra and ra.get("ok"):
            return {"id": m, "stage": "D", "fired": False, "skip": "A-fixed"}
        if ra and ra.get("fired"):
            cur = open(os.path.join(c.out, "edits", "A", m + ".lean")).read()
            log = open(os.path.join(c.out, "logs", "A", m + ".log")).read()
        else:
            cur, log = src, open(os.path.join(c.out, "logs", "base", m + ".log")).read()
        row, used = {"id": m, "stage": "D", "fired": False}, []
        for rnd in range(3):
            unk = set(UNKNOWN_RE.findall(log))
            tab = {o: full[o] for o in unk if o in full and o not in used}
            if not tab:
                break
            used += sorted(tab)
            new = apply_all(cur, tab, [], False, False)
            if new == cur:
                break
            cur = new
            c.put(m, cur)
            row = c.compile(m, "D")
            row.update(fired=True, rounds=rnd + 1, rules=used)
            log = open(os.path.join(c.out, "logs", "D", m + ".log")).read()
            if row["ok"]:
                break
        if row["fired"]:
            os.makedirs(os.path.join(c.out, "edits", "D"), exist_ok=True)
            open(os.path.join(c.out, "edits", "D", m + ".lean"), "w").write(cur)
            c.put(m, src)
        return row
    c.pool(failing(c), "D", run)


def st_restore(c):
    n = sum(c.put(m, c.pinned(m)) for m in c.targets)
    print("restored", n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--max-load", type=float, default=36.0)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("stages", nargs="+")
    a = ap.parse_args()
    c = Ctx(a)
    for s in a.stages:
        t0 = time.time()
        globals()["st_" + s](c)
        print(f"stage {s} done in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
