"""verify_kbo.py — 수집 데이터 무결성 + 수용인원 보정 검증.

매 파이프라인 끝(fetch_vb → fetch_scores → compute_standings → fetch_weather)에 실행.
caps.json 단일 소스를 기준으로 점검하고, 실측 관중으로 cap을 역검증한다.

사용:
    python verify_kbo.py                       # kbo_games.json 검사
    python verify_kbo.py path/to/games.json
    python verify_kbo.py --strict              # WARN도 실패로 처리(CI용, exit!=0)

검사 항목:
  1) 연도별 경기 수 (정규 720±, 진행 중 연도는 제외)
  2) 점유율 100% 초과 (att > cap)  — cap이 낮거나 제2구장 의심
  3) 결측 (att / temp_avg / home_rank)
  4) 팀명 정규화 (현재 10개 구단 외 이름)
  5) cap 보정표 (구단x시대 실측 최다/상위 vs cap)
"""
import json
import sys
from collections import defaultdict

from kbo_caps import cap, load_caps

TEAMS = {"LG", "두산", "삼성", "KIA", "SSG", "롯데", "kt", "한화", "NC", "키움"}
REG_PER_YEAR = 720          # 정규시즌 10개 구단 × 144경기 / 2
OVER_TOL = 0.02             # att가 cap을 이만큼 초과하면 플래그(매진 라운딩 허용)

C_GREEN, C_YELLOW, C_RED, C0 = "\033[92m", "\033[93m", "\033[91m", "\033[0m"


def load_games(path):
    raw = json.load(open(path, encoding="utf-8"))
    return raw["games"] if isinstance(raw, dict) else raw


def pct(sorted_list, p):
    if not sorted_list:
        return 0
    i = min(len(sorted_list) - 1, int(len(sorted_list) * p))
    return sorted_list[i]


def main(path="kbo_games.json", strict=False):
    games = load_games(path)
    played = [g for g in games if g.get("att")]
    warn, fail = [], []
    print(f"\n{'='*64}\n KBO 데이터 검증 — {path}  (총 {len(games):,}경기, 관중기록 {len(played):,})\n{'='*64}")

    # ── 1) 연도별 경기 수 ───────────────────────────────
    by_year = defaultdict(int)
    for g in games:
        by_year[g["yr"]] += 1
    years = sorted(by_year)
    cur_year = max(years)
    print("\n[1] 연도별 경기 수")
    for y in years:
        n = by_year[y]
        if y == cur_year:                       # 진행 중 — 정보만
            print(f"    {y}: {n:>4}경기  (진행 중)")
        elif y in (2020, 2021):                 # 코로나 무관중/제한관중 — 720 미만 정상
            print(f"    {y}: {n:>4}경기  (코로나 무관중 — 정상)")
        elif abs(n - REG_PER_YEAR) <= 8:
            print(f"  {C_GREEN}OK{C0}  {y}: {n:>4}경기")
        else:
            d = n - REG_PER_YEAR
            msg = f"{y}: {n}경기 (정규 {REG_PER_YEAR} 대비 {d:+d}) — 누락/중복 의심"
            print(f"  {C_RED}!!{C0}  {msg}")
            fail.append(f"[연도수] {msg}")

    # ── 2) 점유율 100% 초과 (att > cap) ─────────────────
    over = []
    for g in played:
        c = cap(g["home"], g["yr"], g.get("venue"))
        if g["att"] > c * (1 + OVER_TOL):
            over.append((g["att"] / c, g))
    print(f"\n[2] 점유율 100% 초과(att>cap, +{OVER_TOL*100:.0f}% 허용): {len(over)}건")
    if over:
        over.sort(key=lambda x: x[0], reverse=True)
        by_team = defaultdict(int)
        for r, g in over:
            by_team[(g["home"], g["yr"])] += 1
        for (tm, yr), n in sorted(by_team.items(), key=lambda x: -x[1])[:12]:
            ex = max((r for r, g in over if g["home"] == tm and g["yr"] == yr))
            print(f"  {C_YELLOW}··{C0}  {tm} {yr}: {n}건 (최대 {ex*100:.0f}%) — cap 재확인 또는 제2구장")
        warn.append(f"[초과] att>cap {len(over)}건 — caps.json 보정 검토")
    else:
        print(f"  {C_GREEN}OK{C0}  모든 경기 att ≤ cap")

    # ── 3) 결측 ─────────────────────────────────────────
    miss_att = [g for g in games if not g.get("att") and g.get("home_score") is not None]
    miss_temp = [g for g in played if g.get("temp_avg") in (None, "")]
    miss_rank = [g for g in played if g.get("home_rank") in (None, 0)]
    print("\n[3] 결측")
    def rep(label, lst, hard=False):
        if not lst:
            print(f"  {C_GREEN}OK{C0}  {label}: 0")
            return
        bucket = defaultdict(int)
        for g in lst:
            bucket[g["yr"]] += 1
        tail = ", ".join(f"{y}:{n}" for y, n in sorted(bucket.items()))
        print(f"  {(C_RED+'!!'+C0) if hard else (C_YELLOW+'··'+C0)}  {label}: {len(lst)}  ({tail})")
        (fail if hard else warn).append(f"[결측] {label} {len(lst)}건")
    rep("관중 결측(경기는 종료)", miss_att, hard=True)
    rep("날씨(temp_avg) 결측", miss_temp)
    rep("홈팀 순위 결측", miss_rank)

    # ── 4) 팀명 정규화 ──────────────────────────────────
    bad_names = defaultdict(int)
    for g in games:
        for side in ("home", "away"):
            if g.get(side) not in TEAMS:
                bad_names[g.get(side)] += 1
    print("\n[4] 팀명 정규화 (현재 10구단 외)")
    if bad_names:
        for nm, n in sorted(bad_names.items(), key=lambda x: -x[1]):
            print(f"  {C_RED}!!{C0}  '{nm}': {n}건 — normalize_teams 누락 (예: 넥센→키움, SK→SSG)")
            fail.append(f"[팀명] 미정규화 '{nm}' {n}건")
    else:
        print(f"  {C_GREEN}OK{C0}  전부 정규화됨")

    # ── 5) cap 보정표 (실측 vs caps.json) ───────────────
    print("\n[5] cap 보정표 — 구단×시대 실측 상한 vs caps.json")
    print(f"    {'구단·시대':<22}{'경기':>5}{'최다':>8}{'p99':>8}{'cap':>8}{'판정':>8}")
    eras = defaultdict(list)
    Cdef = load_caps()
    for g in played:
        c = cap(g["home"], g["yr"], g.get("venue"))
        eras[(g["home"], c)].append(g["att"])
    for (tm, c) in sorted(eras, key=lambda k: (k[0], k[1])):
        a = sorted(eras[(tm, c)])
        mx, p99 = max(a), pct(a, 0.99)
        if mx > c * (1 + OVER_TOL):
            verdict = f"{C_YELLOW}낮음?{C0}"      # cap이 실측 최다보다 낮음
        elif p99 < c * 0.90:
            verdict = f"{C_YELLOW}높음?{C0}"      # 매진이 cap에 한참 못 미침
        else:
            verdict = f"{C_GREEN}적정{C0}"
        print(f"    {tm+' (cap '+format(c,',')+')':<22}{len(a):>5}{mx:>8,}{p99:>8,}{c:>8,}{verdict:>16}")

    # ── 6) 포스트시즌 보정 (kbo_postseason.json 있으면) ──
    import os
    ps_path = os.path.join(os.path.dirname(os.path.abspath(path)) or ".", "kbo_postseason.json")
    if os.path.exists(ps_path):
        ps = load_games(ps_path)
        ps = [g for g in ps if g.get("att")]
        print(f"\n[6] 포스트시즌 검증 ({len(ps)}경기) — PS cap 대비")
        ps_over = []
        for g in ps:
            c = cap(g["home"], g["yr"], g.get("venue"), postseason=True)
            if g["att"] > c * (1 + OVER_TOL):
                ps_over.append((g["att"] / c, g, c))
        if ps_over:
            ps_over.sort(key=lambda x: x[0], reverse=True)
            seen = set()
            for r, g, c in ps_over:
                k = (g["home"], g["yr"])
                if k in seen:
                    continue
                seen.add(k)
                print(f"  {C_YELLOW}··{C0}  {g['yr']} {g['home']}: {g['att']:,} > PS cap {c:,} "
                      f"({r*100:.0f}%) — caps.json teams.{g['home']}.postseason 검토")
            warn.append(f"[PS] 포스트시즌 att>cap {len(ps_over)}건")
        else:
            print(f"  {C_GREEN}OK{C0}  모든 포스트시즌 경기 att ≤ PS cap")
    else:
        print(f"\n[6] 포스트시즌: kbo_postseason.json 없음 — 건너뜀")

    # ── 결과 ────────────────────────────────────────────
    print(f"\n{'='*64}")
    if fail:
        print(f" {C_RED}FAIL{C0}: {len(fail)}건 / WARN: {len(warn)}건")
        for m in fail:
            print("   ✗", m)
    else:
        print(f" {C_GREEN}PASS{C0}  (치명 오류 없음) / WARN: {len(warn)}건")
    for m in warn:
        print("   ·", m)
    print('='*64 + "\n")

    return 1 if (fail or (strict and warn)) else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strict = "--strict" in sys.argv
    sys.exit(main(args[0] if args else "kbo_games.json", strict=strict))
