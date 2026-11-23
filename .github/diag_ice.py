"""TEMPORARY: locate the function that crashes cl.exe (VS 2026)."""
import json, re, subprocess, sys

OFF = '#pragma optimize("", off)\n'
ON = '#pragma optimize("", on)\n'


def run(cmd, cwd):
    p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, errors="replace")
    return p.returncode, p.stdout + p.stderr


def main():
    log = open("build.log", errors="replace").read()
    failed = sorted(set(re.findall(r"FAILED:.*?([\w-]+\.c)\.obj", log)))
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

    src = "".join(lines)

    def variant(label, fn):
        t = fn(src)
        if t == src:
            print(f"EXP {label}: transform did not apply", flush=True)
            return
        open(path, "w", encoding="latin-1", newline="").write(t)
        rc, out = run(cmd, cwd)
        print(f"EXP {label}: rc {rc} {'CRASH' if rc else 'ok'}", flush=True)

    NI = "static __declspec(noinline) void\n"
    def sub(a, b, count=1):
        a = a.replace("\n", NL); b = b.replace("\n", NL)
        return lambda t: t.replace(a, b, count)
    NL = "\r\n" if "\r\n" in src else "\n"
    def region(t):
        i = t.index("s390_irgen_EX(UChar r1, IRTemp addr2)")
        j = t.index("s390_irgen_EXRL(UChar r1, UInt offset)")
        return i, j
    def in_ex(f):
        def g(t):
            i, j = region(t)
            return t[:i] + f(t[i:j]) + t[j:]
        return g

    variant("noinline EX_SS", sub("static void\ns390_irgen_EX_SS(", NI + "s390_irgen_EX_SS("))
    variant("noinline EX", sub("static void\ns390_irgen_EX(UChar r1, IRTemp addr2)", NI + "s390_irgen_EX(UChar r1, IRTemp addr2)"))
    variant("noinline EXRL", sub("static void\ns390_irgen_EXRL(", NI + "s390_irgen_EXRL("))
    variant("noinline decode_and_irgen", sub("static UInt\ns390_decode_and_irgen(const", "static __declspec(noinline) UInt\ns390_decode_and_irgen(const"))
    variant("switch on >>56", in_ex(lambda r: re.sub(r"case 0x(..)00000000000000ULL:", r"case 0x\1:", r.replace("switch (last_execute_target & 0xff00000000000000ULL)", "switch (last_execute_target >> 56)"))))
    variant("default: no bytes[0] read", in_ex(lambda r: r.replace("((((bytes[0] >> 6) + 1) >> 1) + 1) << 1", "6")))
    variant("default: bytes points to copy", in_ex(lambda r: r.replace("bytes = (UChar *) &last_execute_target;", "{ static ULong copy_; copy_ = last_execute_target; bytes = (UChar *) &copy_; }")))
    variant("default: no decode call", in_ex(lambda r: re.sub(r"s390_decode_and_irgen\(bytes,[^;]*;", "stmt((IRStmt*)bytes);", r)))
    variant("EX_SS volatile ovl", sub("   IRDirty *d;\n   ULong ovl;", "   IRDirty *d;\n   volatile ULong ovl;"))
    variant("EX_SS no reset of target", sub("   irgen(len, start1, start2);\n\n   last_execute_target = Invalid_execute_target;", "   irgen(len, start1, start2);\n"))
    variant("EX default no reset of target", in_ex(lambda r: r.replace("      last_execute_target = Invalid_execute_target;", "")))
    variant("EX no early invalid check", in_ex(lambda r: r.replace("if (last_execute_target == Invalid_execute_target) {", "if (r1 == 77) {")))
    variant("only MVC case", in_ex(lambda r: re.sub(r"   case 0xd5.*?(?=   default:)", "", r, flags=re.S)))

    # standalone attempt
    for flags in ["/O2", "/O2 /Ob2", "/O1", "/Ob1 /O2"]:
        rc, out = run(f"cl /nologo /c {flags} /Fomini.obj .github\\mini_ice.c", ".")
        print(f"MINI {flags}: rc {rc} | {out.strip()[-200:]}", flush=True)


main()
