"""
KBO 경기장 날씨 데이터 수집기
- Open-Meteo API (무료, API 키 불필요)
- kbo_games.json에 기온/강수량/풍속 추가
실행: python fetch_weather.py
"""
import json, time, requests
from pathlib import Path
from datetime import date, datetime

# ── 경기장 좌표 ─────────────────────────────────────────────
STADIUMS = {
    'LG':   {'name':'잠실야구장',         'lat':37.5121, 'lon':127.0719},
    '두산': {'name':'잠실야구장',         'lat':37.5121, 'lon':127.0719},
    '삼성': {'name':'대구삼성라이온즈파크','lat':35.8417, 'lon':128.6814},
    'KIA':  {'name':'광주챔피언스필드',    'lat':35.1683, 'lon':126.8897},
    'SSG':  {'name':'인천SSG랜더스필드',  'lat':37.4374, 'lon':126.6932},
    '롯데': {'name':'부산사직야구장',     'lat':35.1944, 'lon':129.0613},
    'kt':   {'name':'수원KT위즈파크',     'lat':37.2997, 'lon':127.0097},
    '한화': {'name':'대전한화생명이글스파크','lat':36.3170,'lon':127.4296},
    'NC':   {'name':'창원NC파크',         'lat':35.2226, 'lon':128.5820},
    '키움': {'name':'고척스카이돔',        'lat':37.4982, 'lon':126.8674},
}

# WMO 날씨 코드 → 한국어
WMO = {
    0:'맑음', 1:'대체로맑음', 2:'구름조금', 3:'흐림',
    45:'안개', 48:'착빙안개',
    51:'이슬비(약)', 53:'이슬비', 55:'이슬비(강)',
    61:'비(약)', 63:'비', 65:'비(강)',
    71:'눈(약)', 73:'눈', 75:'눈(강)',
    80:'소나기(약)', 81:'소나기', 82:'소나기(강)',
    95:'뇌우', 96:'뇌우+우박', 99:'뇌우+우박(강)',
}


def fetch_weather(lat, lon, game_date):
    """Open-Meteo로 해당 날짜 시간별 날씨 조회"""
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": game_date,
        "end_date": game_date,
        "hourly": "temperature_2m,precipitation,wind_speed_10m,weather_code",
        "timezone": "Asia/Seoul",
        "wind_speed_unit": "ms",
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def extract_game_weather(weather_data, game_date):
    """경기 시간대(14~21시) 날씨 요약"""
    hourly = weather_data.get('hourly', {})
    times  = hourly.get('time', [])
    temps  = hourly.get('temperature_2m', [])
    rains  = hourly.get('precipitation', [])
    winds  = hourly.get('wind_speed_10m', [])
    wcodes = hourly.get('weather_code', [])

    # 경기 시간대 인덱스 (14~21시)
    game_idx = [i for i,t in enumerate(times) if 14 <= int(t[11:13]) <= 21]
    # 개막전/주말낮경기는 13시도 포함
    day_idx  = [i for i,t in enumerate(times) if 13 <= int(t[11:13]) <= 21]

    if not game_idx:
        return {}

    avg_temp    = round(sum(temps[i] for i in game_idx) / len(game_idx), 1)
    total_rain  = round(sum(rains[i] for i in game_idx), 1)
    max_wind    = round(max(winds[i] for i in game_idx), 1)
    # 가장 흔한 날씨코드
    wcode_count = {}
    for i in game_idx:
        c = wcodes[i]
        wcode_count[c] = wcode_count.get(c, 0) + 1
    dominant_code = max(wcode_count, key=wcode_count.get)

    return {
        'temp_avg':  avg_temp,     # 경기 시간대 평균 기온 (°C)
        'rain_mm':   total_rain,   # 경기 시간대 강수량 합계 (mm)
        'wind_ms':   max_wind,     # 최대 풍속 (m/s)
        'weather':   WMO.get(dominant_code, f'코드{dominant_code}'),
        'rain_yn':   total_rain >= 0.1,  # 우천 여부
    }


def main():
    p = Path('kbo_games.json')
    if not p.exists():
        print("kbo_games.json 없음 — fetch_vb.py 먼저 실행")
        return

    data = json.loads(p.read_text(encoding='utf-8'))
    games = data.get('games', [])
    print(f"총 {len(games)}경기에 날씨 데이터 추가\n")

    # 캐시: (날짜, 팀홈) → 날씨 (같은 날 같은 구장은 API 1회만 호출)
    cache = {}
    added = skipped = failed = 0

    for i, g in enumerate(games):
        home = g.get('home', '')
        gdate = g.get('date', '')
        if not home or not gdate:
            continue

        # 이미 날씨 있으면 스킵
        if g.get('temp_avg') is not None:
            skipped += 1
            continue

        stadium = STADIUMS.get(home)
        if not stadium:
            continue

        cache_key = (gdate, home)

        if cache_key not in cache:
            try:
                raw = fetch_weather(stadium['lat'], stadium['lon'], gdate)
                w = extract_game_weather(raw, gdate)
                cache[cache_key] = w
                time.sleep(0.15)  # API 부하 방지
            except Exception as e:
                print(f"  ✗ {gdate} {home} 오류: {e}")
                failed += 1
                cache[cache_key] = {}
                continue

        w = cache[cache_key]
        if w:
            g.update(w)
            added += 1

        # 50경기마다 진행 출력 + 중간 저장
        if (i+1) % 50 == 0:
            p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            print(f"  {i+1}/{len(games)} | 추가:{added} | 스킵:{skipped} | 실패:{failed}")
            print(f"    최근: {gdate} {home} → {w.get('temp_avg','?')}°C, {w.get('rain_mm','?')}mm")

    # 최종 저장
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n✅ 완료: {added}경기 날씨 추가 / {skipped} 스킵 / {failed} 실패")

    # 날씨 영향 분석 미리보기
    print("\n── 날씨별 평균 관중 분석 ──")
    from collections import defaultdict
    weather_att = defaultdict(list)
    rain_att = {'우천':[], '맑음':[]}
    for g in games:
        if g.get('temp_avg') and g.get('att',0)>0:
            wtype = '우천' if g.get('rain_yn') else '맑음'
            rain_att[wtype].append(g['att'])
            w_label = g.get('weather','?')
            weather_att[w_label].append(g['att'])

    for label, atts in rain_att.items():
        if atts:
            print(f"  {label}: 평균 {sum(atts)//len(atts):,}명 ({len(atts)}경기)")

    print("\n── 기온별 평균 관중 ──")
    temp_bins = {'10°C 미만':[], '10~15°C':[], '15~20°C':[], '20~25°C':[], '25~30°C':[], '30°C 이상':[]}
    for g in games:
        t = g.get('temp_avg')
        a = g.get('att',0)
        if t is None or a<=0: continue
        if t<10:   temp_bins['10°C 미만'].append(a)
        elif t<15: temp_bins['10~15°C'].append(a)
        elif t<20: temp_bins['15~20°C'].append(a)
        elif t<25: temp_bins['20~25°C'].append(a)
        elif t<30: temp_bins['25~30°C'].append(a)
        else:      temp_bins['30°C 이상'].append(a)

    for label, atts in temp_bins.items():
        if atts:
            print(f"  {label}: 평균 {sum(atts)//len(atts):,}명 ({len(atts)}경기)")


if __name__ == '__main__':
    main()
