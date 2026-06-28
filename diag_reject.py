"""
2016~2018 기각 사유 진단기
- 해당 연도 스케줄 링크 중 kbo_games.json 에 아직 없는(=기각된) 경기를 표본으로 방문
- 각 경기가 어떤 검증에서 떨어지는지(종료/점수/팀명/날짜/관중) 출력 + 사유 집계
실행: python diag_reject.py
※ fetch_vb.py 와 같은 폴더에서 실행 (함수 재사용)
"""
import json
from pathlib import Path
from collections import Counter
from playwright.sync_api import sync_playwright
from fetch_vb import collect_links, parse_game_id, make_browser, BASE

YEAR   = 2018     # 진단할 연도 (2016/2017/2018 바꿔가며)
SAMPLE = 40       # 방문 표본 수


def probe(page, info):
    gid = info['game_id']; home, away = info['home'], info['away']
    date_dot = f"{info['mo']:02d}.{info['day']:02d}"
    page.goto(f"{BASE}/game/{gid}", wait_until='domcontentloaded', timeout=25000)
    page.wait_for_timeout(2500)
    return page.evaluate("""(args) => {
        const [home, away, dateDot] = args;
        const txt = document.body.innerText || '';
        const T = txt.toUpperCase();
        let att = 0;
        const m = txt.match(/관중[\\s\\n]*([\\d,]{3,7})/);
        if (m) att = parseInt(m[1].replace(/,/g, ''));
        return {
            att,
            hasFinal: /종료/.test(txt),
            hasScore: /\\d+\\s*[:：]\\s*\\d+/.test(txt),
            teamsOk:  T.includes(home.toUpperCase()) && T.includes(away.toUpperCase()),
            dateOk:   txt.includes(dateDot),
            len:      txt.length,
        };
    }""", [home, away, date_dot])


def main():
    existing = {g['game_id'] for g in
                json.loads(Path('kbo_games.json').read_text(encoding='utf-8'))['games']
                if g.get('yr') == YEAR and g.get('att', 0) > 0}
    print(f"[{YEAR}] 이미 수집된 경기: {len(existing)}\n")

    with sync_playwright() as pw:
        br, page = make_browser(pw)
        links = collect_links(page, YEAR)
        missing = [parse_game_id(g) for g in links if g not in existing]
        missing = [i for i in missing if i][:SAMPLE]
        print(f"미수집(기각 추정) 표본 {len(missing)}개 진단:\n")

        fails = Counter()
        for info in missing:
            try:
                r = probe(page, info)
            except Exception as e:
                print(f"  ERR {info['game_id']}: {e}"); continue
            why = [k for k in ('hasFinal', 'hasScore', 'teamsOk', 'dateOk') if not r[k]]
            if r['att'] <= 100: why.append('att없음')
            for w in why: fails[w] += 1
            tag = '·'.join(why) if why else 'OK?(통과해야 정상)'
            print(f"  {info['date']} {info['away']:>3}@{info['home']:<3} "
                  f"att={r['att']:>6} 종료={int(r['hasFinal'])} 점수={int(r['hasScore'])} "
                  f"팀={int(r['teamsOk'])} 날짜={int(r['dateOk'])} len={r['len']:>5} → {tag}")
        br.close()

    print(f"\n=== 기각 사유 집계({len(missing)}경기) ===")
    for k, v in fails.most_common():
        print(f"  {k}: {v}")
    print("\n해석 가이드:")
    print("  · 'att없음'이 대부분 → 소스에 관중 데이터 자체가 없음(부분 수집 한계) → KBO 공식 소스 권장")
    print("  · 'dateOk'가 대부분 → 옛 페이지 날짜표기가 달라 과도 기각(검증 완화로 복구 가능)")
    print("  · 'len'이 작음(수백) → 페이지 로딩 실패/지연(재시도·대기시간↑로 복구)")


if __name__ == '__main__':
    main()
