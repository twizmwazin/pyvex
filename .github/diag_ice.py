"""TEMPORARY: locate the function that crashes cl.exe (VS 2026)."""
import json, re, subprocess, sys

OFF = '#pragma optimize("", off)\n'
ON = '#pragma optimize("", on)\n'


def run(cmd, cwd):
    p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, errors="replace")
    return p.returncode, p.stdout + p.stderr


def main():
    log = open("build.log", errors="replace").read()
    failed = sorted(set(re.findall(r"FAILED: \S*?([\w-]+\.c)\.obj", log)))
    print("FAILED FILES:", failed, flush=True)
    for m in re.finditer(r"FAILED:.*\n(?:.*\n){0,3}", log):
        pass
    cc = json.load(open("build/compile_commands.json"))
    for name in failed:
        ent = [e for e in cc if e["file"].replace("\\", "/").endswith("/" + name)][0]
        path, cmd, cwd = ent["file"], ent["command"], ent["directory"]
        orig = open(path, encoding="latin-1", newline="").read()
        lines = orig.splitlines(keepends=True)
        try:
            diagnose(name, path, cmd, cwd, lines)
        finally:
            open(path, "w", encoding="latin-1", newline="").write(orig)


def diagnose(name, path, cmd, cwd, lines):
    print(f"\n===== {name} =====", flush=True)

    def compile_with(inserts, extra=""):
        # inserts: {line_index: text inserted before that line}
        out = []
        for i, l in enumerate(lines):
            if i in inserts:
                out.append(inserts[i])
            out.append(l)
        if len(lines) in inserts:
            out.append(inserts[len(lines)])
        open(path, "w", encoding="latin-1", newline="").write("".join(out))
        return run(cmd + " " + extra, cwd)

    rc, out = compile_with({})
    print("baseline rc", rc, "|", out.strip()[-300:], flush=True)
    for flags in ["/Ob0", "/Ob1", "/O1", "/Od", "/O2 /Ob2 /d2ReducedOptimizeHugeFunctions"]:
        rc, out = compile_with({}, flags)
        print(f"whole file {flags}: rc {rc}", flush=True)

    bounds = [i + 1 for i, l in enumerate(lines) if l.rstrip("\r\n") == "}"]
    # validate boundaries: pragma must be at file scope
    for _ in range(5):
        rc, out = compile_with({b: ON for b in bounds}, "/Od")
        if rc == 0:
            break
        # inserted lines shift numbering; map reported line back
        bad = set()
        srt = sorted(bounds)
        for ln in re.findall(r"\((\d+)\)\s*:\s*error C2156", out):
            ln = int(ln)
            for k, b in enumerate(srt):
                if b + k + 1 == ln:
                    bad.add(b)
        print("dropping", len(bad), "non-file-scope boundaries; rc", rc, flush=True)
        if not bad:
            print(out[-2000:])
            return
        bounds = [b for b in bounds if b not in bad]
    bounds = [0] + bounds
    if bounds[-1] != len(lines):
        bounds.append(len(lines))
    n = len(bounds) - 1

    def ok(lo, hi):
        rc, _ = compile_with({bounds[lo]: OFF, bounds[hi]: ON})
        return rc == 0

    if not ok(0, n):
        print("still crashes with optimization off everywhere (culprit in an included file?)")
        return
    lo, hi = 0, n
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ok(lo, mid):
            hi = mid
        elif ok(mid, hi):
            lo = mid
        else:
            print(f"multiple culprits within lines {bounds[lo]+1}-{bounds[hi]}", flush=True)
            break
        print(f"  narrowed to lines {bounds[lo]+1}-{bounds[hi]}", flush=True)
    a, b = bounds[lo], bounds[hi]
    print(f"CULPRIT {name}: lines {a+1}-{b}", flush=True)
    sys.stdout.write("".join(lines[a:min(b, a + 12)]))
    sys.stdout.flush()


main()
