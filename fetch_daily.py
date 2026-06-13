"""
KBO 일일 관중 업데이트 스크립트
- 어제 경기(5경기)만 가져와서 kbo_games.json에 추가
- 기존 전체 수집본이 있으면 그 위에 덮어씀
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
DAYS_KO = ['일','월','화','수','목','금','토']

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
                att = int(n)
                break
        if not att:
            continue
        found = []
        for c in cells:
            for k, v in TEAM_MAP.items():
                if k in c and v not in found:
                    found.append(v)
        if not found:
            continue
        dt = date(year, month, day)
        dow = (dt.weekday()+1) % 7  # 0=일 기준
        games.append({
            'yr': year, 'mo': month, 'day': day,
            'dow': DAYS_KO[dow],
            'home': found[0],
            'away': found[1] if len(found) > 1 else '',
            'att': att,
            'series': 'WE' if dow in [5,6,0] else 'WD',
            'date': dt.isoformat(),
            'dateStr': f'{month}/{day}'
        })
    return games

def fetch_yesterday():
    today = date.today()
    yesterday = today - timedelta(days=1)
    year, month = yesterday.year, yesterday.month
    
    print(f"어제({yesterday}) 경기 수집 중...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            locale='ko-KR'
        )
        page = context.new_page()
        try:
            url = f'https://www.koreabaseball.com/Record/Crowd/GraphDaily.aspx?leId=1&srId=0&seasonId={year}&monthId={month:02d}'
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
            page.wait_for_timeout(2000)
            html = page.content()
            all_month = parse_page(html, year, month)
            # 어제 경기만 필터
            yest_games = [g for g in all_month if g['day'] == yesterday.day]
            print(f"  → {len(yest_games)}경기 수집")
            return yest_games
        except Exception as e:
            print(f"  → 수집 실패: {e}")
            return []
        finally:
            browser.close()

def main():
    today = date.today()
    yesterday = today - timedelta(days=1)
    
    # 기존 JSON 로드
    p = Path('kbo_games.json')
    if p.exists():
        data = json.loads(p.read_text(encoding='utf-8'))
        existing = data.get('games', [])
    else:
        data = {}
        existing = []
    
    # 어제 경기 수집
    new_games = fetch_yesterday()
    
    if not new_games:
        print("수집 실패 — 기존 데이터 유지")
        return
    
    # 중복 제거 후 병합
    new_keys = {(g['yr'], g['mo'], g['day'], g['home']) for g in new_games}
    kept = [g for g in existing if (g['yr'], g['mo'], g['day'], g['home']) not in new_keys]
    merged = sorted(new_games + kept, key=lambda g: g['date'], reverse=True)
    
    result = {
        'generated': datetime.now().isoformat(),
        'updated': yesterday.isoformat(),
        'total': len(merged),
        'games': merged
    }
    p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"✅ 완료: {len(merged)}경기 (어제 {len(new_games)}경기 추가)")

main()
