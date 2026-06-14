#!/usr/bin/env python3
"""
KBO 관중 데이터 수집기
- GitHub Actions에서 매일 자동 실행
- 먼저 requests로 시도, 실패 시 Playwright 브라우저 사용
- 결과: kbo_games.json

[2026-06 수정] 중복 누적 버그 해결
  · 새 경기에 표준 game_id(YYYYMMDD+원정코드+홈코드+더블헤더번호)를 부여
  · 병합은 game_id 기준(더블헤더 보존). 기존 데이터(날씨 등 포함)는 '진실의 원천'으로 보존하고
    기존에 없는 (날짜+카드)만 새로 추가 → 매 실행마다 한 시즌씩 쌓이던 문제 제거
  · 저장 직전 최종 중복 청소(dedup_clean)로, 이미 누적된 파일도 1회 실행으로 정리됨
"""
import json, re, time, sys, os
from datetime import datetime, date, timedelta
from pathlib import Path

# ── 설정 ─────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.koreabaseball.com/",
}
TEAM_MAP = {
    'LG':'LG','두산':'두산','삼성':'삼성','KIA':'KIA','SSG':'SSG',
    'kt':'kt','KT':'kt','롯데':'롯데','한화':'한화','NC':'NC','키움':'키움',
    'LG트윈스':'LG','두산베어스':'두산','삼성라이온즈':'삼성','KIA타이거즈':'KIA',
    'SSG랜더스':'SSG','kt wiz':'kt','KT위즈':'kt','롯데자이언츠':'롯데',
    '한화이글스':'한화','NC다이노스':'NC','키움히어로즈':'키움',
}
# KBO 공식 game_id 팀 코드 (기존 kbo_games.json에서 검증된 매핑)
TEAM_CODE = {
    'LG':'LG','두산':'OB','KIA':'HT','삼성':'SS','롯데':'LT',
    'SSG':'SK','키움':'WO','한화':'HH','NC':'NC','kt':'KT',
}
DOW_KO = ['일','월','화','수','목','금','토']

def norm_team(s):
    s = s.strip()
    for k, v in TEAM_MAP.items():
        if k in s:
            return v
    return s or ''

# ── 중복 제거용 키 ────────────────────────────────────────────
def make_game_id(g):
    """표준 game_id 생성: YYYYMMDD + 원정코드 + 홈코드 + 더블헤더번호(기본 0)"""
    d = str(g.get('date', '')).replace('-', '')
    ac = TEAM_CODE.get(g.get('away', ''), 'XX')
    hc = TEAM_CODE.get(g.get('home', ''), 'XX')
    return f"{d}{ac}{hc}{g.get('dh', 0)}"

def matchup_key(g):
    """날짜 + 정렬한 팀쌍 (홈/원정 순서가 뒤바뀌어도 같은 경기로 인식)"""
    teams = '-'.join(sorted([g.get('home', ''), g.get('away', '')]))
    return f"{g.get('date')}|{teams}"

def dedup_clean(games):
    """
    최종 중복 청소.
    1) game_id 보유 경기 우선 채택(더블헤더는 game_id가 달라 모두 보존)
    2) game_id 없는 잔여 경기는, 같은 (날짜+카드)가 아직 없을 때만 채택
       → 과거 버그로 쌓인 'game_id 없는 중복본'이 여기서 제거됨
    """
    seen_id, seen_match, out = set(), set(), []
    for g in games:
        gid = g.get('game_id')
        if not gid:
            continue
        if gid in seen_id:
            continue
        seen_id.add(gid)
        out.append(g)
        seen_match.add(matchup_key(g))
    for g in games:
        if g.get('game_id'):
            continue
        mk = matchup_key(g)
        if mk in seen_match:
            continue
        seen_match.add(mk)
        out.append(g)
    return out

def parse_crowd_html(html, year, month):
    """KBO 일별관중 페이지 파싱"""
    from bs4 import BeautifulSoup
    games = []
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for row in soup.select('table tr'):
            cells = [td.get_text(' ', strip=True) for td in row.select('td')]
            if len(cells) < 3:
                continue
            # 날짜 추출
            dm = re.search(r'(\d{1,2})[./](\d{1,2})', cells[0])
            if not dm:
                continue
            day = int(dm.group(2))
            # 관중수 추출 (뒤에서부터 첫 번째 숫자 컬럼)
            att = 0
            for c in reversed(cells):
                n = re.sub(r'[^\d]', '', c)
                if n and 500 < int(n) < 60000:
                    att = int(n)
                    break
            if not att:
                continue
            # 팀 추출
            teams = []
            for c in cells[1:]:
                nm = norm_team(c)
                if nm in TEAM_MAP.values() and nm not in teams:
                    teams.append(nm)
            if not teams:
                continue
            home = teams[0]
            away = teams[1] if len(teams) > 1 else ''
            dt = date(year, month, day)
            dow = dt.weekday()  # 0=월
            dow_kr = ['월','화','수','목','금','토','일'][dow]
            g = {
                'yr': year, 'mo': month, 'day': day,
                'dow': dow_kr,
                'home': home, 'away': away,
                'att': att,
                'series': 'WE' if dow >= 4 else 'WD',
                'date': dt.isoformat(),
                'dateStr': f'{month}/{day}',
            }
            g['game_id'] = make_game_id(g)   # ← 표준 game_id 부여(중복 제거 핵심)
            games.append(g)
    except Exception as e:
        print(f'  파싱 오류: {e}')
    return games

def fetch_with_requests(year, month):
    """requests로 시도 (빠름)"""
    import requests
    url = f'https://www.koreabaseball.com/Record/Crowd/GraphDaily.aspx'
    params = {'leId':'1','srId':'0','seasonId':str(year),'monthId':f'{month:02d}'}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=12)
        if r.status_code == 200 and len(r.text) > 500:
            games = parse_crowd_html(r.text, year, month)
            if games:
                return games
    except Exception as e:
        print(f'  requests 실패: {e}')
    return None

def fetch_with_playwright(year, month):
    """Playwright 브라우저로 시도 (확실하지만 느림)"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    url = f'https://www.koreabaseball.com/Record/Crowd/GraphDaily.aspx?leId=1&srId=0&seasonId={year}&monthId={month:02d}'
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=HEADERS['User-Agent'])
            page.goto(url, wait_until='networkidle', timeout=20000)
            page.wait_for_timeout(1500)
            html = page.content()
            browser.close()
        games = parse_crowd_html(html, year, month)
        return games if games else None
    except Exception as e:
        print(f'  Playwright 실패: {e}')
        return None

def fetch_month(year, month):
    """한 달치 데이터 수집 (requests 우선, 실패 시 Playwright)"""
    print(f'  {year}/{month:02d} ', end='', flush=True)

    # 1순위: requests
    games = fetch_with_requests(year, month)
    if games:
        print(f'✓ requests ({len(games)}경기)')
        return games

    # 2순위: Playwright
    print('→ Playwright... ', end='', flush=True)
    games = fetch_with_playwright(year, month)
    if games:
        print(f'✓ ({len(games)}경기)')
        return games

    print('✗ 실패')
    return []

def load_existing():
    """기존 kbo_games.json 로드"""
    p = Path('kbo_games.json')
    if p.exists():
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {'games': []}

def main():
    today = date.today()
    yesterday = today - timedelta(days=1)
    print(f'=== KBO 관중 데이터 수집 ({today} 실행, {yesterday}까지 집계) ===\n')

    existing = load_existing()
    existing_games = existing.get('games', [])

    # 새로 수집
    all_games = []
    seasons = {
        2025: range(3, 10),               # 3~9월 전체
        2026: range(3, today.month + 1),  # 개막~이번 달
    }
    for year, months in seasons.items():
        print(f'[{year} 시즌]')
        for mo in months:
            games = fetch_month(year, mo)
            games = [g for g in games
                     if date.fromisoformat(g['date']) <= yesterday]  # 오늘 이후 제외
            all_games.extend(games)
            time.sleep(0.6)
        print()

    # ── 병합 (중복 누적 방지) ─────────────────────────────────
    # 원칙: 기존 데이터(날씨·game_id 등 포함)는 그대로 보존하고,
    #       기존에 없는 (날짜+카드)만 새로 추가한다.
    covered = {matchup_key(g) for g in existing_games}
    added = []
    if all_games:
        for g in all_games:
            mk = matchup_key(g)
            if mk in covered:
                continue                  # 이미 있는 경기 → 다시 넣지 않음(중복 방지)
            covered.add(mk)
            added.append(g)

    # 기존 + 신규를 합치고 최종 중복 청소(이미 쌓인 중복도 정리)
    merged = dedup_clean(existing_games + added)
    merged.sort(key=lambda g: g.get('date', ''), reverse=True)

    removed = len(existing_games) + len(added) - len(merged)

    out = {
        'generated': datetime.now().isoformat(),
        'updated': yesterday.isoformat(),
        'total': len(merged),
        'source': 'koreabaseball.com',
        'games': merged,
    }
    Path('kbo_games.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'✅ 저장 완료 — 총 {len(merged)}경기 '
          f'(신규 {len(added)}경기 추가, 중복 {removed}건 정리)')

if __name__ == '__main__':
    main()