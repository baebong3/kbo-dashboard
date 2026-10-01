"""
KBO 월간 관중 분석 리포트 생성기
- kbo_games.json 에서 '지난달'(매월 1일 실행 시 직전 달)을 뽑아 다각도 분석
- KBO 대시보드(서던 하우스) 스타일 HTML 생성 → Playwright 로 PDF 인쇄(차트는 전부 인라인 SVG/CSS, JS 의존 없음)
- (선택) 생성한 PDF 를 메일로 첨부 발송

실행:
  python monthly_report.py                  # 지난달 자동
  python monthly_report.py --month 2026-06  # 특정 달 지정(테스트)
  REPORT_YM=2026-06 python monthly_report.py

메일(선택) — 환경변수 설정 시 자동 발송:
  GMAIL_USER, GMAIL_APP_PASSWORD, REPORT_TO(쉼표구분)
"""
import json, os, sys, argparse, math
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

# ── 색상/팀 ─────────────────────────────────────────────
NAVY='#2B3A55'; CORAL='#E85A3C'; CORALD='#C6452B'; INK='#16202C'; MUTED='#8A93A0'
STEEL='#6B7A8F'; UP='#1F7A4D'; DN='#C8413B'
TEAMS=['LG','두산','삼성','KIA','SSG','롯데','kt','한화','NC','키움']
TCOL={'LG':'#C30452','두산':'#16193F','삼성':'#1167B1','KIA':'#EA0029','SSG':'#F03C2E',
      '롯데':'#0A2E5C','kt':'#5A5A5A','한화':'#FF6600','NC':'#2E8FA6','키움':'#820024'}
STAD={'LG':'잠실','두산':'잠실','삼성':'대구','KIA':'광주','SSG':'문학','롯데':'사직',
      'kt':'수원','한화':'대전','NC':'창원','키움':'고척'}
NMP={'LG트윈스':'LG','두산베어스':'두산','삼성라이온즈':'삼성','KIA타이거즈':'KIA','SSG랜더스':'SSG',
     '롯데자이언츠':'롯데','kt wiz':'kt','KT위즈':'kt','KT':'kt','한화이글스':'한화','NC다이노스':'NC',
     '키움히어로즈':'키움','히어로즈':'키움','넥센':'키움','SK':'SSG','OB':'두산','해태':'KIA'}
def norm(t):
    t=(t or '').strip()
    if t in TCOL: return t
    for k,v in NMP.items():
        if k in t: return v
    return t

# ── 수용인원: 단일 소스(caps.json) ───────────────
from kbo_caps import cap  # 같은 폴더에 kbo_caps.py·caps.json 필요. cap(team, yr, venue[, postseason])

# ── 포맷 ────────────────────────────────────────────────
def f(n): return f'{round(n):,}'
def man(n): return f'{n/10000:.1f}'
def pct(p,dec=0): return f'{p:+.{dec}f}%'

# ── 데이터 로드 ─────────────────────────────────────────
def load(path='kbo_games.json'):
    raw=json.loads(Path(path).read_text(encoding='utf-8')).get('games',[])
    out=[]
    for g in raw:
        att=g.get('att',0)
        if not att or att<100: continue
        yr=g.get('yr') or g.get('year')
        if not yr: continue
        home=norm(g.get('home',''))
        if not home: continue
        venue=g.get('venue') or g.get('stadium')
        out.append({
            'yr':int(yr),'mo':int(g.get('mo') or g.get('month') or 0),'day':int(g.get('day') or 0),
            'home':home,'away':norm(g.get('away','')),'att':int(att),
            'occ':min(att/cap(home,int(yr),venue),1.0),
            'series':g.get('series'),
            'temp':g.get('temp_avg'),'rain':g.get('rain_mm'),
            'rainY':g.get('rain_yn') if g.get('rain_yn') is not None else ((g.get('rain_mm') or 0)>0),
            'rank':g.get('home_rank'),'arank':g.get('away_rank'),
            'hs':g.get('home_score'),'as':g.get('away_score'),
        })
    return out

# ── 월 집계 ─────────────────────────────────────────────
def month_games(games,y,m): return [g for g in games if g['yr']==y and g['mo']==m]
def team_records(games,y,m):
    """그 달 각 구단의 성적(홈·원정 전체) → {팀:{'w','d','l','pct'}}. 승률=승/(승+패)."""
    rec={}
    for g in month_games(games,y,m):
        hs,asc=g.get('hs'),g.get('as')
        if hs is None or asc is None: continue
        h,a=g['home'],g['away']
        rec.setdefault(h,[0,0,0]); rec.setdefault(a,[0,0,0])
        if hs>asc:   rec[h][0]+=1; rec[a][2]+=1
        elif hs<asc: rec[h][2]+=1; rec[a][0]+=1
        else:        rec[h][1]+=1; rec[a][1]+=1
    return {t:{'w':w,'d':d,'l':l,'pct':(w/(w+l) if (w+l) else 0)} for t,(w,d,l) in rec.items()}
def summarize(gs):
    if not gs: return None
    n=len(gs); tot=sum(g['att'] for g in gs)
    return {'n':n,'tot':tot,'avg':tot/n,'occ':sum(g['occ'] for g in gs)/n,
            'sell':sum(1 for g in gs if g['occ']>=1)}
def team_stats(gs):
    by={}
    for g in gs: by.setdefault(g['home'],[]).append(g)
    out={}
    for t,a in by.items():
        ranks=[x['rank'] for x in a if x['rank'] is not None]
        out[t]={'n':len(a),'avg':sum(x['att'] for x in a)/len(a),
                'occ':sum(x['occ'] for x in a)/len(a),
                'rank':(sum(ranks)/len(ranks)) if ranks else None}
    return out
def team_rank_avg_allgames(games,y,m):
    """그 달 각 구단의 '경기일 기준 순위'를 한 달간 평균(홈=home_rank, 원정=away_rank, 모든 경기)."""
    gs=month_games(games,y,m); acc={}
    for g in gs:
        if g['rank'] is not None:
            acc.setdefault(g['home'],[]).append(g['rank'])
        ar=g.get('arank')
        if ar is not None:
            acc.setdefault(g['away'],[]).append(ar)
    return {t:sum(v)/len(v) for t,v in acc.items() if v}
def pearson(xs,ys):
    n=len(xs)
    if n<3: return None
    mx=sum(xs)/n; my=sum(ys)/n
    num=sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    dx=math.sqrt(sum((x-mx)**2 for x in xs)); dy=math.sqrt(sum((y-my)**2 for y in ys))
    if dx==0 or dy==0: return None
    return num/(dx*dy)

# ── SVG: 리그 월별 평균 관중 막대 ──────────────────────
def svg_league_bars(months, cur, prev, y):
    """리그 월별 경기당 평균 관중: 올해(네이비) vs 전년(연회색) 막대 + 올해 값 라벨 + 하단 전년비."""
    ms=[mo for mo in months if cur.get(mo) is not None]
    if not ms: return '<div class="note">데이터 없음</div>'
    W,H=372,262; pl,pr,pt,pb=8,8,18,40; iw,ih=W-pl-pr,H-pt-pb
    vmax=max([cur[mo] for mo in ms]+[prev.get(mo) or 0 for mo in ms])
    ymax=math.ceil(vmax*1.08/2000)*2000
    gw=iw/len(ms); bw=min(15,gw*0.3); gap=4
    def Y(v): return pt+ih-(v/ymax)*ih
    s=[f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="Pretendard,sans-serif">']
    for k in range(1,4):
        yy=Y(ymax*k/4)
        s.append(f'<line x1="{pl}" y1="{yy:.1f}" x2="{pl+iw}" y2="{yy:.1f}" stroke="#EEF1F5"/>')
    s.append(f'<line x1="{pl}" y1="{pt+ih}" x2="{pl+iw}" y2="{pt+ih}" stroke="{INK}" stroke-width="1.6"/>')
    for i,mo in enumerate(ms):
        cx=pl+gw*(i+0.5)
        pv=prev.get(mo); cv=cur[mo]
        if pv:
            s.append(f'<rect x="{cx-gap/2-bw:.1f}" y="{Y(pv):.1f}" width="{bw:.1f}" height="{pt+ih-Y(pv):.1f}" rx="1.5" fill="#D3D9E1"/>')
            s.append(f'<text x="{cx-gap/2-bw/2:.1f}" y="{Y(pv)-4:.1f}" text-anchor="middle" font-size="6.8" font-weight="700" fill="{MUTED}">{pv/1000:.1f}</text>')
        hi=(mo==ms[-1]); bc=CORAL if hi else '#5B6676'
        s.append(f'<rect x="{cx+gap/2:.1f}" y="{Y(cv):.1f}" width="{bw:.1f}" height="{pt+ih-Y(cv):.1f}" rx="1.5" fill="{bc}"/>')
        s.append(f'<text x="{cx+gap/2+bw/2:.1f}" y="{Y(cv)-4:.1f}" text-anchor="middle" font-size="{8.4 if hi else 7.6}" font-weight="800" fill="{CORAL if hi else INK}">{cv/1000:.1f}</text>')
        s.append(f'<text x="{cx:.1f}" y="{pt+ih+13}" text-anchor="middle" font-size="9" font-weight="{800 if hi else 700}" fill="{CORAL if hi else "#3A4759"}">{mo}월</text>')
        if pv:
            d=(cv-pv)/pv*100
            col=CORAL if d>=0.5 else NAVY if d<=-0.5 else MUTED
            s.append(f'<text x="{cx:.1f}" y="{pt+ih+27}" text-anchor="middle" font-size="8" font-weight="800" fill="{col}">{d:+.0f}%</text>')
    s.append(f'<text x="{pl}" y="{pt-6}" font-size="8" fill="{MUTED}">단위: 천 명</text>')
    s.append('</svg>')
    return ''.join(s)


def html_month_heat(months, order, occ):
    """월별 구단 점유율 히트맵(CSS 표) + 시즌 평균 열(코랄 톤, 명암은 월별과 동일)."""
    cells=[occ[t][mo] for t in order for mo in months if occ.get(t,{}).get(mo) is not None]
    if not cells: return '<div class="note">데이터 없음</div>'
    mn,mx=min(cells),max(cells)
    def cell(v,avg=False):
        if v is None: return '<td class="hm-e">·</td>'
        r=(v-mn)/(mx-mn) if mx>mn else 0.6
        rgb='22,32,44' if avg else '43,58,85'
        return f'<td style="background:rgba({rgb},{0.12+r*0.82:.2f});color:{"#fff" if r>0.55 else "#1F2733"}">{v*100:.0f}</td>'
    head='<tr><th>구단</th>'+''.join(f'<th{" class=cur" if mo==months[-1] else ""}>{mo}월</th>' for mo in months)+'<th>평균</th></tr>'
    rows=[]
    for t in order:
        vs=[occ[t][mo] for mo in months if occ.get(t,{}).get(mo) is not None]
        avgv=sum(vs)/len(vs) if vs else None
        rows.append(f'<tr><td class="hm-t">{t}</td>'+''.join(cell(occ.get(t,{}).get(mo)) for mo in months)+cell(avgv,True)+'</tr>')
    return f'<table class="hm">{head}{"".join(rows)}</table>'

def team_legend(order):
    return '<div class="legend">'+''.join(
        f'<span class="lg"><i style="background:{TCOL.get(t,"#888")}"></i>{t}</span>' for t in order)+'</div>'
    """points: [{t, dx(순위 계단변화: +면 하락), dy(관중 %변화)}]"""
    W,H=560,300; pl,pr,pt,pb=46,18,16,40
    iw,ih=W-pl-pr,H-pt-pb
    xs=[p['dx'] for p in points]; ys=[p['dy'] for p in points]
    xmax=max(2,math.ceil(max(abs(min(xs)),abs(max(xs)),1)))
    ymax=max(5,math.ceil(max(abs(min(ys)),abs(max(ys)),1)/5)*5)
    def X(v): return pl+(v+xmax)/(2*xmax)*iw
    def Y(v): return pt+(ymax-v)/(2*ymax)*ih
    s=[f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="Pretendard,sans-serif">']
    # 사분면 배경
    s.append(f'<rect x="{pl}" y="{pt}" width="{iw}" height="{ih}" fill="#FAFBFC" stroke="#E6E9EE"/>')
    s.append(f'<line x1="{X(0)}" y1="{pt}" x2="{X(0)}" y2="{pt+ih}" stroke="#D7DCE3" stroke-dasharray="4 3"/>')
    s.append(f'<line x1="{pl}" y1="{Y(0)}" x2="{pl+iw}" y2="{Y(0)}" stroke="#D7DCE3" stroke-dasharray="4 3"/>')
    # 축 라벨
    s.append(f'<text x="{pl+iw}" y="{pt+ih+24}" text-anchor="end" font-size="10" fill="{MUTED}">순위 하락(계단) →</text>')
    s.append(f'<text x="{pl}" y="{pt+ih+24}" text-anchor="start" font-size="10" fill="{MUTED}">← 순위 상승</text>')
    s.append(f'<text x="{pl-6}" y="{pt+8}" text-anchor="end" font-size="10" fill="{MUTED}">관중↑</text>')
    s.append(f'<text x="{pl-6}" y="{pt+ih}" text-anchor="end" font-size="10" fill="{MUTED}">관중↓</text>')
    for p in points:
        cx,cy=X(p['dx']),Y(p['dy']); c=TCOL.get(p['t'],'#888')
        s.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{c}" stroke="#fff" stroke-width="1.5"/>')
        s.append(f'<text x="{cx:.1f}" y="{cy-9:.1f}" text-anchor="middle" font-size="9.5" font-weight="700" fill="{INK}">{p["t"]}</text>')
    s.append('</svg>')
    return ''.join(s)

# ── CSS 가로 막대 ───────────────────────────────────────
def bar_row(label, val, vmax, sub, delta=None):
    w=0 if vmax==0 else max(2,val/vmax*100)
    dchip=''
    if delta is not None:
        cls='up' if delta>0.5 else 'dn' if delta<-0.5 else 'fl'
        arr='▲' if delta>0.5 else '▼' if delta<-0.5 else '-'
        dchip=f'<span class="chip {cls}">{arr} {abs(delta):.0f}%</span>'
    return (f'<div class="brow"><div class="blab">{label}</div>'
            f'<div class="btrk"><div class="bfill" style="width:{w:.1f}%"></div></div>'
            f'<div class="bval">{sub} {dchip}</div></div>')

# ── HTML 빌드 ───────────────────────────────────────────
CSS = """
<style>
@page{size:A4;margin:12mm 13mm 12mm}
*{margin:0;padding:0;box-sizing:border-box}
:root{--ink:#16202C;--navy:#2B3A55;--coral:#E85A3C;--sub:#3A4759;--mut:#7A8595;--gray:#C9D0DA;--line:#E6E9EE;--soft:#F6F7F9}
body{font-family:'Pretendard','Pretendard Variable',-apple-system,sans-serif;color:var(--ink);font-size:10.5px;line-height:1.5;font-variant-numeric:tabular-nums;-webkit-print-color-adjust:exact;print-color-adjust:exact;background:#fff}
.page+.page{page-break-before:always}
.sec,.card,.kpi,table,tr,.mast,.hl,.pts{page-break-inside:avoid;break-inside:avoid}
/* 마스트헤드: 보고서형 강조 타이틀 */
.mast{background:var(--ink);color:#fff;border-radius:3px;padding:16px 20px 14px;display:flex;justify-content:space-between;align-items:flex-end;border-bottom:4px solid var(--coral)}
.mast .eb{font-size:9.5px;font-weight:800;letter-spacing:.16em;color:var(--coral)}
.mast h1{font-size:30px;font-weight:800;letter-spacing:-.03em;line-height:1.15;margin-top:6px}
.mast .iss{text-align:right;line-height:1.35}
.mast .iss b{display:block;font-size:20px;font-weight:800;letter-spacing:-.02em}
.mast .iss span{font-size:9px;color:#AEB7C4;font-weight:600}
.pbadge{display:inline-block;vertical-align:middle;margin-left:8px;font-size:10px;font-weight:800;color:#fff;background:var(--coral);padding:1px 8px;border-radius:2px;letter-spacing:0}
.metarow{display:flex;justify-content:space-between;font-size:9px;color:var(--mut);font-weight:600;padding:6px 2px 0}
.metarow b{color:var(--ink);font-weight:800}
/* 결론 헤드라인 */
.hl{margin-top:16px}
.hl .rule{width:34px;height:4px;background:var(--coral);margin-bottom:9px}
.hl h2{font-size:21px;font-weight:800;letter-spacing:-.025em;line-height:1.3}
.hl p{font-size:10.5px;color:var(--sub);margin-top:5px}
.hl p b{color:var(--ink)}
/* KPI: 검정 상단선, 면 채움 없음 */
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:14px 0 0}
.kpi{border-top:2.5px solid var(--ink);padding:7px 0 0}
.kpi .l{font-size:9px;color:var(--mut);font-weight:700}
.kpi .v{font-size:22px;font-weight:800;letter-spacing:-.03em;margin:2px 0 3px}
.kpi .v small{font-size:10px;font-weight:700;color:var(--sub);margin-left:1px}
.kpi .s{font-size:8.6px;color:var(--mut);font-weight:600;line-height:1.6}
.kpi .s .up,.kpi .s .dn{font-weight:800}
/* 핵심 포인트 */
.pts{margin-top:16px;border-top:1px solid var(--ink);border-bottom:1px solid var(--line)}
.pts .t{font-size:9px;font-weight:800;color:var(--mut);letter-spacing:.06em;padding:6px 0 2px}
.pts ul{list-style:none}
.pts li{display:grid;grid-template-columns:52px 1fr;gap:8px;align-items:baseline;padding:4px 0;border-top:1px solid #EEF0F3;font-size:10.4px;color:#26303C}
.pts li:first-child{border-top:0}
.tag{font-size:9px;font-weight:800;color:var(--coral)}
.pts b{font-weight:800;color:var(--ink)}
/* 섹션: 라벨 + 결론형 제목 */
.sec{margin-top:20px}
.sh{border-top:1px solid var(--ink);padding-top:6px;margin-bottom:8px}
.sh .lab{display:flex;justify-content:space-between;font-size:9px;font-weight:800;color:var(--mut);letter-spacing:.04em}
.sh .lab .no{color:var(--coral);margin-right:5px}
.sh .lab .sub{font-weight:600;letter-spacing:0}
.sh h2{font-size:15px;font-weight:800;letter-spacing:-.02em;margin-top:3px;line-height:1.35}
.desc{font-size:9.6px;color:var(--sub);margin:-2px 0 6px}
.desc b{color:var(--ink)}
/* 표 */
table{width:100%;border-collapse:collapse;font-size:10px}
th{font-size:8.8px;color:var(--mut);font-weight:700;text-align:center;padding:5px 5px;border-bottom:1.5px solid var(--ink);white-space:nowrap}
td{text-align:center;padding:6px 5px;border-bottom:1px solid #EEF0F3;white-space:nowrap}
tbody tr:last-child td{border-bottom:1.5px solid var(--ink)}
th:first-child,td:first-child{text-align:left;padding-left:2px}
td:first-child{font-weight:700}
tr.top td{font-weight:800}
td .st{color:var(--mut);font-weight:600;font-size:9px;margin-left:3px}
td .dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:6px;vertical-align:1px}
tr.tot td{font-weight:800}
.ib{display:grid;grid-template-columns:1fr 46px;align-items:center;gap:6px}
.ib .tr{height:7px;background:#F0F2F5;overflow:hidden}
.ib .tr i{display:block;height:100%;background:var(--gray)}
tr.top .ib .tr i{background:var(--ink)}
.ib span{text-align:right}
.up{color:var(--coral);font-weight:800}.dn{color:var(--navy);font-weight:800}.na{color:#C5CCD5}
/* 카드 */
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{border-top:1px solid var(--line);padding-top:7px}
.card .ct{font-size:11px;font-weight:800}
.card .cs{font-size:8.6px;color:var(--mut);margin:1px 0 6px;font-weight:600}
.card .ins{border-left:3px solid var(--coral);padding:1px 0 1px 7px;font-size:9.4px;font-weight:700;color:var(--ink);margin-top:7px}
.lg2{display:flex;gap:10px;font-size:8.6px;color:var(--sub);font-weight:700;margin-top:2px}
.lg2 i{display:inline-block;width:9px;height:9px;margin-right:4px;vertical-align:-1px}
/* 히트맵 */
.hm{width:100%;border-collapse:separate;border-spacing:2px;font-size:8.8px}
.hm th{font-size:8px;color:var(--mut);font-weight:700;padding:2px 1px;text-align:center;border:0}
.hm th.cur{color:var(--coral);font-weight:800}
.hm td{text-align:center;padding:3.2px 1px;border-radius:2px;border:0;font-weight:700}
.hm td.hm-t{background:none;text-align:left;padding-left:2px;font-weight:800;color:var(--ink)}
.hm td.hm-e{background:#F8FAFC;color:#CBD2DA}
.hm tr:last-child td{border-bottom:0}
/* 상대팀 */
.opp{display:inline-block;padding:0 4px;margin:1px 1px;border-radius:2px;font-size:8.8px;font-weight:700;line-height:15px}
.opp.ou{color:#C6452B;background:#FDECE7}.opp.od{color:var(--navy);background:#E3E8F0}.opp.on{color:#5B6676;background:#EEF0F3}
td.opc{white-space:normal;text-align:left;line-height:1.55}
/* 날씨 */
.wv{font-size:24px;font-weight:800;letter-spacing:-.03em}
.brow{display:grid;grid-template-columns:30px 1fr 92px;align-items:center;gap:8px;padding:3px 0}
.blab{font-size:9.5px;font-weight:800;color:var(--sub)}
.btrk{height:11px;background:#F0F2F5;overflow:hidden}
.bfill{height:100%;background:var(--gray)}
.bfill.c{background:var(--coral)}
.bval{font-size:9.5px;font-weight:700;text-align:right}
.note{font-size:8.6px;color:var(--mut);margin-top:5px;line-height:1.55}
.empty{font-size:9.8px;color:var(--sub);background:var(--soft);padding:8px 11px}
.mini{display:flex;justify-content:space-between;align-items:center;font-size:9px;color:var(--mut);font-weight:700;padding-bottom:6px;border-bottom:2.5px solid var(--ink)}
.mini b{color:var(--ink);font-weight:800}.mini .c{color:var(--coral)}
.foot{margin-top:18px;padding-top:8px;border-top:1px solid var(--ink);font-size:8.4px;color:var(--mut);line-height:1.65}
.foot b{color:var(--sub)}
</style>
"""


def month_cancels(y,m):
    try:
        cd=json.load(open('cancellations.json',encoding='utf-8'))
        items=cd.get('items',[]); upd=cd.get('_meta',{}).get('updated','')
    except Exception:
        return [],''
    ym=f'{y}-{m:02d}'
    return [c for c in items if str(c.get('date','')).startswith(ym)],upd

REASON_ORDER=['우천취소','폭염취소','미세먼지취소','그라운드사정','기타']
def sec_head(no,lab,title,sub=''):
    """섹션 머리: 번호·분류 라벨(작게) + 결론형 제목(굵게)"""
    return (f'<div class="sh"><div class="lab"><span><span class="no">{no}</span>{lab}</span>'
            f'<span class="sub">{sub}</span></div><h2>{title}</h2></div>')

def cancel_section(y,m,sec_no='06'):
    """월간 취소 경기: 홈팀 × 사유별 건수 표."""
    cs,upd=month_cancels(y,m)
    if not cs:
        return ('<div class="sec">'+sec_head(sec_no,'취소 경기','이 달 취소 경기 없음','홈팀 기준 · KBO 비고란 자동 수집')
                +'<div class="empty">이 달 집계된 취소 경기 없음</div></div>')
    reasons=[r for r in REASON_ORDER if any((c.get('reason') or '기타')==r for c in cs)]
    reasons+=sorted(set((c.get('reason') or '기타') for c in cs)-set(reasons))
    per={}
    for c in cs:
        t=c.get('home','?'); r=c.get('reason') or '기타'
        per.setdefault(t,{}).setdefault(r,0); per[t][r]+=1
    order=sorted(per.keys(),key=lambda t:-sum(per[t].values()))
    th=''.join(f'<th>{r.replace("취소","")}</th>' for r in reasons)
    rows=[]
    for t in order:
        tds=''.join(f'<td>{per[t].get(r) or "<span class=na>-</span>"}</td>' for r in reasons)
        rows.append(f'<tr><td><span class="dot" style="background:{TCOL.get(t,"#888")}"></span>{t}<span class="st">{STAD.get(t,"")}</span></td>'
                    f'{tds}<td><b>{sum(per[t].values())}</b></td></tr>')
    cnt=lambda r:sum(1 for c in cs if (c.get('reason') or '기타')==r)
    tot_r=''.join(f'<td>{cnt(r)}</td>' for r in reasons)
    top=max(reasons,key=cnt)
    ttl=(f'취소 {len(cs)}경기, 전부 {top.replace("취소","")}' if cnt(top)==len(cs)
         else f'취소 {len(cs)}경기, 최다 사유 {top.replace("취소","")} {cnt(top)}건')
    head='<div class="sec">'+sec_head(sec_no,'취소 경기',ttl,'홈팀 기준 · KBO 비고란 자동 수집'+(f' · 기준일 {upd}' if upd else ''))
    desc=''
    tbl=('<table><thead><tr><th>홈팀</th>'+th+'<th>합계</th></tr></thead><tbody>'+''.join(rows)
         +f'<tr class="tot"><td>전체</td>{tot_r}<td>{len(cs)}</td></tr></tbody></table>')
    return head+desc+tbl+'</div>'

def build_html(y,m,cur,prevM,prevY,tcur,tprev,rank_cur,rankrows,r,season,
               opp_rows,opp_beta,
               temp_cur,temp_prev,rain_gs,clear_gs,league=None):
    head=('<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">'
          '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">'
          +CSS+'</head><body>')
    pm=m-1 if m>1 else 12
    NA='<span class="na">-</span>'
    def rel(c,p):
        return None if p in (None,0) else (c-p)/abs(p)*100
    def chip(d,unit='%',lab=''):
        if d is None: return f'{lab} -'
        dec=1 if unit in ('%p','℃') else 0
        if round(d,dec)==0: return f'{lab} 0{unit}'
        cls='up' if d>0 else 'dn'; arr='▲' if d>0 else '▼'
        return f'{lab} <span class="{cls}">{arr}{abs(d):.{dec}f}{unit}</span>'
    def signed(d,dec=0,unit='%'):
        if d is None: return NA
        if round(d,dec)==0: return f'<span class="na" style="color:#8A93A0;font-weight:700">0{unit}</span>'
        return f'<span class="{"up" if d>=0 else "dn"}">{d:+.{dec}f}{unit}</span>'
    def tname(t):
        return f'<span class="dot" style="background:{TCOL.get(t,"#888")}"></span>{t}<span class="st">{STAD.get(t,"")}</span>'

    dM=rel(cur['avg'],prevM['avg'] if prevM else None)
    dY=rel(cur['avg'],prevY['avg'] if prevY else None)
    prov=(date.today().year==y and date.today().month==m)
    pbadge='<span class="pbadge">잠정</span>' if prov else ''

    # ── 마스트헤드: 보고서명(강조) ──
    hd=(f'<div class="mast"><div><div class="eb">KBO ATTENDANCE MONTHLY REPORT</div>'
        f'<h1>KBO 월간 관중 리포트{pbadge}</h1></div>'
        f'<div class="iss"><b>{y}년 {m}월호</b><span>발행 {date.today():%Y.%m.%d} · 서던포스트</span></div></div>'
        f'<div class="metarow"><span>분석 대상 <b>{y}년 {m}월 정규시즌 {cur["n"]}경기</b> · 홈경기 관중 기준{" · 진행 중 잠정" if prov else ""}</span>'
        f'<span>(주)서던포스트 데이터분석</span></div>')

    # ── KPI 5 ──
    cs,_=month_cancels(y,m)
    occD=(cur['occ']-prevM['occ'])*100 if prevM else None
    occY=(cur['occ']-prevY['occ'])*100 if prevY else None
    totY=rel(cur['tot'],prevY['tot'] if prevY else None)
    sellP=cur['sell']-prevM['sell'] if prevM else None
    kpis=('<div class="kpis">'
          f'<div class="kpi"><div class="l">경기당 평균 관중</div><div class="v">{f(cur["avg"])}<small>명</small></div>'
          f'<div class="s">{chip(dM,"%","전월")} · {chip(dY,"%","전년")}</div></div>'
          f'<div class="kpi"><div class="l">총 관중</div><div class="v">{man(cur["tot"])}<small>만 명</small></div>'
          f'<div class="s">{cur["n"]}경기 합산{" · "+chip(totY,"%","전년") if prevY else ""}</div></div>'
          f'<div class="kpi"><div class="l">평균 좌석 점유율</div><div class="v">{cur["occ"]*100:.1f}<small>%</small></div>'
          f'<div class="s">{chip(occD,"%p","전월")} · {chip(occY,"%p","전년")}</div></div>'
          f'<div class="kpi"><div class="l">완전 매진</div><div class="v">{cur["sell"]}<small>경기</small></div>'
          f'<div class="s">전체의 {cur["sell"]/cur["n"]*100:.0f}%'
          +(f' · 전월 {prevM["sell"]}경기' if prevM else '')+'</div></div>'
          f'<div class="kpi"><div class="l">취소 경기</div><div class="v">{len(cs)}<small>경기</small></div>'
          f'<div class="s">우천 {sum(1 for c in cs if (c.get("reason") or "")=="우천취소")}경기</div></div>'
          '</div>')

    # ── 핵심 포인트 (개조식) ──
    rk={x['t']:(x['r0'],x['r1']) for x in rankrows}
    oshift={}
    for x in opp_rows:
        def om(cnt):
            tot=sum(cnt.values())
            return sum(opp_beta.get(a,0)*n for a,n in cnt.items())/tot if tot else 0
        oshift[x['h']]=om(x['cur_opp'])-om(x['prev_opp'])
    def zone(x): return '상위권' if x<=3.5 else '하위권' if x>=7.5 else '중위권'
    def rank_txt(t):
        """순위 변화는 방향과 무관하게 항상 표기(상승·하락·유지 + 현재 위치)"""
        if t not in rk: return None
        r0,r1=rk[t]; imp=r0-r1
        if abs(imp)>=1.0: w='순위 상승' if imp>0 else '순위 하락'
        elif abs(imp)>=0.05: w='순위 소폭 상승' if imp>0 else '순위 소폭 하락'
        else: return f'순위 유지 {r1:.1f}위({zone(r1)})'
        return f'{w} {r0:.1f}→{r1:.1f}위({zone(r1)})'
    def reasons(t,gain):
        rs=[]
        rt=rank_txt(t)
        if rt: rs.append(rt)
        sh=oshift.get(t)
        if sh is not None:
            if gain and sh>=150: rs.append('인기 원정팀 홈경기 증가')
            elif (not gain) and sh<=-150: rs.append('인기 원정팀 홈경기 감소')
        return rs[:2]
    chg=sorted([{'t':t,'d':rel(tcur[t]['avg'],tprev[t]['avg'])} for t in tcur if tprev.get(t) and tprev[t]['avg']],
               key=lambda x:x['d'])
    pts=[]
    ups=[c for c in chg if c['d']>0]; dns=[c for c in chg if c['d']<0]
    if ups:
        c=ups[-1]; rs=reasons(c['t'],True)
        pts.append(('최대 증가',f'<b>{c["t"]}</b> {signed(c["d"])}'+(f' · {" · ".join(rs)}' if rs else '')))
    if dns:
        c=dns[0]; rs=reasons(c['t'],False)
        pts.append(('최대 감소',f'<b>{c["t"]}</b> {signed(c["d"])}'+(f' · {" · ".join(rs)}' if rs else '')))
    if r is not None and rankrows:
        lab=('양의 상관' if r>0.1 else '음의 상관' if r<-0.1 else '관계 미약')
        txt=(' · 순위 오른 구단 관중 증가 경향' if r>=0.25 else ' · 순위와 반대 방향 움직임' if r<=-0.25 else '')
        def grp(cond):
            xs=[x['dAtt'] for x in rankrows if cond(x['r0']-x['r1'])]
            return (len(xs),sum(xs)/len(xs)) if xs else (0,None)
        nu,au=grp(lambda d:d>=0.05); nd,ad=grp(lambda d:d<=-0.05); nf,af=grp(lambda d:abs(d)<0.05)
        gb=[]
        if nu: gb.append(f'순위 상승 {nu}개 구단 관중 평균 {signed(au)}')
        if nd: gb.append(f'하락 {nd}개 구단 {signed(ad)}')
        if nf: gb.append(f'유지 {nf}개 구단 {signed(af)}')
        pts.append(('순위',' · '.join(gb)+f' · <b>{lab} (r={r:.2f})</b>'))
    if oshift:
        mx=max(oshift,key=oshift.get); mn=min(oshift,key=oshift.get); bits=[]
        if oshift[mx]>=300: bits.append(f'<b>{mx}</b> 유리(인기 원정팀 증가)')
        if oshift[mn]<=-300: bits.append(f'<b>{mn}</b> 불리(인기 원정팀 감소)')
        if bits: pts.append(('상대팀',' · '.join(bits)))
    if rain_gs and clear_gs:
        rn=len(rain_gs); ravg=sum(g['att'] for g in rain_gs)/rn
        cavg=sum(g['att'] for g in clear_gs)/len(clear_gs); rd=rel(ravg,cavg)
        if rd is not None and abs(rd)>=8 and rn>=3:
            pts.append(('날씨',f'우천 {rn}경기 평균 {f(ravg)}명 · 맑은 날 대비 {signed(rd)}'))
    # 결론 헤드라인(해석형)
    if dM is None: hl=f'{m}월 경기당 평균 {f(cur["avg"])}명'
    else:
        hl=(f'{m}월 경기당 평균 {f(cur["avg"])}명, 전월 대비 '
            +(f'{abs(dM):.0f}% {"증가" if dM>0 else "감소"}' if abs(dM)>=0.5 else '보합'))
        if dY is not None and abs(dY)>=0.5:
            hl+=f' · 전년 동월 대비 {abs(dY):.0f}% {"증가" if dY>0 else "감소"}'
    lead_bits=[]
    if ups: lead_bits.append(f'최대 증가 <b>{ups[-1]["t"]} {ups[-1]["d"]:+.0f}%</b>')
    if dns: lead_bits.append(f'최대 감소 <b>{dns[0]["t"]} {dns[0]["d"]:+.0f}%</b>')
    lead_bits.append(f'완전 매진 <b>{cur["sell"]}경기</b>')
    hlH=f'<div class="hl"><div class="rule"></div><h2>{hl}</h2></div>'
    ptsH=('<div class="pts"><div class="t">핵심 포인트</div><ul>'
          +''.join(f'<li><span class="tag">{t}</span><span>{x}</span></li>' for t,x in pts[:6])+'</ul></div>')

    # ── 01 구단별 현황 ──
    order=sorted(tcur.keys(),key=lambda t:-tcur[t]['avg'])
    amax=max(tcur[t]['avg'] for t in order) if order else 1
    rows=[]
    for t in order:
        c=tcur[t]; p=tprev.get(t)
        d=rel(c['avg'],p['avg']) if p else None
        od=(c['occ']-p['occ'])*100 if p else None
        rkv=rank_cur.get(t)
        if t in rk:
            ch=rk[t][0]-rk[t][1]
            rkc=(f'<span class="up">▲{ch:.1f}</span>' if ch>=0.05 else f'<span class="dn">▼{abs(ch):.1f}</span>' if ch<=-0.05 else NA)
        else: rkc=NA
        rows.append(f'<tr{" class=top" if order.index(t)<3 else ""}><td>{tname(t)}</td><td>{c["n"]}</td>'
                    f'<td style="width:30%"><div class="ib"><div class="tr"><i style="width:{c["avg"]/amax*100:.1f}%"></i></div><span>{f(c["avg"])}</span></div></td>'
                    f'<td>{c["occ"]*100:.1f}%</td><td>{f"{rkv:.1f}" if rkv is not None else NA}</td><td>{rkc}</td>'
                    f'<td>{signed(d)}</td><td>{signed(od,1,"%p")}</td></tr>')
    t1=f'평균 관중 1위 {order[0]} {f(tcur[order[0]]["avg"])}명' if order else '구단별 현황'
    if ups: t1+=f' · 최대 증가 {ups[-1]["t"]} {ups[-1]["d"]:+.0f}%'
    sec1=('<div class="sec">'+sec_head('01','구단별 현황',t1,'홈경기 기준 · 평균 관중 내림차순')
          +'<table><thead><tr><th>구단</th><th>경기</th><th>평균 관중(명)</th><th>점유율</th><th>평균 순위</th><th>순위 변화</th>'
          f'<th>관중 전월비</th><th>점유율 전월비</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')

    # ── 02 시즌 추이 ──
    ins_l=ins_h=''
    t2='시즌 추이'
    if league and league['cur'].get(m) and league['prev'].get(m):
        ly=rel(league['cur'][m],league['prev'][m])
        t2=f'{m}월 리그 평균 {f(league["cur"][m])}명, 전년 동월 대비 {ly:+.0f}%'
        nup=sum(1 for mo in league['months'] if league['prev'].get(mo) and league['cur'][mo]>league['prev'][mo])
        ins_l=f'{len(league["months"])}개월 중 {nup}개월 전년 대비 증가'
    if season and season.get('months'):
        so=season['occ']; lm=season['months'][-1]
        full=[t for t in season['order'] if so.get(t,{}).get(lm) is not None and so[t][lm]>=0.95]
        ins_h=(f'{m}월 점유율 95% 이상 {len(full)}개 구단'+(f' ({"·".join(full)})' if full else ''))
    if season and season.get('months'):
        lb=(svg_league_bars(league['months'],league['cur'],league['prev'],y) if league else '')
        mh=('<div class="two">'
            f'<div class="card"><div class="ct">리그 월별 평균 관중</div><div class="cs">{y}년 vs {y-1}년 · 경기당 · 하단 = 전년 동월비</div>'
            f'{lb}<div class="lg2"><span><i style="background:{CORAL}"></i>{y}년 {m}월</span><span><i style="background:#5B6676"></i>{y}년</span><span><i style="background:#D3D9E1"></i>{y-1}년</span></div>'
            f'<div class="ins">{ins_l}</div></div>'
            '<div class="card"><div class="ct">구단별 월 좌석 점유율(%)</div><div class="cs">진할수록 만석 · 오른쪽 = 시즌 평균</div>'
            f'{html_month_heat(season["months"],season["order"],season["occ"])}<div class="ins">{ins_h}</div></div>'
            '</div>')
    else:
        mh='<div class="empty">월별 추이 데이터 부족</div>'
    sec2=('<div class="sec">'+sec_head('02','시즌 추이',t2,f'{y}시즌 누적 · 홈경기 기준')+mh+'</div>')

    # ── 03 상대팀 ──
    def opp_list(counter):
        if not counter: return NA
        items=sorted(counter.items(),key=lambda kv:-(opp_beta.get(kv[0],0)))
        out=[]
        for a,n in items:
            b=opp_beta.get(a,0); cls='ou' if b>300 else 'od' if b<-300 else 'on'
            out.append(f'<span class="opp {cls}">{a}{("×"+str(n)) if n>1 else ""}</span>')
        return ''.join(out)
    if opp_rows:
        otr=''.join(f'<tr><td>{tname(x["h"])}</td><td class="opc">{opp_list(x["prev_opp"])}</td>'
                    f'<td class="opc">{opp_list(x["cur_opp"])}</td><td>{signed(x["pct"])}</td></tr>' for x in opp_rows)
        ob=(f'<table><thead><tr><th>홈팀</th><th>{pm}월 홈경기 상대</th><th>{m}월 홈경기 상대</th><th>관중 전월비</th></tr></thead>'
            f'<tbody>{otr}</tbody></table>'
            '<div class="note">상대팀 색 = 방문 시 홈 평균 대비 관중 동원력(시즌 누적) · '
            '<span class="opp ou">코랄</span> 평균 이상 · <span class="opp od">네이비</span> 평균 이하 · <span class="opp on">회색</span> 비슷 · ×n = 경기 수</div>')
    else:
        ob='<div class="empty">이 달 홈경기 데이터 부족</div>'
    t3='상대팀 구성 변화'
    if oshift:
        mx=max(oshift,key=oshift.get); mn=min(oshift,key=oshift.get); b3=[]
        if oshift[mx]>=150: b3.append(f'인기 원정팀 증가 {mx}')
        if oshift[mn]<=-150: b3.append(f'감소 {mn}')
        if b3: t3=' · '.join(b3)
    sec3=('<div class="sec">'+sec_head('03','상대팀 구성',t3,'인기 원정팀 증가 시 홈 관중 유리')+ob+'</div>')

    # ── 04 순위 ──
    if rankrows:
        trows=[]
        for x in sorted(rankrows,key=lambda x:-x['a1']):
            ch=x['r0']-x['r1']
            rkc=(f'<span class="up">▲{ch:.1f}</span>' if ch>0.05 else f'<span class="dn">▼{abs(ch):.1f}</span>' if ch<-0.05 else NA)
            rc=x.get('rec')
            if rc:
                pr=f'{rc["pct"]:.3f}'; pr=pr[1:] if pr.startswith('0') else pr
                rec=f'{rc["w"]}-{rc["d"]}-{rc["l"]}<span class="st">{pr}</span>'
            else: rec=NA
            trows.append(f'<tr><td>{tname(x["t"])}</td><td>{rec}</td><td>{x["r0"]:.1f}</td><td>{x["r1"]:.1f}</td><td>{rkc}</td>'
                         f'<td>{f(x["a0"])}</td><td>{f(x["a1"])}</td><td>{signed(x["dAtt"])}</td></tr>')
        rdesc=''
        if r is not None:
            lab=('양의 상관' if r>0.1 else '음의 상관' if r<-0.1 else '관계 미약')
            rdesc=''
        rh=(rdesc+'<table><thead><tr><th>구단</th><th>성적(승-무-패 승률)</th><th>전월 순위</th><th>이번달 순위</th><th>변화</th>'
            f'<th>전월 평균</th><th>이번달 평균</th><th>관중 변화</th></tr></thead><tbody>{"".join(trows)}</tbody></table>'
            '<div class="note">성적 = 그 달 홈·원정 전체 · 순위 = 경기일 기준 순위의 월 평균 · 정렬 = 이번달 평균 관중 내림차순</div>')
    else:
        rh='<div class="empty">전월 비교 가능한 순위 데이터 부족</div>'
    t4='순위와 관중'
    if r is not None and rankrows:
        lab=('양의 상관' if r>0.1 else '음의 상관' if r<-0.1 else '관계 미약')
        t4=f'순위 변화와 관중 변화 {lab}(r={r:.2f})'+(', 순위 오른 구단 관중 증가' if r>=0.25 else '')
    sec4=('<div class="sec">'+sec_head('04','순위와 관중',t4,'경기일 기준 평균 순위 · 전월 대비')+rh+'</div>')

    # ── 05 날씨 ──
    rn=len(rain_gs); cn=len(clear_gs)
    if temp_cur is None and rn+cn==0:
        wb='<div class="empty">날씨 데이터 미수집 · fetch_weather.py 실행 후 재생성</div>'
    else:
        ravg=sum(g['att'] for g in rain_gs)/rn if rn else 0
        cavg=sum(g['att'] for g in clear_gs)/cn if cn else 0
        tempd=(temp_cur-temp_prev) if (temp_cur is not None and temp_prev is not None) else None
        bmax=max(ravg,cavg,1)
        def br(lab,v,n,cls=''):
            return (f'<div class="brow"><div class="blab">{lab}</div><div class="btrk"><div class="bfill {cls}" style="width:{max(2,v/bmax*100):.1f}%"></div></div>'
                    f'<div class="bval">{f(v)}명 <span class="st" style="color:#8A93A0">{n}경기</span></div></div>')
        tchip=(f'{chip(tempd,"℃","전월")} <span style="color:#8A93A0">전월 {temp_prev:.1f}℃</span>' if tempd is not None else '')
        rd=rel(ravg,cavg) if rn and cavg else None
        wb=('<div class="two">'
            f'<div class="card"><div class="ct">경기 시간대 평균 기온</div><div class="cs">14~21시 · 구장 좌표 기준</div>'
            f'<div class="wv">{f"{temp_cur:.1f}℃" if temp_cur is not None else "-"}</div><div style="margin-top:4px;font-size:9px">{tchip}</div></div>'
            f'<div class="card"><div class="ct">강수 여부별 평균 관중</div><div class="cs">'
            +(f'우천 경기 맑은 날 대비 {signed(rd)}' if rd is not None else '이 달 우천 경기 없음')+'</div>'
            +br('맑음',cavg,cn)+(br('우천',ravg,rn,'c') if rn else '')+'</div></div>')
    t5='날씨'
    if rn and cn:
        rd5=rel(sum(g['att'] for g in rain_gs)/rn,sum(g['att'] for g in clear_gs)/cn)
        t5=f'우천 {rn}경기 평균 관중, 맑은 날 대비 {rd5:+.0f}%'
    elif temp_cur is not None:
        t5=f'경기 시간대 평균 {temp_cur:.1f}℃, 우천 경기 없음'
    sec5=('<div class="sec">'+sec_head('05','날씨',t5,'실제 강수 여부 기준')+wb+'</div>')

    foot=('<div class="foot"><b>출처</b> 관중·결과 KBO 공식 기록 · 날씨 Open-Meteo 과거 기상(구장 좌표, 경기 시간대) · 취소 KBO 일정 비고란<br>'
          '<b>정의</b> 점유율 = 관중 ÷ 구장 수용인원 · 완전 매진 = 점유율 100% 이상 · 순위 = 경기 직전 기준 · 진행 중 시즌은 잠정값<br>'
          '제작 (주)서던포스트</div>')
    mini=lambda p:f'<div class="mini"><span><b>KBO 월간 관중 리포트</b> <span class="c">{y}년 {m}월호</span></span><span>{p}</span></div>'

    return (head
            +'<div class="page">'+hd+hlH+kpis+ptsH+sec1+'</div>'
            +'<div class="page">'+mini('2 / 3')+sec2+sec3+'</div>'
            +'<div class="page">'+mini('3 / 3')+sec4+sec5+cancel_section(y,m,'06')+foot+'</div>'
            +'</body></html>')

def league_monthly(games,y,upto_m):
    def agg(yy,lim):
        by={}
        for g in games:
            if g['yr']==yy and 3<=g['mo']<=lim: by.setdefault(g['mo'],[]).append(g['att'])
        return {mo:sum(a)/len(a) for mo,a in by.items() if len(a)>=10}
    cur=agg(y,upto_m); prev=agg(y-1,upto_m)
    return {'months':sorted(cur),'cur':cur,'prev':prev}


# ── 분석 파이프라인 ─────────────────────────────────────
def opponent_analysis(games,y,m,py,pm):
    """홈팀별: 전월 상대팀 vs 이번달 상대팀, 홈 평균관중 전월대비 증감률.
       beta[a]=그 팀이 방문했을 때 홈 평균 대비 ±명(시즌 누적, 색 구분용)."""
    cur=month_games(games,y,m); prev=month_games(games,py,pm)
    season=[g for g in games if g['yr']==y and 0<g['mo']<=m]
    hb={}
    for g in season: hb.setdefault(g['home'],[]).append(g['att'])
    host_season={h:sum(a)/len(a) for h,a in hb.items()}
    ab={}
    for g in season:
        a=g.get('away'); b=host_season.get(g['home'])
        if a and b is not None: ab.setdefault(a,[]).append(g['att']-b)
    beta={a:sum(v)/len(v) for a,v in ab.items()}
    def hgroup(gs):
        d={}
        for g in gs:
            x=d.setdefault(g['home'],{'att':[],'opp':[]})
            x['att'].append(g['att'])
            if g.get('away'): x['opp'].append(g['away'])
        return d
    hc=hgroup(cur); hp=hgroup(prev)
    rows=[]
    for h,c in hc.items():
        cavg=sum(c['att'])/len(c['att'])
        p=hp.get(h); pavg=(sum(p['att'])/len(p['att'])) if p else None
        rows.append({'h':h,'cavg':cavg,'pavg':pavg,
                     'pct':((cavg-pavg)/pavg*100) if pavg else None,
                     'prev_opp':Counter(p['opp']) if p else Counter(),
                     'cur_opp':Counter(c['opp'])})
    rows.sort(key=lambda x:-x['cavg'])
    return rows, beta

def season_monthly_stats(games,y,upto_m):
    """y시즌 누적: 구단별·월별 평균 관중/점유율 (홈경기 기준, upto_m 까지)."""
    gs=[g for g in games if g['yr']==y and 0<g['mo']<=upto_m]
    months=sorted({g['mo'] for g in gs})
    by={}
    for g in gs: by.setdefault(g['home'],{}).setdefault(g['mo'],[]).append(g)
    att={t:{mo:sum(x['att'] for x in a)/len(a) for mo,a in mm.items()} for t,mm in by.items()}
    occ={t:{mo:sum(x['occ'] for x in a)/len(a) for mo,a in mm.items()} for t,mm in by.items()}
    order=sorted(by.keys(),key=lambda t:-sum(x['att'] for mo in by[t] for x in by[t][mo]))
    return {'months':months,'order':order,'att':att,'occ':occ}

def analyze(games,y,m):
    cur=summarize(month_games(games,y,m))
    if not cur: return None
    py,pm=(y,m-1) if m>1 else (y-1,12)
    prevM=summarize(month_games(games,py,pm))
    prevY=summarize(month_games(games,y-1,m))
    tcur=team_stats(month_games(games,y,m))
    tprev=team_stats(month_games(games,py,pm))
    # 순위(경기일 기준 한 달 평균) — 전월 대비
    rank_cur=team_rank_avg_allgames(games,y,m)
    rank_prev=team_rank_avg_allgames(games,py,pm)
    rows=[]
    recs=team_records(games,y,m)
    for t in tcur:
        c=tcur[t]; p=tprev.get(t); rc=rank_cur.get(t); rp=rank_prev.get(t)
        if not p or rc is None or rp is None or p['avg']==0: continue
        rows.append({'t':t,'r0':rp,'r1':rc,'dRank':rc-rp,'rec':recs.get(t),
                     'a0':p['avg'],'a1':c['avg'],'dAtt':(c['avg']-p['avg'])/p['avg']*100})
    r=pearson([-x['dRank'] for x in rows],[x['dAtt'] for x in rows]) if len(rows)>=3 else None
    # 기온
    cg=month_games(games,y,m); pg=month_games(games,py,pm)
    tc=[g['temp'] for g in cg if g['temp'] is not None]; tp=[g['temp'] for g in pg if g['temp'] is not None]
    temp_cur=sum(tc)/len(tc) if tc else None; temp_prev=sum(tp)/len(tp) if tp else None
    wxg=[g for g in cg if (g.get('rain') is not None) or (g.get('temp') is not None)]
    rain_gs=[g for g in wxg if g['rainY']]; clear_gs=[g for g in wxg if not g['rainY']]
    opp_rows,opp_beta=opponent_analysis(games,y,m,py,pm)
    return dict(cur=cur,prevM=prevM,prevY=prevY,tcur=tcur,tprev=tprev,
                rank_cur=rank_cur,rankrows=rows,r=r,season=season_monthly_stats(games,y,m),
                opp_rows=opp_rows,opp_beta=opp_beta,league=league_monthly(games,y,m),
                temp_cur=temp_cur,temp_prev=temp_prev,rain_gs=rain_gs,clear_gs=clear_gs)

# ── PDF 인쇄 (Playwright) ───────────────────────────────
def html_to_pdf(html_path,pdf_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br=pw.chromium.launch(args=['--no-sandbox'])
        page=br.new_context().new_page()
        page.goto('file://'+os.path.abspath(html_path),wait_until='networkidle')
        page.wait_for_timeout(800)  # 웹폰트 로드 여유
        page.pdf(path=pdf_path,format='A4',print_background=True,
                 margin={'top':'0','bottom':'0','left':'0','right':'0'})
        br.close()

# ── 메일 발송 (선택) ────────────────────────────────────
def send_mail(pdf_path,y,m):
    user=os.getenv('GMAIL_USER'); pw=os.getenv('GMAIL_APP_PASSWORD'); to=os.getenv('REPORT_TO')
    if not (user and pw and to):
        print('  메일 환경변수 미설정 → 발송 생략'); return False
    import smtplib
    from email.message import EmailMessage
    msg=EmailMessage()
    msg['Subject']=f'[KBO 관중 분석] {y}년 {m}월 월간 리포트'
    msg['From']=user; msg['To']=to
    msg.set_content(f'{y}년 {m}월 KBO 관중 분석 월간 리포트를 첨부합니다.\n\n자동 발송 (주)서던포스트')
    msg.add_attachment(Path(pdf_path).read_bytes(),maintype='application',subtype='pdf',
                       filename=f'KBO_월간리포트_{y}-{m:02d}.pdf')
    with smtplib.SMTP_SSL('smtp.gmail.com',465) as s:
        s.login(user,pw); s.send_message(msg)
    print(f'  메일 발송 완료 → {to}'); return True

def last_complete_month():
    first=date.today().replace(day=1); last=first-timedelta(days=1)
    return last.year,last.month

def month_range(fy,fm,ty,tm):
    y,m=fy,fm
    while (y,m)<=(ty,tm):
        yield y,m
        m+=1
        if m>12: m=1; y+=1

def update_manifest(entries,outdir):
    """reports/reports.json 에 생성된 월을 병합(기존 보존)."""
    mf=outdir/'reports.json'; data={}
    if mf.exists():
        try:
            for e in json.loads(mf.read_text(encoding='utf-8')).get('reports',[]):
                data[e['ym']]=e
        except: pass
    for e in entries: data[e['ym']]=e
    out=sorted(data.values(),key=lambda e:e['ym'],reverse=True)
    mf.write_text(json.dumps({'updated':date.today().isoformat(),'reports':out},
                             ensure_ascii=False,indent=2),encoding='utf-8')
    return mf

def generate_one(games,y,m,outdir,make_pdf=True):
    res=analyze(games,y,m)
    if not res:
        print(f'  {y}-{m:02d}: 경기 데이터 없음 → 건너뜀'); return None
    html=build_html(y,m,res['cur'],res['prevM'],res['prevY'],res['tcur'],res['tprev'],
                    res['rank_cur'],res['rankrows'],res['r'],res['season'],
                    res['opp_rows'],res['opp_beta'],
                    res['temp_cur'],res['temp_prev'],res['rain_gs'],res['clear_gs'],res['league'])
    name=f'KBO_월간리포트_{y}-{m:02d}'
    (outdir/(name+'.html')).write_text(html,encoding='utf-8')
    if make_pdf:
        try:
            html_to_pdf(str(outdir/(name+'.html')),str(outdir/(name+'.pdf')))
            print(f'  {y}-{m:02d}: PDF 생성 ({res["cur"]["n"]}경기)')
        except Exception as e:
            print(f'  {y}-{m:02d}: PDF 단계 건너뜀(Playwright 미설치 등): {e}')
    else:
        print(f'  {y}-{m:02d}: HTML만 생성')
    return {'ym':f'{y}-{m:02d}','file':name+'.pdf','n':res['cur']['n'],
            'avg':round(res['cur']['avg']),'occ':round(res['cur']['occ']*100,1),
            'generated':date.today().isoformat()}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--month',help='YYYY-MM 단일 월 (생략 시 지난달)')
    ap.add_argument('--from',dest='frm',help='YYYY-MM 부터 지난달까지 일괄 생성(백필)')
    ap.add_argument('--json',default='kbo_games.json')
    ap.add_argument('--no-pdf',action='store_true')
    a=ap.parse_args()

    games=load(a.json)
    outdir=Path('reports'); outdir.mkdir(exist_ok=True)
    ty,tm=last_complete_month()
    entries=[]

    if a.frm:
        fy,fm=map(int,a.frm.split('-'))
        print(f'=== 일괄 생성 {fy}-{fm:02d} ~ {ty}-{tm:02d} (지난달까지) ===')
        for y,m in month_range(fy,fm,ty,tm):
            e=generate_one(games,y,m,outdir,not a.no_pdf)
            if e: entries.append(e)
    else:
        ym=a.month or os.getenv('REPORT_YM')
        if ym: y,m=map(int,ym.split('-'))
        else:  y,m=ty,tm
        print(f'=== KBO 월간 리포트 {y}-{m:02d} ===')
        e=generate_one(games,y,m,outdir,not a.no_pdf)
        if e: entries.append(e)

    if entries:
        mf=update_manifest(entries,outdir)
        print(f'  매니페스트 갱신: {mf} (총 {len(entries)}개월 추가/갱신)')
    else:
        print('  생성된 리포트 없음 (해당 기간 경기 데이터 없음)')

if __name__=='__main__':
    main()
