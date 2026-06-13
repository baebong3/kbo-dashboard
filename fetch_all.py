"""
KBO 전체 역사 관중 데이터 수집기
- 2000~2024: KBO 공식 GraphDaily.aspx 게임별 스크래핑
- 1982~1999: kbo_history.json 연간 집계 데이터 활용
- 결과: kbo_games.json (업데이트)
"""
import json, re, time
from datetime import datetime, date, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

TEAM_MAP = {
    'LG':'LG','두산':'두산','OB':'두산','MBC':'LG',
    '삼성':'삼성','KIA':'KIA','해태':'KIA','빙그레':'한화',
    'SSG':'SSG','SK':'SSG','롯데':'롯데','kt':'kt','KT':'kt',
    '한화':'한화','NC':'NC','키움':'키움','히어로즈':'키움',
    '넥센':'키움','우리':'키움','현대':'현대','쌍방울':'쌍방울',
    '청보':'청보','삼미':'삼미','태평양':'현대',
}
DAYS_KO = ['일','월','화','수','목','금','토']

def norm_team(name):
    for k, v in TEAM_MAP.items():
        if k in name:
            return v
    return name.strip() or '?'

def parse_html(html, year, month):
    soup = BeautifulSoup(html, 'html.parser')
    games = []
    for row in soup.select('table tr'):
        cells = [td.get_text(' ', strip=True) for td in row.select('td')]
        if len(cells) < 3: continue
        m = re.search(r'(\d{1,2})[./](\d{1,2})', cells[0])
        if not m: continue
        day = int(m.group(2))
        att = 0
        for c in reversed(cells):
            n = re.sub(r'[^\d]', '', c)
            if n and 200 < int(n) < 80000:
                att = int(n); break
        if not att: continue
        found = []
        for c in cells:
            for k in TEAM_MAP:
                v = TEAM_MAP[k]
                if k in c and v not in found:
                    found.append(v)
        if not found: continue
        try:
            dt = date(year, month, day)
        except:
            continue
        dow = (dt.weekday()+1) % 7
        games.append({
            'yr': year, 'mo': month, 'day': day,
            'dow': DAYS_KO[dow],
            'home': found[0], 'away': found[1] if len(found)>1 else '',
            'att': att,
            'series': 'WE' if dow in [5,6,0] else 'WD',
            'date': dt.isoformat(),
            'dateStr': f'{month}/{day}',
        })
    return games

def scrape_year(page, year):
    """한 시즌 전체 스크래핑"""
    all_games = []
    # KBO 사이트에서 월별 수집
    months = range(3, 12) if year < 2000 else range(3, 10)
    for mo in months:
        print(f'    {year}/{mo:02d} ', end='', flush=True)
        try:
            url = f'https://www.koreabaseball.com/Record/Crowd/GraphDaily.aspx?leId=1&srId=0&seasonId={year}&monthId={mo:02d}'
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
            page.wait_for_timeout(1500)
            html = page.content()
            games = parse_html(html, year, mo)
            print(f'{len(games)}경기')
            all_games.extend(games)
        except Exception as e:
            print(f'실패({e})')
        time.sleep(0.8)
    return all_games

def main():
    today = date.today()
    yesterday = today - timedelta(days=1)
    print(f'=== KBO 전체 역사 데이터 수집 ({today}) ===')

    # 기존 데이터 로드
    p = Path('kbo_games.json')
    existing = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
            for g in data.get('games', []):
                key = (g['yr'], g['mo'], g.get('day',0), g['home'])
                existing[key] = g
        except: pass
    print(f'기존 데이터: {len(existing)}경기\n')

    all_new = []
    # 2000~2024 KBO 공식 사이트 스크래핑
    target_years = [y for y in range(2000, yesterday.year+1)]
    print(f'[KBO 공식 사이트 스크래핑: {target_years[0]}~{target_years[-1]}]')

    with sync_playwright() as p_pw:
        browser = p_pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            locale='ko-KR'
        )
        page = ctx.new_page()
        for yr in target_years:
            print(f'\n  [{yr}]')
            end_yr = yesterday if yr == yesterday.year else date(yr, 11, 30)
            games = scrape_year(page, yr)
            games = [g for g in games if date.fromisoformat(g['date']) <= end_yr]
            print(f'  → {yr}: {len(games)}경기 수집')
            all_new.extend(games)
            time.sleep(1)
        browser.close()

    # 병합: 스크래핑 데이터 + 기존 데이터
    new_keys = {(g['yr'],g['mo'],g.get('day',0),g['home']) for g in all_new}
    kept_old = [g for k,g in existing.items() if k not in new_keys]
    merged = sorted(all_new + kept_old, key=lambda g: g['date'], reverse=True)

    result = {
        'generated': datetime.now().isoformat(),
        'updated': yesterday.isoformat(),
        'total': len(merged),
        'note': 'KBO 공식 사이트 실측 데이터 (2000~현재) + 시뮬레이션 (1982~1999)',
        'games': merged,
    }
    Path('kbo_games.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n✅ 완료: {len(merged)}경기 저장')
    print(f'   - 스크래핑 신규: {len(all_new)}경기')
    print(f'   - 기존 유지: {len(kept_old)}경기')

main()
