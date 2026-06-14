"""
visualbaseball.com 관중 수집기
- schedule 페이지 월별 탭 전체 클릭 → 게임 링크 수집
- 각 게임 페이지 관중 정보 추출
실행: python fetch_vb.py
"""
import json, re, time
from datetime import datetime, date, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright, Error as PWError

BASE = "https://visualbaseball.com"

# URL 형식: YYYYMMDD{원정코드}{홈코드}0
TEAM_CODE = {
    'LG':'LG', 'OB':'두산', 'SS':'삼성', 'HT':'KIA',
    'SK':'SSG', 'LT':'롯데', 'KT':'kt', 'HH':'한화',
    'NC':'NC', 'WO':'키움',
    'CB':'현대', 'SB':'쌍방울', 'TG':'청보', 'MBC':'LG',
}
DAYS_KO = ['일','월','화','수','목','금','토']
MONTHS = ['3월','4월','5월','6월','7월','8월','9월']


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
    """월별 탭 전체 클릭해서 게임 링크 수집"""
    print(f'\n[{year}] 스케줄 수집')
    all_links = set()

    try:
        page.goto(f'{BASE}/schedule', wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(1500)

        # 연도 선택
        try:
            sel = page.locator('select')
            if sel.count() > 0:
                sel.first.select_option(str(year))
                page.wait_for_timeout(2000)
            else:
                # 드롭다운 또는 탭
                page.locator(f'text="{year}시즌"').first.click(timeout=5000)
                page.wait_for_timeout(2000)
        except:
            pass

        # 월별 탭 클릭 (3월~9월)
        for mo_label in MONTHS:
            try:
                btn = page.locator(f'text="{mo_label}"').first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    page.wait_for_timeout(1200)
                    # 해당 월 링크 수집
                    links = page.evaluate("""() => {
                        const s = new Set();
                        document.querySelectorAll('a[href]').forEach(a => {
                            const m = (a.getAttribute('href')||'').match(/\\/game\\/(\\d{8}[A-Z]{4}\\d)/);
                            if (m) s.add(m[1]);
                        });
                        return [...s];
                    }""")
                    before = len(all_links)
                    all_links.update(links)
                    print(f'  {mo_label}: +{len(all_links)-before}경기 (누적 {len(all_links)})')
            except:
                pass

        # 전체 탭도 한번 더
        try:
            page.locator('text="전체"').first.click(timeout=3000)
            page.wait_for_timeout(1500)
            for _ in range(6):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(500)
            links = page.evaluate("""() => {
                const s = new Set();
                document.querySelectorAll('a[href]').forEach(a => {
                    const m = (a.getAttribute('href')||'').match(/\\/game\\/(\\d{8}[A-Z]{4}\\d)/);
                    if (m) s.add(m[1]);
                });
                return [...s];
            }""")
            before = len(all_links)
            all_links.update(links)
            if len(all_links) > before:
                print(f'  전체탭: +{len(all_links)-before}경기 추가')
        except:
            pass

    except Exception as e:
        print(f'  오류: {e}')

    result = sorted(all_links)
    print(f'  → {year} 총 {len(result)}경기 링크')
    return result


def get_att(page, gid):
    """게임 페이지에서 관중수 추출"""
    page.goto(f'{BASE}/game/{gid}', wait_until='domcontentloaded', timeout=25000)
    # '구장 XX  관중 23,000  개시...' 패턴 대기
    for _ in range(20):
        page.wait_for_timeout(400)
        att = page.evaluate("""() => {
            const txt = document.body.innerText || '';
            // '관중 23,000' 또는 '관중\\n23,000' 패턴
            const m = txt.match(/관중[\\s\\n]*([\\d,]{3,7})/);
            if (m) return parseInt(m[1].replace(/,/g, ''));
            // script JSON에서
            for (const s of document.querySelectorAll('script')) {
                const t = s.textContent || '';
                const m2 = t.match(/"(?:crowd|attendance)"\\s*:\\s*(\\d+)/i);
                if (m2) { const n=parseInt(m2[1]); if(n>100&&n<80000) return n; }
            }
            return 0;
        }""")
        if att and att > 100:
            return att
    return 0


def make_browser(pw):
    br = pw.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
    page = br.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        locale='ko-KR', viewport={'width':1440,'height':900},
    ).new_page()
    return br, page


def drop_fabricated(games):
    """수집 오류 가드: 한 팀이 하루에 서로 다른 2팀 이상과 경기한 날짜는 통째 제거.
    (한 팀은 하루 한 상대만 — 더블헤더는 같은 상대 2경기라 보존)"""
    from collections import defaultdict
    bydate = defaultdict(list)
    for g in games:
        bydate[g.get('date')].append(g)
    out = []
    for d, recs in bydate.items():
        opp = defaultdict(set)
        for r in recs:
            h, a = r.get('home',''), r.get('away','')
            if h and a:
                opp[h].add(a); opp[a].add(h)
        if all(len(v) <= 1 for v in opp.values()):
            out.extend(recs)
        else:
            print(f'  ⚠ 가짜 매치업 의심 — {d} {len(recs)}건 제외')
    return out


def save(results, path, until):
    valid = sorted(
        drop_fabricated([g for g in results if g.get('att',0)>0]),
        key=lambda g: g['date'], reverse=True
    )
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
    print(f'=== visualbaseball 관중 수집 (2021~{yesterday.year}) ===')
    print(f'실행: {today}  /  수집 기준: ~{yesterday}\n')

    p = Path('kbo_games.json')
    done = {}
    if p.exists():
        try:
            for g in json.loads(p.read_text(encoding='utf-8')).get('games',[]):
                if g.get('att',0)>0 and g.get('game_id'):
                    done[g['game_id']] = g
        except: pass
    print(f'기존 완료: {len(done)}경기 (재실행 시 자동 스킵)\n')

    all_results = list(done.values())
    years = list(range(yesterday.year, 2020, -1))  # 2021~현재

    with sync_playwright() as pw:
        br, page = make_browser(pw)

        for year in years:
            game_ids = collect_links(page, year)

            # 완료 경기만 (어제 이전, 미수집)
            todo = []
            for gid in game_ids:
                if len(gid)<8: continue
                try:
                    d = date(int(gid[:4]),int(gid[4:6]),int(gid[6:8]))
                    if d<=yesterday and gid not in done:
                        todo.append(gid)
                except: pass

            skip = sum(1 for g in done.values() if g.get('yr')==year)
            print(f'  신규: {len(todo)}  /  스킵: {skip}')

            if not todo:
                print(f'  → 모두 완료\n')
                continue

            ok = 0
            for i, gid in enumerate(todo):
                info = parse_game_id(gid)
                if not info: continue

                # 오류 시 브라우저 재시작
                for attempt in range(3):
                    try:
                        att = get_att(page, gid)
                        break
                    except PWError:
                        if attempt < 2:
                            print(f'\n  ⚠ 브라우저 재시작...')
                            try: br.close()
                            except: pass
                            time.sleep(3)
                            br, page = make_browser(pw)
                            att = 0
                        else:
                            att = 0
                    except:
                        att = 0
                        break

                info['att'] = att
                if att > 0:
                    ok += 1
                    all_results.append(info)
                    done[gid] = info

                if (i+1) % 20 == 0 or i+1 == len(todo):
                    saved = save(all_results, p, yesterday)
                    print(f'  [{(i+1)/len(todo)*100:4.0f}%] {i+1}/{len(todo)} | 성공:{ok} | {info["date"]} {info["home"]}(홈)vs{info["away"]}(원정) {att:,} | 저장:{saved}')

                time.sleep(0.4)

            print(f'  → {year} 완료: {ok}/{len(todo)}\n')

        try: br.close()
        except: pass

    total = save(all_results, p, yesterday)
    print(f'\n✅ 최종 저장: {total}경기')

    from collections import defaultdict
    by_year = defaultdict(list)
    for g in all_results:
        if g.get('att',0)>0: by_year[g['yr']].append(g['att'])
    print('\n연도별 요약:')
    for yr in sorted(by_year.keys(), reverse=True):
        gs = by_year[yr]
        print(f'  {yr}: {len(gs):>4}경기  평균 {sum(gs)//len(gs):>6,}명')

    print('\n최근 5경기:')
    valid = sorted(all_results, key=lambda g:g['date'], reverse=True)
    for g in [x for x in valid if x.get('att',0)>0][:5]:
        print(f'  {g["date"]} {g["dow"]}  {g["home"]}(홈) vs {g["away"]}(원정)  {g["att"]:,}명')


if __name__=='__main__':
    main()