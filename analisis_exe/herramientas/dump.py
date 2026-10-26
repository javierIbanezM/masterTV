"""Dump outline + disassembly of PyInstaller-extracted .pyc files (same Python version required).
usage: python -I dump.py <pyz_extracted_dir> <out_dir>
"""
import dis, io, marshal, os, sys, types

src_root, out_root = sys.argv[1], sys.argv[2]


def outline(co, out, indent=0):
    pad = "    " * indent
    kind = "class/module body" if co.co_name.startswith("<") or co.co_flags & 0 else "def"
    args = co.co_varnames[: co.co_argcount + co.co_kwonlyargcount]
    out.write(f"{pad}{co.co_qualname}({', '.join(args)})  line {co.co_firstlineno}\n")
    for c in co.co_consts:
        if isinstance(c, types.CodeType):
            outline(c, out, indent + 1)


def strings(co, acc):
    for c in co.co_consts:
        if isinstance(c, str) and len(c) > 1:
            acc.append(c)
        elif isinstance(c, types.CodeType):
            strings(c, acc)


for dirpath, _, files in os.walk(src_root):
    for f in files:
        if not f.endswith(".pyc"):
            continue
        p = os.path.join(dirpath, f)
        rel = os.path.relpath(p, src_root)
        with open(p, "rb") as fh:
            fh.read(16)
            co = marshal.load(fh)
        base = os.path.join(out_root, rel[:-4])
        os.makedirs(os.path.dirname(base), exist_ok=True)
        with open(base + ".dis.txt", "w", encoding="utf-8") as o:
            dis.dis(co, file=o)
        with open(base + ".outline.txt", "w", encoding="utf-8") as o:
            outline(co, o)
            acc = []
            strings(co, acc)
            o.write("\n--- strings ---\n")
            for s in acc:
                o.write(repr(s) + "\n")
        print("ok", rel)
