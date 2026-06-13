#!/usr/bin/env python3
"""
KBO 관중 데이터 수집기
- GitHub Actions에서 매일 자동 실행
- 먼저 requests로 시도, 실패 시 Playwright 브라우저 사용
- 결과: kbo_games.json
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
DOW_KO = ['일','월','화','수','목','금','토']

def norm_team(s):
    s = s.strip()
    for k, v in TEAM_MAP.items():
        if k in s:
            return v
    return s or ''

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
            games.append({
                'yr': year, 'mo': month, 'day': day,
                'dow': dow_kr,
                'home': home, 'away': away,
                'att': att,
                'series': 'WE' if dow >= 4 else 'WD',
                'date': dt.isoformat(),
                'dateStr': f'{month}/{day}',
            })
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
        except:
            pass
    return {'games': []}

def main():
    today = date.today()
    yesterday = today - timedelta(days=1)
    print(f'=== KBO 관중 데이터 수집 ({today} 실행, {yesterday}까지 집계) ===\n')

    existing = load_existing()
    existing_keys = {(g['yr'], g['mo'], g['day'], g['home'])
                     for g in existing.get('games', [])}

    all_games = []
    seasons = {
        2025: range(3, 10),   # 3~9월 전체
        2026: range(3, today.month + 1),  # 개막~이번 달
    }

    for year, months in seasons.items():
        print(f'[{year} 시즌]')
        for mo in months:
            games = fetch_month(year, mo)
            # 오늘 이후 데이터 제외
            games = [g for g in games
                     if date.fromisoformat(g['date']) <= yesterday]
            all_games.extend(games)
            time.sleep(0.6)
        print()

    if not all_games:
        print('⚠ 새 데이터 없음 — 기존 데이터 유지')
        return

    # 기존 데이터와 병합 (새 데이터 우선)
    new_keys = {(g['yr'], g['mo'], g['day'], g['home']) for g in all_games}
    kept_old = [g for g in existing.get('games', [])
                if (g['yr'], g['mo'], g['day'], g['home']) not in new_keys]
    merged = sorted(all_games + kept_old,
                    key=lambda g: g['date'], reverse=True)

    out = {
        'generated': datetime.now().isoformat(),
        'updated': yesterday.isoformat(),
        'total': len(merged),
        'games': merged,
    }
    Path('kbo_games.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'✅ 저장 완료 — 총 {len(merged)}경기 (신규 {len(all_games)}경기)')

if __name__ == '__main__':
    main()
