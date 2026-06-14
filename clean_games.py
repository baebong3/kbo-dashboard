"""
kbo_games.json 정리기 (1회용)
- 수집 오류로 만들어진 '가짜 매치업' 제거
- 규칙: 한 팀은 하루에 한 상대만 상대한다.
        같은 날 한 팀이 서로 다른 2개 이상 팀과 경기한 것으로 기록된 날짜는
        통째로 제거(그 날짜는 이후 fetch_kbo.py 등으로 재수집).
        더블헤더(같은 상대와 2경기)는 정상으로 보존.
- 원본은 kbo_games.json.bak 으로 백업
"""
import json
from collections import defaultdict, Counter
from pathlib import Path

def date_is_clean(recs):
    opp = defaultdict(set)            # 팀 -> 그날 상대한 팀 집합
    for r in recs:
        h, a = r.get('home',''), r.get('away','')
        if h and a:
            opp[h].add(a); opp[a].add(h)
    # 어떤 팀이든 서로 다른 상대가 2팀 이상이면 가짜 섞인 날
    return all(len(v) <= 1 for v in opp.values())

def main():
    p = Path('kbo_games.json')
    data = json.loads(p.read_text(encoding='utf-8'))
    games = data.get('games', [])

    bydate = defaultdict(list)
    for g in games:
        bydate[g.get('date')].append(g)

    kept, dropped = [], []
    for d, recs in bydate.items():
        if date_is_clean(recs):
            kept.extend(recs)
        else:
            dropped.append((d, len(recs)))

    before = Counter(g['yr'] for g in games)
    after  = Counter(g['yr'] for g in kept)
    print(f"정리 전 {len(games)}경기 → 후 {len(kept)}경기 "
          f"(가짜 섞인 {len(dropped)}일 제거)\n")
    print("연도별 (전 → 후):")
    for yr in sorted(before):
        print(f"  {yr}: {before[yr]:>5} → {after.get(yr,0):>5}")
    print("\n제거된 날짜(재수집 대상):")
    for d, n in sorted(dropped):
        print(f"  {d}  ({n}건)")

    # 백업 후 저장
    p.with_suffix('.json.bak').write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    data['games'] = sorted(kept, key=lambda g: g.get('date',''), reverse=True)
    data['total'] = len(kept)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n백업: kbo_games.json.bak  /  저장 완료: {len(kept)}경기")

if __name__ == '__main__':
    main()
