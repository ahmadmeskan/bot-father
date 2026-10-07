python - <<'EOF'
import importlib.util, os, re, shutil
root = os.path.dirname(importlib.util.find_spec("pyrogram").origin)
H = ("import asyncio as _afix\n"
     "def _pyro_get_event_loop():\n"
     "    try:\n"
     "        return _afix.get_running_loop()\n"
     "    except RuntimeError:\n"
     "        pass\n"
     "    try:\n"
     "        l = _afix.get_event_loop_policy().get_event_loop()\n"
     "        if not l.is_closed():\n"
     "            return l\n"
     "    except Exception:\n"
     "        pass\n"
     "    l = _afix.new_event_loop()\n"
     "    _afix.set_event_loop(l)\n"
     "    return l\n\n")
pat, n = re.compile(r"asyncio\.get_event_loop\(\)"), 0
for d, _, fs in os.walk(root):
    for f in fs:
        if not f.endswith(".py"): continue
        p = os.path.join(d, f)
        t = open(p, encoding="utf-8").read()
        if "_pyro_get_event_loop" in t or not pat.search(t): continue
        if "from __future__" in t: continue
        new = H + pat.sub("_pyro_get_event_loop()", t)
        try: compile(new, p, "exec")
        except SyntaxError: continue
        shutil.copy2(p, p + ".orig"); open(p, "w", encoding="utf-8").write(new)
        print("patched:", os.path.relpath(p, root)); n += 1
print("done, files patched:", n)
EOF
