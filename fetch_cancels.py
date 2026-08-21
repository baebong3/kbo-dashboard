#!/usr/bin/env python3
"""
KBO 취소 경기 수집기 (cancellations.json)

kbo_games.json에는 '열린 경기'만 들어오므로, 우천·폭염 등으로 취소된 경기는
KBO 공식 「경기일정・결과」 페이지의 [비고] 칸을 읽어 별도로 관리한다.

- Playwright로 페이지를 열고 연도/월 셀렉트를 바꿔가며 표를 읽는다(DOM 파싱).
- 같은 화면을 PNG로도 저장해 눈으로 대조할 수 있게 한다(_cancels_capture/).
- 수집한 달은 기존 항목을 통째로 교체 → 나중에 KBO가 비고를 정정해도 따라간다.

사용:
  python fetch_cancels.py                 # 올해 현재 달(월초면 전달 포함)
  python fetch_cancels.py --months 2026-07 2026-08
  python fetch_cancels.py --season 2026   # 3~11월 전체
  python fetch_cancels.py --dry-run       # 파일 쓰지 않고 변경분만 출력
"""
import json, re, argparse, sys
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

SCHEDULE_URL = 'https://www.koreabaseball.com/Schedule/Schedule.aspx'
OUT = Path('cancellations.json')
SHOT_DIR = Path('_cancels_capture')

TEAMS = ['LG', '두산', '삼성', 'KIA', 'SSG', 'kt', 'KT', '롯데', '한화', 'NC', '키움']
NORM = {'KT': 'kt'}
# 날짜 셀: "08.06(목)"
RE_DATE = re.compile(r'(\d{2})\.(\d{2})')
# 비고가 이 중 하나면 '경기 없음'으로 본다
NOT_CANCEL = {'', '-', '–', '—'}


def norm_team(s):
    s = s.strip()
    return NORM.get(s, s)


def parse_month(page, yr, mo):
    """현재 표시된 표에서 (날짜, 원정, 홈, 구장, 사유) 리스트를 뽑는다."""
    rows = page.query_selector_all('table tbody tr')
    out, cur_day, seen_rows = [], None, 0

    for tr in rows:
        tds = tr.query_selector_all('td')
        if len(tds) < 8:
            continue
        seen_rows += 1

        # 날짜 칸은 그 날의 첫 행에만 있다 → td가 9개면 첫 칸이 날짜
        if len(tds) >= 9:
            m = RE_DATE.search(tds[0].inner_text())
            if m:
                cur_day = int(m.group(2))
                mm = int(m.group(1))
                if mm != mo:          # 달력이 아직 안 바뀐 상태
                    return None, seen_rows
        if cur_day is None:
            continue

        note = tds[-1].inner_text().strip()
        if note in NOT_CANCEL:
            continue

        venue = tds[-2].inner_text().strip()
        # 경기 칸: 뒤에서 7번째 (경기 | 게임센터 | 하이라이트 | TV | 라디오 | 구장 | 비고)
        matchup = tds[-7].inner_text()
        found = []
        for tok in re.split(r'\s*(?:vs|VS)\s*|\n', matchup):
            tok = re.sub(r'[\d\s]', '', tok)
            if tok in TEAMS:
                found.append(norm_team(tok))
        if len(found) < 2:
            print(f'  [주의] 팀 인식 실패 → {yr}-{mo:02d}-{cur_day:02d} "{matchup.strip()}"')
            continue

        out.append({
            'date': f'{yr}-{mo:02d}-{cur_day:02d}',
            'away': found[0], 'home': found[1],   # KBO 표기 = 원정 vs 홈
            'venue': venue, 'reason': note,
        })
    return out, seen_rows


def pick_select(page, values):
    """옵션 값에 values 중 하나가 있는 select 엘리먼트를 찾는다(아이디가 바뀌어도 동작)."""
    for sel in page.query_selector_all('select'):
        opts = {o.get_attribute('value') for o in sel.query_selector_all('option')}
        if opts & set(values):
            return sel
    return None


def fetch(months, headless=True, shots=True):
    SHOT_DIR.mkdir(exist_ok=True)
    got = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            locale='ko-KR', viewport={'width': 1280, 'height': 1600},
        ).new_page()
        try:
            page.goto(SCHEDULE_URL, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(2000)

            for yr, mo in months:
                try:
                    ys = pick_select(page, [str(yr)])
                    ms = pick_select(page, [f'{mo:02d}', str(mo)])
                    if not ys or not ms:
                        print(f'  {yr}-{mo:02d}: 연/월 선택 상자를 찾지 못함 — 건너뜀')
                        continue
                    ys.select_option(str(yr)); page.wait_for_timeout(1800)
                    ms.select_option(f'{mo:02d}'); page.wait_for_timeout(2500)

                    items, nrow = parse_month(page, yr, mo)
                    if items is None:
                        page.wait_for_timeout(2500)          # 포스트백 지연 → 1회 재시도
                        items, nrow = parse_month(page, yr, mo)
                    if items is None or nrow == 0:
                        print(f'  {yr}-{mo:02d}: 표를 읽지 못함 — 기존 데이터 유지')
                        continue

                    if shots:
                        page.screenshot(path=str(SHOT_DIR / f'{yr}-{mo:02d}.png'), full_page=True)
                    got[(yr, mo)] = items
                    print(f'  {yr}-{mo:02d}: {nrow}행 중 취소 {len(items)}건')
                except Exception as e:
                    print(f'  {yr}-{mo:02d} 실패: {e}')
        finally:
            browser.close()
    return got


def merge(got, dry=False):
    data = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {'_meta': {}, 'items': []}
    old = data.get('items', [])
    keep = [c for c in old if (int(c['date'][:4]), int(c['date'][5:7])) not in got]

    new = []
    for (yr, mo) in sorted(got):
        new += got[(yr, mo)]

    def key(c): return (c['date'], c['away'], c['home'])
    added = [c for c in new if key(c) not in {key(o) for o in old}]
    dropped = [c for c in old if (int(c['date'][:4]), int(c['date'][5:7])) in got
               and key(c) not in {key(n) for n in new}]

    merged = sorted(keep + new, key=lambda c: (c['date'], c['home']))
    print(f'\n신규 {len(added)}건 · 삭제 {len(dropped)}건 · 총 {len(merged)}건')
    for c in added:   print(f'  + {c["date"]} {c["away"]}-{c["home"]}({c["venue"]}, {c["reason"]})')
    for c in dropped: print(f'  - {c["date"]} {c["away"]}-{c["home"]}({c["venue"]}) — KBO 비고에서 사라짐')

    if dry:
        print('\n(dry-run: 파일을 쓰지 않았습니다)')
        return

    meta = data.get('_meta', {})
    meta.setdefault('purpose', 'KBO 취소 경기 기록(우천취소·폭염취소 등). kbo_games.json에는 열린 경기만 수집되므로 별도 관리.')
    meta['source'] = 'KBO 공식 「경기일정・결과」 [비고] 칸 — fetch_cancels.py 자동 수집'
    meta['format'] = 'away = 원정, home = 홈 (KBO 일정 표기 "원정 vs 홈"과 동일)'
    meta['coverage'] = f'{merged[0]["date"]} ~ {merged[-1]["date"]}' if merged else ''
    meta['updated'] = date.today().isoformat()
    meta['usage'] = 'index2.html이 로딩 시 fetch — 주간·월간 요약 리포트에서만 언급'

    OUT.write_text(json.dumps({'_meta': meta, 'items': merged}, ensure_ascii=False, indent=2) + '\n',
                   encoding='utf-8')
    print(f'저장 완료: {OUT}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--months', nargs='+', help='YYYY-MM 형식, 여러 개 가능')
    ap.add_argument('--season', type=int, help='해당 연도 3~11월 전체')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-shot', action='store_true', help='검증용 캡처 저장 생략')
    ap.add_argument('--show', action='store_true', help='브라우저 창을 띄워 눈으로 확인')
    a = ap.parse_args()

    if a.season:
        months = [(a.season, m) for m in range(3, 12)]
    elif a.months:
        months = [(int(s[:4]), int(s[5:7])) for s in a.months]
    else:
        t = date.today()
        months = [(t.year, t.month)]
        if t.day <= 5 and t.month > 1:
            months.insert(0, (t.year, t.month - 1))

    print(f'수집 대상: {[f"{y}-{m:02d}" for y, m in months]}')
    got = fetch(months, headless=not a.show, shots=not a.no_shot)
    if not got:
        print('수집 실패 — 기존 cancellations.json 유지'); sys.exit(0)
    merge(got, dry=a.dry_run)


if __name__ == '__main__':
    main()
