"""Compara el bytecode original (PYZ extraido) con el codigo fuente reconstruido, funcion a funcion.
usage: python -I verify.py <orig_pyz_dir> <src_root>
"""
import marshal, os, sys, types

orig_root, src_root = sys.argv[1], sys.argv[2]


def collect(co, out, prefix=""):
    q = co.co_qualname
    if q == "__annotate__" or q.endswith(".__annotate__"):
        return
    strs = {c for c in co.co_consts if isinstance(c, (str, bytes, int, float)) and not isinstance(c, bool)
            and not (isinstance(c, str) and c.startswith("<"))}
    # nombres globales/atributos usados
    out[q] = (strs, set(co.co_names))
    for c in co.co_consts:
        if isinstance(c, types.CodeType):
            collect(c, out)


total_missing = 0
for dirpath, _, files in os.walk(orig_root):
    for f in sorted(files):
        if not f.endswith(".pyc"):
            continue
        rel = os.path.relpath(os.path.join(dirpath, f), orig_root)[:-4] + ".py"
        src = os.path.join(src_root, "atvmaster", rel)
        if not os.path.exists(src):
            print("FALTA", rel)
            continue
        with open(os.path.join(dirpath, f), "rb") as fh:
            fh.read(16)
            o = marshal.load(fh)
        n = compile(open(src, encoding="utf-8").read(), src, "exec")
        a, b = {}, {}
        collect(o, a)
        collect(n, b)
        issues = []
        for q, (s, names) in a.items():
            if q not in b:
                issues.append(f"  funcion ausente: {q}")
                continue
            ms = {x for x in s - b[q][0] if not (isinstance(x, int) and x < 300)}
            mn = names - b[q][1]
            if ms:
                issues.append(f"  {q}: constantes ausentes {sorted(map(repr, ms))[:6]}")
            if mn:
                issues.append(f"  {q}: nombres ausentes {sorted(mn)[:8]}")
        extra = set(b) - set(a)
        print(("OK   " if not issues else "DIF  ") + rel + f"  (funciones: orig {len(a)}, nueva {len(b)})")
        for i in issues:
            print(i)
        total_missing += len(issues)
print("TOTAL diferencias:", total_missing)
