#!/usr/bin/env python3
"""
KBO 포스트시즌 수집기 (kbo_postseason.json) — 게임센터 내부 API 방식

[방식 이력 — 실패한 길을 다시 가지 않기 위한 기록]
  · 일정표(Schedule.aspx) 스크래핑: 실패 (2026-06 v1 — gameId 0개)
  · 관중페이지(GraphDaily) srId 파라미터: 실패 (URL의 srId·seasonId·monthId를 무시하고
    현재 시즌 전체를 반환 — 2026-08-21 재확인)
  · 게임센터 내부 API: 성공 (v5, 기존 83경기가 이 방식으로 수집됨)

[확정 사실 — 2026-06-28 실측으로 검증]
  · POST /ws/Main.asmx/GetKboGameList (leId, srId, date=YYYYMMDD) → 그날 경기 목록
  · sr_id 매핑: 0=정규, 1=시범, 3=준PO, 4=와일드카드, 5=플레이오프, 6=연습, 7=한국시리즈
    (게임센터 소스 주석과 달리 실제 응답은 4=WC·5=PO·7=KS — 2024년 실측으로 확정)
  · 스코어: 목록의 T_SCORE_CN(원정)/B_SCORE_CN(홈) · 구장: S_NM · 팀: AWAY_NM/HOME_NM
  · 관중: Main.aspx?gameDate=...&gameId=...&section=REVIEW 렌더 후 '관중 : N,NNN' 파싱
    (gameDate 없이 ReviewNew.aspx 직접 호출은 실패)

사용:
  python fetch_postseason.py --year 2025 --dry-run   # 검증(저장 안 함)
  python fetch_postseason.py                          # 올해 수집·병합
"""
import json, re, argparse, sys
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path('kbo_postseason.json')
BASE = 'https://www.koreabaseball.com'
SR_SERIES = {'3': '준PO', '4': 'WC', '5': 'PO', '7': 'KS'}
# 규정상 경기 수 — 벗어나면 수집 누락/과잉(준PO·PO 5전3선승, KS 7전4선승)
SERIES_MIN = {'WC': 1, '준PO': 3, 'PO': 3, 'KS': 4}
SERIES_MAX = {'WC': 2, '준PO': 5, 'PO': 5, 'KS': 7}


def norm(nm):
    return {'SK': 'SSG', 'KT': 'kt', '넥센': '키움', '우리': '키움', '히어로즈': '키움'}.get(nm, nm)


def toint(x):
    try:
        return int(str(x).strip())
    except (ValueError, TypeError):
        return None


def dig_games(j):
    if not isinstance(j, dict):
        return None
    for o in (j, j.get('d') if isinstance(j.get('d'), dict) else None):
        if isinstance(o, dict):
            for k in ('game', 'Game', 'GAME', 'rows', 'list'):
                if isinstance(o.get(k), list):
                    return o[k]
    return None


def gv(g, *keys):
    for k in keys:
        if k in g and g[k] not in (None, ''):
            return g[k]
    return None


def get_list(page, ds):
    return page.evaluate("""async (d)=>{ try{
        const r = await fetch('/ws/Main.asmx/GetKboGameList',{method:'POST',
          headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'},
          body:'leId=1&srId=0,1,3,4,5,6,7,8,9&date='+d});
        return await r.json(); }catch(e){ return {err:String(e)}; } }""", ds)


def get_att(page, gid, dbg=False):
    gd = gid[:8]
    page.goto(f'{BASE}/Schedule/GameCenter/Main.aspx?gameDate={gd}&gameId={gid}&section=REVIEW',
              wait_until='domcontentloaded', timeout=30000)
    txt = ''
    for _ in range(24):
        page.wait_for_timeout(500)
        txt = page.evaluate("()=>document.body.innerText||''")
        if '관중' in txt:
            break
    if dbg:
        i = txt.find('구장')
        i = i if i >= 0 else txt.find('관중')
        print('  [리뷰 디버그]', repr(txt[max(0, i - 12):i + 70]) if i >= 0
              else '관중/구장 없음, 앞부분: ' + repr(txt[:200]))
    ma = re.search(r'관중\s*[:：]?\s*([\d,]{3,7})', txt)
    return int(ma.group(1).replace(',', '')) if ma else None


def collect(yr, d_from, d_to):
    out = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True)
        pg = br.new_context(locale='ko-KR').new_page()
        try:
            pg.goto(f'{BASE}/Schedule/GameCenter/Main.aspx', wait_until='domcontentloaded', timeout=30000)
            pg.wait_for_timeout(1500)

            found, d = {}, d_from
            while d <= d_to:
                games = dig_games(get_list(pg, d.strftime('%Y%m%d')))
                for g in (games or []):
                    sr = str(gv(g, 'SR_ID', 'sr_id') or '')
                    gid = gv(g, 'G_ID', 'g_id')
                    if not gid or sr not in SR_SERIES:
                        continue
                    if str(gv(g, 'GAME_RESULT_CK') or '1') == '0':   # 미완료
                        continue
                    # 우천취소 등 취소 경기: CANCEL_SC_ID != '0'. 차수 계산에서도 빼야 한다
                    # (2025 준PO2 10/10·PO1 10/17 우천취소 — 포함하면 이후 차전 번호가 밀림)
                    cancel = str(gv(g, 'CANCEL_SC_ID') or '0') != '0'
                    found[gid] = {'cancel': cancel} | {
                        'gid': gid, 'sr': sr,
                        'date': f'{gid[:4]}-{gid[4:6]}-{gid[6:8]}',
                        'away': norm(gv(g, 'AWAY_NM', 'away_nm') or ''),
                        'home': norm(gv(g, 'HOME_NM', 'home_nm') or ''),
                        'venue': gv(g, 'S_NM', 's_nm'),
                        'as': toint(gv(g, 'T_SCORE_CN')), 'hs': toint(gv(g, 'B_SCORE_CN')),
                    }
                d += timedelta(days=1)

            allrows = sorted(found.values(), key=lambda x: x['date'])
            canc = [f for f in allrows if f['cancel']]
            rows = [f for f in allrows if not f['cancel']]
            print(f'[{yr}] 포스트시즌 {len(rows)}경기 확인'
                  + (f' (취소 {len(canc)}경기 제외: '
                     + ' · '.join(f'{c["date"][5:]} {c["away"]}@{c["home"]}' for c in canc) + ')' if canc else ''))
            cnt, first = {}, True
            for f in rows:
                att = get_att(pg, f['gid'], dbg=first)
                first = False
                series = SR_SERIES[f['sr']]
                cnt[series] = cnt.get(series, 0) + 1
                out.append({'yr': yr, 'date': f['date'], 'series': series, 'game_no': cnt[series],
                            'home': f['home'], 'away': f['away'], 'att': att,
                            'venue': f['venue'], 'home_score': f['hs'], 'away_score': f['as']})
                sc = f"{f['as']}:{f['hs']}" if f['hs'] is not None else '?'
                print(f'  {f["date"]} [{series}{cnt[series]}] {f["away"]}@{f["home"]} {sc} '
                      f'관중 {f"{att:,}" if att else "파싱 실패"} ({f["venue"]})')
        finally:
            br.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, default=date.today().year)
    ap.add_argument('--from', dest='dfrom', default=None, help='YYYY-MM-DD (기본: 그해 9/20)')
    ap.add_argument('--to', dest='dto', default=None, help='YYYY-MM-DD (기본: 그해 11/30)')
    ap.add_argument('--dry-run', '--probe', dest='dry', action='store_true')
    a = ap.parse_args()

    d_from = date.fromisoformat(a.dfrom) if a.dfrom else date(a.year, 9, 20)
    d_to = min(date.fromisoformat(a.dto) if a.dto else date(a.year, 11, 30), date.today())
    if d_from > d_to:
        print(f'{a.year}년 조회 구간이 아직 오지 않았습니다({d_from}~) — 종료'); sys.exit(0)

    print(f'{a.year}년 포스트시즌 수집: {d_from} ~ {d_to}')
    rows = collect(a.year, d_from, d_to)
    got = [g for g in rows if g['att']]
    fail = len(rows) - len(got)
    if fail:
        print(f'\n[주의] 관중 파싱 실패 {fail}경기 — 저장에서 제외됩니다.'
              ' 정상 개최 경기인데 실패했다면 리뷰 페이지 형식 변경 가능성이 있으니 출력을 확인하세요.')

    # 규정 대조
    cnt = {}
    for g in rows:
        cnt[g['series']] = cnt.get(g['series'], 0) + 1
    bad = [(s, n) for s, n in cnt.items() if n < SERIES_MIN[s] or n > SERIES_MAX[s]]
    if bad:
        print('[경고] 규정과 맞지 않는 시리즈(진행 중이면 정상): '
              + ' · '.join(f'{s} {n}경기(규정 {SERIES_MIN[s]}~{SERIES_MAX[s]})' for s, n in bad))

    if a.dry:
        print('\n(dry-run: 저장하지 않았습니다)'); return
    if not got:
        print('저장할 경기 없음 — 기존 파일 유지'); return

    data = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {'games': []}
    old = data.get('games', [])
    key = lambda g: (g['date'], g['home'], g['away'])
    keep = [g for g in old if key(g) not in {key(x) for x in got}]
    merged = sorted(keep + got, key=lambda g: g['date'])
    data.update({'games': merged, 'total': len(merged), 'updated': date.today().isoformat(),
                 'source': 'KBO 게임센터 내부 API(GetKboGameList + REVIEW) — fetch_postseason.py'})
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'\n저장 완료: {OUT} (총 {len(merged)}경기, 신규·갱신 {len(got)}건)')


if __name__ == '__main__':
    main()