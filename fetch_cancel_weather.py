#!/usr/bin/env python3
"""
취소 경기 날씨 수집기 (cancellations.json → temp_avg / rain_mm / wind_ms / weather)

왜 필요한가
-----------
강수량별 평균 관중 차트에는 생존편향이 있다. 비가 많이 오면 경기가 취소되므로
'5mm+' 구간에 남는 건 '비가 와도 강행한 경기'뿐이고, 그건 흥행이 보장된 카드이거나
돔구장일 가능성이 높다. 그래서 5mm+ 평균이 0~5mm보다 높게 나오는 역전이 생긴다.

취소된 경기의 날씨를 같은 기준(경기 시간대 14~21시)으로 채워 넣으면,
각 강수/기온 구간의 '취소율'을 계산해 편향의 크기를 실제로 잴 수 있다.

fetch_weather.py의 좌표·API·집계 로직을 그대로 재사용한다(같은 기준이어야 비교가 성립).

사용:
  python fetch_cancel_weather.py            # 날씨 없는 항목만
  python fetch_cancel_weather.py --refetch   # 전부 다시
"""
import json, time, argparse, sys
from pathlib import Path

try:
    from fetch_weather import fetch_weather, extract_game_weather, get_stadium, STADIUMS
except ImportError:
    print('fetch_weather.py를 찾을 수 없습니다. 같은 폴더에서 실행하세요.')
    sys.exit(1)

OUT = Path('cancellations.json')

# 구장명 → 좌표. 취소 기록에는 팀이 아니라 구장 이름이 남으므로 구장 기준으로 찾는다.
VENUE_TEAM = {
    '잠실': 'LG', '대구': '삼성', '광주': 'KIA', '문학': 'SSG', '사직': '롯데',
    '수원': 'kt', '대전': '한화', '창원': 'NC', '고척': '키움',
}
VENUE_XY = {   # 제2·중립구장 (홈팀 구장과 다르므로 직접 지정)
    '포항': {'name': '포항야구장', 'lat': 36.0079, 'lon': 129.3597},
    '울산': {'name': '울산문수야구장', 'lat': 35.5326, 'lon': 129.2658},
    '청주': {'name': '청주야구장', 'lat': 36.6396, 'lon': 127.4700},
}


def locate(item):
    v = (item.get('venue') or '').strip()
    if v in VENUE_XY:
        return VENUE_XY[v]
    team = VENUE_TEAM.get(v) or item.get('home')
    yr = int(item['date'][:4])
    st = get_stadium(team, yr)
    if st:
        return st
    return STADIUMS.get(item.get('home'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--refetch', action='store_true', help='이미 날씨가 있는 항목도 다시 조회')
    a = ap.parse_args()

    if not OUT.exists():
        print('cancellations.json 없음 — fetch_cancels.py 먼저 실행'); return
    data = json.loads(OUT.read_text(encoding='utf-8'))
    items = data.get('items', [])

    cache, added, skipped, failed = {}, 0, 0, 0
    for it in items:
        if it.get('temp_avg') is not None and not a.refetch:
            skipped += 1; continue
        st = locate(it)
        if not st:
            print(f'  좌표 없음: {it["date"]} {it.get("venue")}'); failed += 1; continue

        key = (it['date'], st['name'])
        if key not in cache:
            try:
                raw = fetch_weather(st['lat'], st['lon'], it['date'])
                cache[key] = extract_game_weather(raw, it['date'])
                time.sleep(0.35)                    # Open-Meteo 예의상 간격
            except Exception as e:
                print(f'  실패 {it["date"]} {st["name"]}: {e}')
                cache[key] = {}; failed += 1
        w = cache[key]
        if w:
            it.update({k: w[k] for k in ('temp_avg', 'rain_mm', 'wind_ms', 'weather') if k in w})
            added += 1

    data['_meta']['weather'] = 'Open-Meteo 과거 기상(경기 시간대 14~21시) — fetch_cancel_weather.py'
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'\n추가 {added} · 기존유지 {skipped} · 실패 {failed}')

    # 사유별 실제 기상값 요약 — 수집이 제대로 됐는지 눈으로 확인하는 용도
    byr = {}
    for it in items:
        if it.get('rain_mm') is None: continue
        byr.setdefault(it['reason'], []).append(it)
    print()
    for r, gs in sorted(byr.items(), key=lambda x: -len(x[1])):
        rain = sorted(g['rain_mm'] for g in gs)
        temp = sorted(g['temp_avg'] for g in gs)
        med = lambda v: v[len(v) // 2]
        print(f'  {r} {len(gs):3d}건 — 강수 중앙값 {med(rain):5.1f}mm (최대 {rain[-1]:.1f}) · '
              f'기온 중앙값 {med(temp):4.1f}℃ (최고 {temp[-1]:.1f})')


if __name__ == '__main__':
    main()
