def edit(path, old, new, n_expected=1):
    s=open(path,encoding='utf-8').read()
    c=s.count(old)
    if c!=n_expected:
        print(f'  [{path}] 매칭 {c}회(기대 {n_expected}) — 실패:', old[:45]); return False
    open(path,'w',encoding='utf-8').write(s.replace(old,new)); print(f'  [{path}] {c}곳 수정'); return True

ok=True
ok&=edit('fetch_vb.py',
  '    years = list(range(yesterday.year, 2020, -1))',
  '    years = [y for y in range(yesterday.year, 2018, -1) if y != 2020]')
ok&=edit('fetch_scores.py',
  'TARGET_YEARS = {2025, 2026}',
  'TARGET_YEARS = {2019, 2021, 2022, 2023, 2024, 2025, 2026}')
ok&=edit('compute_standings.py',
  'for yr in (2025, 2026):',
  "for yr in sorted({g.get('yr') for g in games if g.get('yr')} - {2020}):",
  n_expected=2)

norm = '# 과거 팀명 통일 (SK->SSG, 넥센/우리->키움). fetch_vb 직후 1회 실행.\n'
norm += 'import json\nfrom pathlib import Path\n'
norm += 'MAP={"SK":"SSG","SK 와이번스":"SSG","넥센":"키움","우리":"키움","히어로즈":"키움"}\n'
norm += 'p=Path("kbo_games.json"); d=json.loads(p.read_text(encoding="utf-8"))\n'
norm += 'n=0\n'
norm += 'for g in d["games"]:\n'
norm += '    for k in ("home","away"):\n'
norm += '        if g.get(k) in MAP: g[k]=MAP[g[k]]; n+=1\n'
norm += 'p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")\n'
norm += 'print(f"팀명 정규화 {n}건 적용")\n'
open('normalize_teams.py','w',encoding='utf-8').write(norm); print('  [normalize_teams.py] 생성')
print('=> 전체 완료' if ok else '=> 일부 실패')
