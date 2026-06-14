"""
날짜별 순위 계산 + 각 경기에 '그 경기 직전(당일 아침) 순위·승률' 부착
- 입력: kbo_games.json (각 2025·2026 경기에 away_score/home_score 필요)
- 처리: 경기 결과로 누적 승·패·무 계산 → KBO 승률(승/(승+패)) 기준 순위
        각 경기에는 '그 날짜 이전까지의 성적'으로 매긴 순위를 부착(팬이 경기 전 알던 순위)
- 출력: 각 경기에 home_rank/away_rank/home_wpct/away_wpct/rank_gap 추가 후 저장
        + 순위대별 평균 관중·점유율 요약 출력
실행: python compute_standings.py
"""
import json
from collections import defaultdict
from pathlib import Path

CAPY={'LG':23750,'두산':23750,'삼성':24000,'KIA':20500,'SSG':23183,
      '롯데':23200,'kt':18700,'한화':20007,'NC':18128,'키움':16000}
CAPY_PRE25={'한화':13000}  # 2025 이전 한화 구장

def cap(team, yr):
    if yr < 2025 and team in CAPY_PRE25: return CAPY_PRE25[team]
    return CAPY.get(team, 20000)

def winner(g):
    a, h = g.get('away_score'), g.get('home_score')
    if a is None or h is None: return None
    if h > a: return 'home'
    if a > h: return 'away'
    return 'tie'

def standings_snapshot(rec):
    """rec: team -> [W,L,T] → 순위 매긴 dict team -> (rank, wpct, gb)"""
    def wpct(wlt):
        w,l,t = wlt
        return w/(w+l) if (w+l)>0 else 0.0
    order = sorted(rec.keys(), key=lambda t: (-wpct(rec[t]), -rec[t][0]))
    if not order: return {}
    w1,l1,_ = rec[order[0]]
    out={}
    for i,t in enumerate(order):
        w,l,_ = rec[t]
        gb = ((w1 - w) + (l - l1))/2
        out[t] = (i+1, round(wpct(rec[t]),3), gb)
    return out

def process_year(games_year):
    """경기 직전 순위 부착. games_year: 그 해 경기 리스트(점수 포함 가정)"""
    bydate = defaultdict(list)
    for g in games_year:
        bydate[g['date']].append(g)
    rec = defaultdict(lambda: [0,0,0])   # team -> [W,L,T]
    # 모든 팀 등록(0-0-0)
    teams = set(g['home'] for g in games_year) | set(g['away'] for g in games_year)
    for t in teams: rec[t]
    for d in sorted(bydate):
        snap = standings_snapshot(rec)           # 그 날짜 '이전'까지의 순위
        for g in bydate[d]:
            hr = snap.get(g['home'], (None,None,None))
            ar = snap.get(g['away'], (None,None,None))
            g['home_rank'], g['home_wpct'], g['home_gb'] = hr
            g['away_rank'], g['away_wpct'], g['away_gb'] = ar
            g['rank_gap'] = (abs(hr[0]-ar[0]) if hr[0] and ar[0] else None)
        # 그 날짜 결과 누적
        for g in bydate[d]:
            w = winner(g)
            if w is None: continue
            h,a = g['home'], g['away']
            if w=='home': rec[h][0]+=1; rec[a][1]+=1
            elif w=='away': rec[a][0]+=1; rec[h][1]+=1
            else: rec[h][2]+=1; rec[a][2]+=1

def main():
    p = Path('kbo_games.json')
    data = json.loads(p.read_text(encoding='utf-8'))
    games = data['games']

    for yr in (2025, 2026):
        gy = [g for g in games if g.get('yr')==yr and g.get('att')]
        scored = [g for g in gy if g.get('home_score') is not None]
        print(f"[{yr}] {len(gy)}경기 중 점수 보유 {len(scored)}")
        if len(scored) < len(gy)*0.8:
            print(f"  ⚠ 점수 부족 — fetch_scores.py 전체 실행(TEST_LIMIT=0) 후 다시 돌리세요.\n")
            continue
        process_year(gy)

    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print("순위 부착 저장 완료.\n")

    # ── 요약: 홈팀 순위대별 평균 관중·점유율 ──
    def occ(g): return g['att']/cap(g['home'], g['yr'])
    for yr in (2025, 2026):
        rows = [g for g in games if g.get('yr')==yr and g.get('att') and g.get('home_rank')]
        if not rows: continue
        print(f"=== {yr} 홈팀 순위대별 ===")
        for lo,hi,lab in [(1,3,'1~3위'),(4,6,'4~6위'),(7,10,'7~10위')]:
            sub=[g for g in rows if lo<=g['home_rank']<=hi]
            if sub:
                a=sum(g['att'] for g in sub)/len(sub)
                o=sum(occ(g) for g in sub)/len(sub)*100
                print(f"  홈팀 {lab}: 평균관중 {a:>7,.0f} / 점유율 {o:4.1f}%  ({len(sub)}경기)")
        # 순위차(접전 여부)
        print(f"  --- 순위차별 ---")
        for lo,hi,lab in [(0,2,'0~2위차(접전)'),(3,5,'3~5위차'),(6,9,'6위차+')]:
            sub=[g for g in rows if g.get('rank_gap') is not None and lo<=g['rank_gap']<=hi]
            if sub:
                a=sum(g['att'] for g in sub)/len(sub)
                print(f"  {lab}: 평균관중 {a:>7,.0f}  ({len(sub)}경기)")
        print()

if __name__ == '__main__':
    main()
