# 과거 팀명 통일 (SK->SSG, 넥센/우리->키움). fetch_vb 직후 1회 실행.
import json
from pathlib import Path
MAP={"SK":"SSG","SK 와이번스":"SSG","넥센":"키움","우리":"키움","히어로즈":"키움"}
p=Path("kbo_games.json"); d=json.loads(p.read_text(encoding="utf-8"))
n=0
for g in d["games"]:
    for k in ("home","away"):
        if g.get(k) in MAP: g[k]=MAP[g[k]]; n+=1
p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")
print(f"팀명 정규화 {n}건 적용")
