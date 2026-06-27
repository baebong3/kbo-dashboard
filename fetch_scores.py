"""
게임 페이지에서 원정/홈 점수(득점) 추출 — 순위 분석용 (검증 모드 우선)
- TEST_LIMIT > 0 이면 그 개수만 뽑아서 화면에 출력(파일 저장 안 함) → 추출이 맞는지 먼저 확인
- 확인되면 TEST_LIMIT = 0 으로 두고 전체 실행 → kbo_games.json 의 2025·2026 경기에
  away_score / home_score 추가 (이미 있는 건 스킵)
실행: python fetch_scores.py
"""
import json, time
from datetime import date
from pathlib import Path
from playwright.sync_api import sync_playwright, Error as PWError

BASE = "https://visualbaseball.com"
TARGET_YEARS = {2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025, 2026}
TEST_LIMIT = 0           # 0 이면 전체 실행, >0 이면 그 개수만 검증 출력

def get_score(page, info):
    gid, home, away = info['game_id'], info['home'], info['away']
    date_dot = f"{info['mo']:02d}.{info['day']:02d}"
    page.goto(f"{BASE}/game/{gid}", wait_until='domcontentloaded', timeout=25000)
    for _ in range(18):
        page.wait_for_timeout(400)
        res = page.evaluate("""(args) => {
            const [home, away, dateDot] = args;
            const txt = document.body.innerText || '';
            if (!/종료/.test(txt)) return null;
            if (!txt.includes(dateDot)) return null;   // 스테일 차단

            // 방법1) 박스스코어 표에서 R(득점) 컬럼
            const tables = [...document.querySelectorAll('table')];
            for (const t of tables) {
                const heads = [...t.querySelectorAll('th, thead td')].map(x => (x.innerText||'').trim());
                const ri = heads.indexOf('R');
                if (ri < 0) continue;
                const rows = [...t.querySelectorAll('tbody tr')];
                if (rows.length < 2) continue;
                const c0 = [...rows[0].querySelectorAll('td,th')].map(x => (x.innerText||'').trim());
                const c1 = [...rows[1].querySelectorAll('td,th')].map(x => (x.innerText||'').trim());
                // 본문 셀 수가 헤더와 같다고 가정, 다르면 뒤에서부터 R/H/E/B 4칸 중 첫칸
                let a = parseInt(c0[ri]), h = parseInt(c1[ri]);
                if (isNaN(a) || isNaN(h)) {
                    // 뒤에서 4번째(R H E B 가정)
                    a = parseInt(c0[c0.length-4]); h = parseInt(c1[c1.length-4]);
                }
                if (!isNaN(a) && !isNaN(h)) return {away_score:a, home_score:h, how:'box'};
            }
            // 방법2) 큰 점수 표시 "원정 : 홈" (시간 14:00 오인 방지 위해 공백 포함 콜론만)
            const m = txt.match(/(\\d{1,2})\\s+[:：]\\s+(\\d{1,2})/);
            if (m) return {away_score:parseInt(m[1]), home_score:parseInt(m[2]), how:'big'};
            return null;
        }""", [home, away, date_dot])
        if res and res.get('away_score') is not None and res.get('home_score') is not None:
            return res['away_score'], res['home_score'], res.get('how','')
    return None, None, ''

def main():
    p = Path('kbo_games.json')
    data = json.loads(p.read_text(encoding='utf-8'))
    games = data.get('games', [])
    targets = [g for g in games
               if g.get('yr') in TARGET_YEARS and g.get('game_id')
               and g.get('home_score') is None]   # 점수 아직 없는 것
    targets.sort(key=lambda g: g.get('date',''))
    if TEST_LIMIT > 0:
        targets = targets[:TEST_LIMIT]
        print(f"[검증 모드] 앞 {len(targets)}경기 점수만 추출(저장 안 함)\n")
    else:
        print(f"[전체 실행] 점수 보강 대상 {len(targets)}경기\n")

    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        page = br.new_context(locale='ko-KR', viewport={'width':1440,'height':900}).new_page()
        ok = 0
        for i, info in enumerate(targets):
            a, h, how = None, None, ''
            for attempt in range(3):
                try:
                    a, h, how = get_score(page, info); break
                except PWError:
                    if attempt < 2: time.sleep(2)
            if a is not None:
                info['away_score'] = a; info['home_score'] = h; ok += 1
                line = f"  {info['date']} {info['away']}(원정) {a} : {h} {info['home']}(홈)  [{how}]"
            else:
                line = f"  {info['date']} {info['away']}@{info['home']}  ✗ 점수 추출 실패"
            if TEST_LIMIT > 0:
                print(line)
            elif (i+1) % 20 == 0 or i+1 == len(targets):
                data['games'] = games
                p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
                print(f"  [{(i+1)/len(targets)*100:4.0f}%] {i+1}/{len(targets)} | 성공 {ok}")
            time.sleep(0.3)
        br.close()

    if TEST_LIMIT == 0:
        data['games'] = games
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"\n저장 완료: 점수 보강 {ok}경기")
    else:
        print(f"\n→ 위 점수가 실제 결과와 맞으면, 파일 상단 TEST_LIMIT = 0 으로 바꾸고 다시 실행하세요.")

if __name__ == '__main__':
    main()
