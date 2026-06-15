"""
KBO 일일 증분 업데이트 스크립트
- 현재 달(월초이면 전달도)을 보고 '아직 파일에 없는 경기'만 추가
- 기존 데이터(game_id·날씨 포함)는 절대 건드리지 않음 → 누적/덮어쓰기 없음
- 하루 CI가 실패해 건너뛰어도, 다음 실행이 그 달 전체를 다시 보므로 자동 보충

[설계]
  · 새 경기에 표준 game_id(YYYYMMDD+원정코드+홈코드+더블헤더번호) 부여
  · 병합: 기존 보존 + 기존에 없는 (날짜+카드)만 추가 + 최종 dedup_clean
"""
import json, re, time
from datetime import datetime, date, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

TEAM_MAP = {
    'LG':'LG','두산':'두산','삼성':'삼성','KIA':'KIA','SSG':'SSG',
    'kt':'kt','KT':'kt','롯데':'롯데','한화':'한화','NC':'NC','키움':'키움'
}
TEAM_CODE = {
    'LG':'LG','두산':'OB','KIA':'HT','삼성':'SS','롯데':'LT',
    'SSG':'SK','키움':'WO','한화':'HH','NC':'NC','kt':'KT',
}
DAYS_KO = ['일','월','화','수','목','금','토']

# 중복 제거용 키 ---------------------------------------------------
def make_game_id(g):
    ac = TEAM_CODE.get(g.get('away', ''))
    hc = TEAM_CODE.get(g.get('home', ''))
    if not ac or not hc:
        return None
    d = str(g.get('date', '')).replace('-', '')
    return f"{d}{ac}{hc}{g.get('dh', 0)}"

def matchup_key(g):
    teams = '-'.join(sorted([g.get('home', ''), g.get('away', '')]))
    return f"{g.get('date')}|{teams}"

def dedup_clean(games):
    seen_id, seen_match, out = set(), set(), []
    for g in games:
        gid = g.get('game_id')
        if not gid:
            continue
        if gid in seen_id:
            continue
        seen_id.add(gid); out.append(g); seen_match.add(matchup_key(g))
    for g in games:
        if g.get('game_id'):
            continue
        mk = matchup_key(g)
        if mk in seen_match:
            continue
        seen_match.add(mk); out.append(g)
    return out

def strip_cartesian(games):
    from collections import defaultdict
    byd=defaultdict(list)
    for g in games: byd[g.get('date')].append(g)
    bad=set()
    for d,recs in byd.items():
        opp=defaultdict(set)
        for r in recs:
            h,a=r.get('home',''),r.get('away','')
            if h and a: opp[h].add(a); opp[a].add(h)
        if any(len(v)>1 for v in opp.values()): bad.add(d)
    kept=[g for g in games if g.get('date') not in bad]
    if bad: print('  strip_cartesian removed', len(games)-len(kept), 'games on', sorted(bad))
    return kept

def parse_page(html, year, month):
    soup = BeautifulSoup(html, 'html.parser')
    games = []
    for row in soup.select('table tr'):
        cells = [td.get_text(' ', strip=True) for td in row.select('td')]
        if len(cells) < 3:
            continue
        m = re.search(r'(\d{1,2})[./](\d{1,2})', cells[0])
        if not m:
            continue
        day = int(m.group(2))
        att = 0
        for c in reversed(cells):
            n = re.sub(r'[^\d]', '', c)
            if n and 500 < int(n) < 60000:
                att = int(n); break
        if not att:
            continue
        found = []
        for c in cells:
            for k, v in TEAM_MAP.items():
                if k in c and v not in found:
                    found.append(v)
        if not found:
            continue
        try:
            dt = date(year, month, day)
        except ValueError:
            continue
        dow = (dt.weekday()+1) % 7
        g = {
            'yr': year, 'mo': month, 'day': day,
            'dow': DAYS_KO[dow],
            'home': found[0],
            'away': found[1] if len(found) > 1 else '',
            'att': att,
            'series': 'WE' if dow in [5,6,0] else 'WD',
            'date': dt.isoformat(),
            'dateStr': f'{month}/{day}'
        }
        gid = make_game_id(g)
        if gid:
            g['game_id'] = gid
        games.append(g)
    return games

def fetch_recent():
    """현재 달(월초면 전달 포함)의 경기를 수집해 어제까지만 반환"""
    today = date.today()
    yesterday = today - timedelta(days=1)
    # 볼 달 목록: 현재 달, 그리고 5일 이전이면 전달도(월말 경기 늦반영 대비)
    targets = [(yesterday.year, yesterday.month)]
    if yesterday.day <= 5 and yesterday.month > 1:
        targets.insert(0, (yesterday.year, yesterday.month - 1))

    print(f"최근 경기 수집({yesterday}까지): 대상 월 {targets}")
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            locale='ko-KR'
        )
        page = context.new_page()
        try:
            for yr, mo in targets:
                url = f'https://www.koreabaseball.com/Record/Crowd/GraphDaily.aspx?leId=1&srId=0&seasonId={yr}&monthId={mo:02d}'
                try:
                    page.goto(url, wait_until='domcontentloaded', timeout=20000)
                    page.wait_for_timeout(2000)
                    games = parse_page(page.content(), yr, mo)
                    games = [g for g in games if date.fromisoformat(g['date']) <= yesterday]
                    print(f"  {yr}/{mo:02d}: {len(games)}경기")
                    results.extend(games)
                except Exception as e:
                    print(f"  {yr}/{mo:02d} 수집 실패: {e}")
        finally:
            browser.close()
    return results

def main():
    today = date.today()
    yesterday = today - timedelta(days=1)

    p = Path('kbo_games.json')
    if p.exists():
        data = json.loads(p.read_text(encoding='utf-8'))
        existing = data.get('games', [])
    else:
        data, existing = {}, []

    recent = fetch_recent()
    if not recent:
        print("새 경기 없음 — 기존 데이터 유지")
        return

    # 병합: 기존 보존 + 기존에 없는 (날짜+카드)만 추가
    covered = {matchup_key(g) for g in existing}
    added = []
    for g in recent:
        mk = matchup_key(g)
        if mk in covered:
            continue
        covered.add(mk); added.append(g)

    merged = dedup_clean(existing + added)
    merged = strip_cartesian(merged)
    merged.sort(key=lambda g: g.get('date', ''), reverse=True)
    removed = len(existing) + len(added) - len(merged)

    result = {
        'generated': datetime.now().isoformat(),
        'updated': yesterday.isoformat(),
        'total': len(merged),
        'games': merged
    }
    p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"완료: 총 {len(merged)}경기 (신규 {len(added)}경기 추가, 중복 {removed}건 정리)")

if __name__ == '__main__':
    main()
