import dis, marshal, os, sys, types
src_root, out_root = sys.argv[1], sys.argv[2]
SKIP = {"RESUME","NOT_TAKEN","CACHE","PUSH_NULL","POP_TOP","COPY_FREE_VARS","MAKE_CELL","NOP"}
def walk(co, out, ind=0):
    if co.co_name == "__annotate__": return
    out.write("\n%sDEF %s(%s) @%d\n" % ("  "*ind, co.co_qualname, ",".join(co.co_varnames[:co.co_argcount+co.co_kwonlyargcount]), co.co_firstlineno))
    cur=None; buf=[]
    def flush():
        if buf: out.write("%s%s: %s\n" % ("  "*ind, cur, "; ".join(buf)))
    for i in dis.get_instructions(co):
        if i.opname in SKIP: continue
        ln = i.line_number
        if ln != cur:
            flush(); buf=[]; cur=ln
        if i.is_jump_target: buf.append("<L%d>" % i.offset)
        a = i.argrepr
        if not a and i.opname=="LOAD_SMALL_INT": a = str(i.argval)
        if isinstance(i.argval, types.CodeType): a = "<code %s>" % i.argval.co_qualname
        if "JUMP" in i.opname or i.opname.startswith("POP_JUMP") or i.opname=="FOR_ITER": a = "->%s" % i.argval
        buf.append(i.opname + (" "+a if a else ""))
    flush()
    for c in co.co_consts:
        if isinstance(c, types.CodeType): walk(c, out, ind+1)
for d,_,fs in os.walk(src_root):
    for f in fs:
        if f.endswith(".pyc"):
            p=os.path.join(d,f)
            with open(p,"rb") as fh:
                fh.read(16); co=marshal.load(fh)
            b=os.path.join(out_root, os.path.relpath(p,src_root)[:-4]+".c.txt")
            os.makedirs(os.path.dirname(b),exist_ok=True)
            with open(b,"w",encoding="utf-8") as o: walk(co,o)
