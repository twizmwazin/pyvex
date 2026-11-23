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

    def in_dec(f):
        def g(t):
            i = t.index("s390_decode_and_irgen(const UChar *bytes, UInt insn_length, DisResult *dres)")
            j = t.index("disInstr_S390_WRK(const UChar *insn)")
            return t[:i] + f(t[i:j]) + t[j:]
        return g
    pre = re.compile(r"bytes\[ 0\] == 0x18 &&.*?bytes\[ 7\] == 0x33", re.S)
    variant("noinline decode_and_irgen", sub("static UInt\ns390_decode_and_irgen(const", "static __declspec(noinline) UInt\ns390_decode_and_irgen(const"))
    variant("preamble: only byte0", in_dec(lambda r: pre.sub("bytes[0] == 0x18", r)))
    variant("preamble: bytes 0-6", in_dec(lambda r: r.replace(" &&\n       bytes[ 6] == 0x18 && bytes[ 7] == 0x33".replace("\n", NL), " &&\n       bytes[ 6] == 0x18".replace("\n", NL))))
    variant("preamble: bytes 0-3", in_dec(lambda r: pre.sub("bytes[0] == 0x18 && bytes[1] == 0xff && bytes[2] == 0x18 && bytes[3] == 0x11", r)))
    variant("preamble: bytes 1-7 only", in_dec(lambda r: r.replace("bytes[ 0] == 0x18 && bytes[ 1] == 0xff", "bytes[ 1] == 0xff")))
    variant("preamble: via volatile ptr", in_dec(lambda r: pre.sub("(*(const UChar *volatile *)&bytes)[0] == 0x18", r)))
    variant("no next-insn-is-EX check", in_dec(lambda r: r.replace("if (dis_res->whatNext == Dis_Continue &&", "if (0 && dis_res->whatNext == Dis_Continue &&")))
    variant("no special decode", in_dec(lambda r: r.replace("s390_decode_special_and_irgen(bytes + S390_SPECIAL_OP_PREAMBLE_SIZE);", "S390_DECODE_ERROR;")))
    variant("no failure printing", in_dec(lambda r: r.replace("if (sigill_diag) {", "if (0) {")))
    variant("EX: no top-byte switch", in_ex(lambda r: r.replace("switch (last_execute_target & 0xff00000000000000ULL)", "switch ((ULong)r1 << 60)")))

    # standalone attempts
    HEAD = """typedef unsigned long long ULong; typedef unsigned char UChar;
ULong target = 1; extern int flag; extern int other(const UChar *);
static int dec(const UChar *b) {
   if (flag && b[0] == 0x18 && b[1] == 0xff && b[2] == 0x18 && b[3] == 0x11 &&
       b[4] == 0x18 && b[5] == 0x22 && b[6] == 0x18 && b[7] == 0x33)
      return other(b + 8);
   return other(b);
}
"""
    minis = {
      "switch+dec": "int ex(void) { switch (target & 0xff00000000000000ULL) { case 0xd200000000000000ULL: return 5; case 0xd500000000000000ULL: return 6; default: return dec((UChar *)&target); } }",
      "plain dec": "int ex(void) { return dec((UChar *)&target); }",
      "if+dec": "int ex(void) { if (target == 1) return 3; if ((target >> 56) == 0xd2) return 5; return dec((UChar *)&target); }",
      "byte0+dec": "int ex(void) { UChar *b = (UChar *)&target; if (target == 1) return 3; return dec(b) + (b[0] >> 6); }",
      "cmp+dec": "int ex(ULong x) { if (x != target) return 3; return dec((UChar *)&target); }",
    }
    for label, body in minis.items():
        open("mini.c", "w").write(HEAD + body + "\n")
        rc, out = run("cl /nologo /c /O2 /Fomini.obj mini.c", ".")
        print(f"MINI {label}: rc {rc} | {out.strip()[-120:]}", flush=True)


main()
