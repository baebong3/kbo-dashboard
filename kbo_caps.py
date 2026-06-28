"""kbo_caps.py — 구장 수용인원(만원기준) 단일 소스 로더.

caps.json 하나만 읽어서 모든 곳(compute_standings.py, monthly_report.py, 대시보드)이
같은 cap()을 쓰게 한다. 값이 틀리면 caps.json 한 곳만 고치면 전부 반영됨.

사용:
    from kbo_caps import cap
    cap('한화', 2025)            -> 17000
    cap('한화', 2024)            -> 13000
    cap('롯데', 2017)            -> 26600
    occ = min(att / cap(home, yr, venue), 1.0)

대시보드(JS)용으로 내보내기:
    python kbo_caps.py --js > caps.js     # window.KBO_CAPS + cap() 생성
"""
import json
import os

_CAPS = None
_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "caps.json")


def load_caps(path=None):
    """caps.json을 로드(캐시). path를 주면 강제 재로드."""
    global _CAPS
    if _CAPS is None or path:
        with open(path or _PATH, encoding="utf-8") as f:
            _CAPS = json.load(f)
    return _CAPS


def _era_match(era, year):
    return (era.get("min") is None or year >= era["min"]) and \
           (era.get("max") is None or year <= era["max"])


def cap(team, year=None, venue=None, postseason=False):
    """team/year/venue로 만원기준 수용인원 반환.

    우선순위: postseason override > venue(제2구장) > team+year(시대) > default.
    포스트시즌엔 cap(home, yr, venue, postseason=True) 로 호출.
    """
    C = load_caps()
    t = C["teams"].get(team)
    if postseason and t and t.get("postseason") is not None:
        return t["postseason"]
    if venue:
        v = str(venue)
        for name, val in C.get("venues", {}).items():
            if name in v:
                return val
    if not t:
        return C.get("default_cap", 20000)
    y = int(year) if year else 9999
    for era in t["eras"]:
        if _era_match(era, y):
            return era["cap"]
    return t["eras"][-1]["cap"]


def cap_info(team, year=None):
    """디버그용: 적용된 era 전체 반환."""
    C = load_caps()
    t = C["teams"].get(team)
    if not t:
        return {"cap": C.get("default_cap", 20000), "source": "default"}
    y = int(year) if year else 9999
    for era in t["eras"]:
        if _era_match(era, y):
            return {**era, "confidence": t.get("confidence"), "note": t.get("note")}
    return {**t["eras"][-1], "confidence": t.get("confidence")}


def to_js():
    """caps.json을 그대로 담은 JS 스니펫 생성 — 대시보드가 동일 소스를 쓰게 함."""
    C = load_caps()
    payload = json.dumps(C, ensure_ascii=False, separators=(",", ":"))
    return (
        "/* AUTO-GENERATED from caps.json — 직접 수정 금지. caps.json을 고치고 재생성하세요. */\n"
        "window.KBO_CAPS=" + payload + ";\n"
        "function cap(team,year,venue,postseason){\n"
        "  var C=window.KBO_CAPS, t=C.teams[team];\n"
        "  if(postseason&&t&&t.postseason!=null)return t.postseason;\n"
        "  if(venue){var v=''+venue;for(var k in C.venues){if(v.indexOf(k)>=0)return C.venues[k];}}\n"
        "  if(!t)return C.default_cap||20000;\n"
        "  var y=parseInt(year)||9999;\n"
        "  for(var i=0;i<t.eras.length;i++){var e=t.eras[i];\n"
        "    if((e.min==null||y>=e.min)&&(e.max==null||y<=e.max))return e.cap;}\n"
        "  return t.eras[t.eras.length-1].cap;\n"
        "}\n"
    )


if __name__ == "__main__":
    import sys
    if "--js" in sys.argv:
        sys.stdout.write(to_js())
    else:
        # 간단 자가 점검
        for tm, yr, exp in [("한화", 2025, 17000), ("한화", 2024, 13000),
                            ("롯데", 2017, 26600), ("롯데", 2022, 22990),
                            ("SSG", 2018, 25000), ("SSG", 2022, 23000),
                            ("키움", 2017, 17000), ("키움", 2020, 16000),
                            ("kt", 2017, 20000), ("kt", 2024, 18700),
                            ("NC", 2018, 11000), ("NC", 2020, 17983)]:
            got = cap(tm, yr)
            print(f"{'OK ' if got == exp else 'FAIL'} cap({tm},{yr})={got} (기대 {exp})")
