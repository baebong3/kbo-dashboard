"""
visualbaseball.com 관중 수집기 (검증 강화판)
- schedule 페이지에서 게임 링크 수집(과수집되어도 OK — 아래 검증으로 걸러짐)
- 각 게임 페이지가 '진짜 완료 경기'인지 검증 후에만 관중 채택:
    ① 페이지에 그 game_id의 날짜(MM.DD)가 보이고
    ② 양팀 이름이 모두 보이고
    ③ '종료' + 점수(d:d)가 있고
    ④ 관중 수가 있을 것
  → 가짜 대진/스테일(이전 경기 잔상) 읽기를 차단
- REFETCH_YEARS 에 든 연도는 기존 데이터를 버리고 처음부터 다시 검증 수집
실행: python fetch_vb.py
"""
import json, re, time
from datetime import datetime, date, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright, Error as PWError

BASE = "https://visualbaseball.com"

# 이 연도들은 기존 데이터를 무시하고 처음부터 재수집(검증)
REFETCH_YEARS = {2025, 2026}

TEAM_CODE = {
    'LG':'LG', 'OB':'두산', 'SS':'삼성', 'HT':'KIA',
    'SK':'SSG', 'LT':'롯데', 'KT':'kt', 'HH':'한화',
    'NC':'NC', 'WO':'키움',
    'CB':'현대', 'SB':'쌍방울', 'TG':'청보', 'MBC':'LG',
}
DAYS_KO = ['일','월','화','수','목','금','토']
MONTHS = ['3월','4월','5월','6월','7월','8월','9월','10월']


def parse_game_id(gid):
    m = re.match(r'(\d{4})(\d{2})(\d{2})([A-Z]{2})([A-Z]{2})\d', gid)
    if not m: return None
    yr, mo, day, away_code, home_code = int(m[1]),int(m[2]),int(m[3]),m[4],m[5]
    try:
        dt = date(yr, mo, day)
        dow = (dt.weekday()+1) % 7
        return {
            'yr':yr, 'mo':mo, 'day':day, 'dow':DAYS_KO[dow],
            'away': TEAM_CODE.get(away_code, away_code),
            'home': TEAM_CODE.get(home_code, home_code),
            'att':0, 'game_id':gid,
            'date':dt.isoformat(), 'dateStr':f'{mo}/{day}',
            'series':'WE' if dow in [5,6,0] else 'WD',
        }
    except: return None


def collect_links(page, year):
    print(f'\n[{year}] 스케줄 수집')
    all_links = set()
    try:
        page.goto(f'{BASE}/schedule', wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(1500)
        try:
            sel = page.locator('select')
            if sel.count() > 0:
                sel.first.select_option(str(year)); page.wait_for_timeout(2000)
            else:
                page.locator(f'text="{year}시즌"').first.click(timeout=5000); page.wait_for_timeout(2000)
        except: pass

        for mo_label in MONTHS:
            try:
                btn = page.locator(f'text="{mo_label}"').first
                if btn.is_visible(timeout=2000):
                    btn.click(); page.wait_for_timeout(1200)
                    links = page.evaluate("""() => {
                        const s = new Set();
                        document.querySelectorAll('a[href]').forEach(a => {
                            const m = (a.getAttribute('href')||'').match(/\\/game\\/(\\d{8}[A-Z]{4}\\d)/);
                            if (m) s.add(m[1]);
                        });
                        return [...s];
                    }""")
                    all_links.update(links)
            except: pass
        try:
            page.locator('text="전체"').first.click(timeout=3000); page.wait_for_timeout(1500)
            for _ in range(6):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)"); page.wait_for_timeout(500)
            links = page.evaluate("""() => {
                const s = new Set();
                document.querySelectorAll('a[href]').forEach(a => {
                    const m = (a.getAttribute('href')||'').match(/\\/game\\/(\\d{8}[A-Z]{4}\\d)/);
                    if (m) s.add(m[1]);
                });
                return [...s];
            }""")
            all_links.update(links)
        except: pass
    except Exception as e:
        print(f'  오류: {e}')

    # 해당 연도 game_id만
    result = sorted(g for g in all_links if g[:4] == str(year))
    print(f'  → {year} 수집 링크 {len(result)}개 (검증 전)')
    return result


def get_att(page, info):
    """게임 페이지가 진짜 완료 경기인지 검증 후 관중수 반환. 아니면 0."""
    gid = info['game_id']
    home, away = info['home'], info['away']
    date_dot = f"{info['mo']:02d}.{info['day']:02d}"   # 예: 06.05
    page.goto(f'{BASE}/game/{gid}', wait_until='domcontentloaded', timeout=25000)
    for _ in range(18):
        page.wait_for_timeout(400)
        res = page.evaluate("""(args) => {
            const [home, away, dateDot] = args;
            const txt = document.body.innerText || '';
            const hasFinal = /종료/.test(txt);
            const hasScore = /\\d+\\s*[:：]\\s*\\d+/.test(txt);
            const T = txt.toUpperCase();
            const teamsOk  = T.includes(home.toUpperCase()) && T.includes(away.toUpperCase());
            const dateOk   = txt.includes(dateDot);   // 그 경기의 실제 날짜가 페이지에 있어야(스테일 차단)
            let att = 0;
            const m = txt.match(/관중[\\s\\n]*([\\d,]{3,7})/);
            if (m) att = parseInt(m[1].replace(/,/g, ''));
            return {att, hasFinal, hasScore, teamsOk, dateOk};
        }""", [home, away, date_dot])
        if (res['att'] and res['att'] > 100 and res['hasFinal']
                and res['hasScore'] and res['teamsOk'] and res['dateOk']):
            return res['att']
    return 0


def make_browser(pw):
    br = pw.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
    page = br.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        locale='ko-KR', viewport={'width':1440,'height':900},
    ).new_page()
    return br, page


def save(results, path, until):
    valid = sorted([g for g in results if g.get('att',0) > 0],
                   key=lambda g: g['date'], reverse=True)
    path.write_text(json.dumps({
        'generated': datetime.now().isoformat(),
        'updated': until.isoformat(),
        'total': len(valid),
        'source': 'visualbaseball.com',
        'games': valid,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return len(valid)


def main():
    today = date.today()
    yesterday = today - timedelta(days=1)
    print(f'=== visualbaseball 관중 수집(검증판) 2021~{yesterday.year} ===')
    print(f'재수집(검증) 연도: {sorted(REFETCH_YEARS)}\n')

    p = Path('kbo_games.json')
    done = {}
    if p.exists():
        for g in json.loads(p.read_text(encoding='utf-8')).get('games', []):
            # REFETCH_YEARS 는 기존 데이터를 버림(가짜 제거) → done 에 넣지 않음
            if g.get('att',0) > 0 and g.get('game_id') and g.get('yr') not in REFETCH_YEARS:
                done[g['game_id']] = g
    print(f'유지(스킵) 기존: {len(done)}경기 / 재수집 연도는 전부 새로 검증\n')

    all_results = list(done.values())
    years = [y for y in range(yesterday.year, 2015, -1) if y != 2020]

    with sync_playwright() as pw:
        br, page = make_browser(pw)
        for year in years:
            game_ids = collect_links(page, year)
            todo = []
            for gid in game_ids:
                info = parse_game_id(gid)
                if not info: continue
                try:
                    if date(info['yr'],info['mo'],info['day']) <= yesterday and gid not in done:
                        todo.append(info)
                except: pass
            print(f'  검증 대상: {len(todo)}')
            if not todo:
                print('  → 스킵\n'); continue

            ok = rej = 0
            for i, info in enumerate(todo):
                att = 0
                for attempt in range(3):
                    try:
                        att = get_att(page, info); break
                    except PWError:
                        if attempt < 2:
                            try: br.close()
                            except: pass
                            time.sleep(3); br, page = make_browser(pw)
                        else: att = 0
                    except: att = 0; break
                if att > 0:
                    info['att'] = att; ok += 1
                    all_results.append(info); done[info['game_id']] = info
                else:
                    rej += 1   # 가짜/미완료/스테일 → 버림
                if (i+1) % 20 == 0 or i+1 == len(todo):
                    saved = save(all_results, p, yesterday)
                    print(f'  [{(i+1)/len(todo)*100:4.0f}%] {i+1}/{len(todo)} | 채택:{ok} 기각:{rej} | 저장:{saved}')
                time.sleep(0.35)
            print(f'  → {year}: 채택 {ok} / 기각 {rej}\n')
        try: br.close()
        except: pass

    total = save(all_results, p, yesterday)
    from collections import defaultdict
    by_year = defaultdict(list)
    for g in all_results:
        if g.get('att',0) > 0: by_year[g['yr']].append(g['att'])
    print(f'\n최종 저장: {total}경기\n연도별:')
    for yr in sorted(by_year, reverse=True):
        gs = by_year[yr]
        print(f'  {yr}: {len(gs):>4}경기  평균 {sum(gs)//len(gs):>6,}')

if __name__ == '__main__':
    main()
