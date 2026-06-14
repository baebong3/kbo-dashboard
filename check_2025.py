"""kbo_games.json 의 2025 시즌 완성도 점검 — 날짜별 경기수와 빠진(의심) 날짜 출력"""
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

data = json.loads(Path('kbo_games.json').read_text(encoding='utf-8'))
games = [g for g in data.get('games', []) if g.get('yr') == 2025 and g.get('att')]
bydate = defaultdict(list)
for g in games:
    bydate[g['date']].append(g)

print(f"2025 총 경기수: {len(games)}  (정상: 720)")
print(f"경기가 있는 날짜 수: {len(bydate)}\n")

# 시즌 범위 내에서 '경기가 0이거나 비정상적으로 적은 날' 찾기
if bydate:
    ds = sorted(bydate)
    start = date.fromisoformat(ds[0]); end = date.fromisoformat(ds[-1])
    print(f"시즌 범위: {start} ~ {end}")
    print("\n[경기 수가 적은(≤2) 또는 비어있는 날 — 보충 후보]")
    d = start
    gap_days = []
    while d <= end:
        iso = d.isoformat()
        n = len(bydate.get(iso, []))
        # KBO는 월요일 휴식이 많음 → 월요일(weekday()==0)은 0경기 정상일 수 있음
        if n == 0 and d.weekday() != 0:
            gap_days.append((iso, d.strftime('%a'), 0))
        elif 0 < n <= 2:
            gap_days.append((iso, d.strftime('%a'), n))
        d += timedelta(days=1)
    for iso, dow, n in gap_days:
        print(f"  {iso} ({dow}): {n}경기")
    if not gap_days:
        print("  없음 — 날짜 공백 없음")

# 월별 요약
print("\n[월별 경기수]")
bymonth = defaultdict(int)
for g in games: bymonth[g['mo']] += 1
for m in range(3, 11):
    if bymonth.get(m): print(f"  {m}월: {bymonth[m]}경기")
