import marshal, os, sys, types, dis
from collections import Counter
orig_root, src_root = sys.argv[1], sys.argv[2]
KEEP = {"LOAD_ATTR","LOAD_GLOBAL","LOAD_METHOD","STORE_ATTR","COMPARE_OP","IS_OP","CONTAINS_OP","BINARY_OP","RETURN_VALUE","RAISE_VARARGS","FOR_ITER","CALL_KW"}
def sig(co):
    c = Counter()
    for i in dis.get_instructions(co):
        if i.opname in ("LOAD_ATTR","LOAD_GLOBAL","STORE_ATTR"):
            c[(i.opname.replace("LOAD_GLOBAL","G").replace("LOAD_ATTR","A"), str(i.argval))] += 1
        elif i.opname in ("COMPARE_OP","IS_OP","CONTAINS_OP","BINARY_OP","RAISE_VARARGS","CALL_KW","FOR_ITER"):
            c[(i.opname, i.argrepr if i.opname not in ("FOR_ITER",) else "")] += 1
        elif i.opname in ("LOAD_CONST",) and isinstance(i.argval,(str,int,float,bytes)) and not isinstance(i.argval,bool):
            c[("K", i.argval)] += 1
    return c
def walk(co, out):
    if co.co_qualname.endswith("__annotate__"): return
    out[co.co_qualname] = sig(co)
    for k in co.co_consts:
        if isinstance(k, types.CodeType): walk(k, out)
bad = 0
for d,_,fs in os.walk(orig_root):
    for f in sorted(fs):
        if not f.endswith(".pyc"): continue
        rel = os.path.relpath(os.path.join(d,f), orig_root)[:-4]+".py"
        fh = open(os.path.join(d,f),"rb"); fh.read(16); o = marshal.load(fh)
        n = compile(open(os.path.join(src_root,"atvmaster",rel),encoding="utf-8").read(), rel, "exec")
        a,b = {},{}; walk(o,a); walk(n,b)
        for q in a:
            if q not in b: continue
            da = a[q]-b[q]; db = b[q]-a[q]
            # ignorar ruido de docstrings (K str)
            da = {k:v for k,v in da.items()}; db = {k:v for k,v in db.items()}
            if da or db:
                bad += 1
                print(f"{rel} :: {q}")
                if da: print("   solo ORIGINAL:", [ (k,v) for k,v in list(da.items())[:8]])
                if db: print("   solo NUEVA   :", [ (k,v) for k,v in list(db.items())[:8]])
print("funciones con diferencias:", bad)
