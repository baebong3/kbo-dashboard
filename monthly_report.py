"""
KBO 월간 관중 분석 리포트 생성기
- kbo_games.json 에서 '지난달'(매월 1일 실행 시 직전 달)을 뽑아 다각도 분석
- house-style HTML 생성 → Playwright 로 PDF 인쇄(차트는 전부 인라인 SVG/CSS, JS 의존 없음)
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

# ── 수용인원(대시보드 cap() 과 동일 로직) ───────────────
VENUE_CAP={'포항':12247,'울산':12000,'청주':9500,'사직':23079,'마산':11000,'고척':16000}
CAPY={'LG':23750,'두산':23750,'삼성':24000,'KIA':20500,'SSG':23000,'롯데':23079,'kt':18700,'NC':17983,'키움':16000}
def cap(t, yr, venue=None):
    if venue:
        for k,v in VENUE_CAP.items():
            if k in str(venue): return v
    if (venue and '잠실' in str(venue)) or t in ('LG','두산'):
        return 25000 if yr<=2021 else 23750
    if t=='NC' and yr<=2018: return 11000
    if t=='한화': return 13000 if yr<2025 else 17000
    return CAPY.get(t,20000)

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
        })
    return out

# ── 월 집계 ─────────────────────────────────────────────
def month_games(games,y,m): return [g for g in games if g['yr']==y and g['mo']==m]
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

# ── SVG: 산점도(순위변화 × 관중변화) ────────────────────
def svg_month_lines(months, order, att):
    """월별 구단 평균관중 라인. 세로축 0 미시작(최소값 근처)으로 선 분산 + 오른쪽 끝 팀명."""
    W,H=372,206; pl,pr,pt,pb=42,54,10,22; iw,ih=W-pl-pr,H-pt-pb
    vals=[att[t][mo] for t in order for mo in months if att.get(t,{}).get(mo) is not None]
    if not vals: return '<div class="note">데이터 없음</div>'
    vmin,vmax=min(vals),max(vals); span=(vmax-vmin) or vmax or 1000
    ymin=math.floor(max(0,vmin-span*0.10)/500)*500
    ymax=math.ceil((vmax+span*0.10)/500)*500
    if ymax<=ymin: ymax=ymin+1000
    n=len(months)
    def X(i): return pl+(i/(n-1) if n>1 else 0.5)*iw
    def Y(v): return pt+(1-(v-ymin)/(ymax-ymin))*ih
    s=[f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" font-family="Pretendard,sans-serif">']
    for k in range(5):
        v=ymin+(ymax-ymin)*k/4; yy=Y(v)
        s.append(f'<line x1="{pl}" y1="{yy:.1f}" x2="{pl+iw}" y2="{yy:.1f}" stroke="#F1F3F6"/>')
        s.append(f'<text x="{pl-4}" y="{yy+3:.1f}" text-anchor="end" font-size="8" fill="{MUTED}">{v/1000:.1f}천</text>')
    for i,mo in enumerate(months):
        s.append(f'<text x="{X(i):.1f}" y="{pt+ih+15}" text-anchor="middle" font-size="9" font-weight="700" fill="{MUTED}">{mo}월</text>')
    ends=[]
    for t in order:
        pts=[(X(i),Y(att[t][mo])) for i,mo in enumerate(months) if att.get(t,{}).get(mo) is not None]
        if not pts: continue
        c=TCOL.get(t,'#888')
        s.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x,y in pts)}" fill="none" stroke="{c}" stroke-width="1.8"/>')
        for x,y in pts: s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.1" fill="{c}"/>')
        ends.append({'t':t,'oy':pts[-1][1],'y':pts[-1][1],'c':c})
    ends.sort(key=lambda e:e['y']); gap=9.4
    for i in range(1,len(ends)):
        if ends[i]['y']-ends[i-1]['y']<gap: ends[i]['y']=ends[i-1]['y']+gap
    if ends and ends[-1]['y']>pt+ih:
        over=ends[-1]['y']-(pt+ih)
        for e in ends: e['y']-=over
    for e in ends:
        s.append(f'<line x1="{pl+iw:.1f}" y1="{e["oy"]:.1f}" x2="{pl+iw+3:.1f}" y2="{e["y"]:.1f}" stroke="{e["c"]}" stroke-width="0.7" opacity="0.55"/>')
        s.append(f'<text x="{pl+iw+5:.1f}" y="{e["y"]+3:.1f}" font-size="8.5" font-weight="800" fill="{e["c"]}">{e["t"]}</text>')
    s.append('</svg>'); return ''.join(s)

def html_month_heat(months, order, occ):
    """월별 구단 점유율 히트맵(CSS 표) + 시즌 평균 열."""
    cells=[occ[t][mo] for t in order for mo in months if occ.get(t,{}).get(mo) is not None]
    if not cells: return '<div class="note">데이터 없음</div>'
    mn,mx=min(cells),max(cells)
    def cell(v):
        if v is None: return '<td class="hm-e">·</td>'
        r=(v-mn)/(mx-mn) if mx>mn else 0.6
        return f'<td style="background:rgba(43,58,85,{0.12+r*0.82:.2f});color:{"#fff" if r>0.55 else "#1F2733"}">{v*100:.0f}</td>'
    head='<tr><th>구단</th>'+''.join(f'<th>{mo}월</th>' for mo in months)+'<th>평균</th></tr>'
    rows=[]
    for t in order:
        vs=[occ[t][mo] for mo in months if occ.get(t,{}).get(mo) is not None]
        avgv=sum(vs)/len(vs) if vs else None
        rows.append(f'<tr><td class="hm-t">{t}</td>'+''.join(cell(occ.get(t,{}).get(mo)) for mo in months)+cell(avgv)+'</tr>')
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
        arr='▲' if delta>0.5 else '▼' if delta<-0.5 else '—'
        dchip=f'<span class="chip {cls}">{arr} {abs(delta):.0f}%</span>'
    return (f'<div class="brow"><div class="blab">{label}</div>'
            f'<div class="btrk"><div class="bfill" style="width:{w:.1f}%"></div></div>'
            f'<div class="bval">{sub} {dchip}</div></div>')

# ── HTML 빌드 ───────────────────────────────────────────
CSS = """
<style>
@page{size:A4;margin:14mm 13mm}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Pretendard','Pretendard Variable',-apple-system,sans-serif;color:#16202C;font-size:11px;line-height:1.55;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.mono{font-family:'JetBrains Mono',ui-monospace,monospace;font-feature-settings:'tnum' 1}
.page{padding:0 0 6mm}
.page+.page{page-break-before:always}
/* 인쇄 단락 구분: 섹션/표/카드가 페이지 경계에서 쪼개지지 않게 */
.sec{page-break-inside:avoid;break-inside:avoid}
.sec-h{page-break-after:avoid;break-after:avoid}
.cover,.kpis,.kpi,.cmp,.cmp .box,.wxcard,.lead,.wx,table,tr,.brow,.foot{page-break-inside:avoid;break-inside:avoid}
.cover{background:linear-gradient(135deg,#2B3A55,#1E2A40);color:#fff;border-radius:14px;padding:30px 32px;margin-bottom:18px}
.cover .eyebrow{font-size:11px;letter-spacing:.18em;color:#9DB0C8;font-weight:700;font-family:'JetBrains Mono',monospace}
.cover h1{font-size:27px;font-weight:800;letter-spacing:-.02em;margin:8px 0 4px}
.cover .period{font-size:13px;color:#C7D2E2;font-weight:600}
.pbadge{display:inline-block;vertical-align:middle;margin-left:9px;font-size:12px;font-weight:800;color:#fff;background:#E85A3C;padding:2px 10px;border-radius:20px;letter-spacing:.02em}
.cover .rule{width:46px;height:3px;background:#E85A3C;border-radius:2px;margin:16px 0 0}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin:14px 0}
.kpi{border:1px solid #E6E9EE;border-radius:11px;padding:11px 13px;position:relative;overflow:hidden}
.kpi::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:#E85A3C}
.kpi.n2::before{background:#2B3A55}.kpi.n3::before{background:#C6452B}.kpi.n4::before{background:#6B7A8F}
.kpi .l{font-size:9.5px;color:#8A93A0;font-weight:600;margin-bottom:5px}
.kpi .v{font-size:20px;font-weight:800;letter-spacing:-.01em;font-family:'JetBrains Mono',monospace}
.kpi .v small{font-size:11px;font-weight:600;color:#3A4759}
.kpi .s{font-size:9px;color:#8A93A0;margin-top:4px}
.sec{margin:13px 0 0}
.sec-h{display:flex;align-items:baseline;gap:8px;margin-bottom:9px;border-bottom:2px solid #2B3A55;padding-bottom:5px}
.sec-h .no{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:800;color:#E85A3C}
.sec-h h2{font-size:14px;font-weight:800;letter-spacing:-.01em}
.sec-h .sub{font-size:10px;color:#8A93A0;margin-left:auto;font-weight:500}
.lead{font-size:11.5px;line-height:1.7;color:#39414E;background:#F7F8FA;border-left:3px solid #E85A3C;border-radius:8px;padding:10px 13px;margin-bottom:10px}
.lead b{color:#C6452B;font-weight:700}
.lead .up{color:#1F7A4D}.lead .dn{color:#C8413B}
.cmp{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:10px 0}
.cmp .box{border:1px solid #E6E9EE;border-radius:10px;padding:10px 13px}
.cmp .box .t{font-size:10px;color:#8A93A0;font-weight:600;margin-bottom:4px}
.cmp .box .row{display:flex;align-items:baseline;gap:8px}
.cmp .box .big{font-size:16px;font-weight:800;font-family:'JetBrains Mono',monospace}
.chip{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;padding:1px 7px;border-radius:6px}
.chip.up{background:#E6F4EC;color:#1F7A4D}.chip.dn{background:#E7EAF0;color:#2B3A55}.chip.fl{background:#F1F3F6;color:#8A93A0}
table{width:100%;border-collapse:collapse;font-size:10.5px;margin-top:6px}
th{font-size:9px;letter-spacing:.04em;color:#8A93A0;text-transform:uppercase;text-align:right;padding:6px 7px;border-bottom:1.5px solid #2B3A55}
th:first-child{text-align:left}
td{padding:6px 7px;text-align:right;font-family:'JetBrains Mono',monospace;border-bottom:1px solid #F1F3F6}
td:first-child{text-align:left;font-family:'Pretendard',sans-serif;font-weight:700}
td .dot{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px;vertical-align:middle}
.up{color:#1F7A4D;font-weight:700}.dn{color:#C8413B;font-weight:700}
.brow{display:grid;grid-template-columns:64px 1fr 150px;align-items:center;gap:9px;padding:2.5px 0}
.blab{font-size:10.5px;font-weight:700;color:#3A4759;text-align:right}
.btrk{height:15px;background:#F1F3F6;border-radius:4px;overflow:hidden}
.bfill{height:100%;background:#E85A3C;border-radius:4px}
.bval{font-size:10px;font-family:'JetBrains Mono',monospace;font-weight:700;color:#16202C}
.wx{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:4px}
.wxcard{border:1px solid #E6E9EE;border-radius:10px;padding:12px 14px}
.wxcard .t{font-size:10px;color:#8A93A0;font-weight:600;margin-bottom:7px}
.mwrap{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:4px}
.mcard{border:1px solid #E6E9EE;border-radius:11px;padding:10px 11px}
.mcard .mt{font-size:11.5px;font-weight:800;margin-bottom:2px}
.mcard .ms{font-size:9px;color:#8A93A0;margin-bottom:7px}
.hm{width:100%;border-collapse:separate;border-spacing:2px;font-size:9px;font-family:'JetBrains Mono',monospace}
.hm th{font-size:8px;color:#8A93A0;font-weight:700;padding:2px 1px;text-align:center;border:0}
.hm td{text-align:center;padding:3px 1px;border-radius:3px;border:0;font-weight:700}
.hm td.hm-t{background:#F4F6F9;color:#16202C;font-family:'Pretendard',sans-serif;text-align:left;padding-left:4px;font-weight:800}
.hm td.hm-e{background:#F8FAFC;color:#CBD2DA}
.legend{display:flex;flex-wrap:wrap;gap:6px 12px;justify-content:center;margin-top:11px}
.legend .lg{display:flex;align-items:center;gap:4px;font-size:9.5px;color:#3A4759;font-weight:600}
.legend .lg i{width:9px;height:9px;border-radius:2px}
.opc{line-height:1.6}
.opp{display:inline-block;padding:1px 4px;margin:1px 1px;border-radius:4px;font-size:8.8px;font-weight:700;background:#F4F6F9}
.opt{font-size:10px}
.opt th,.opt td{padding:4px 6px}
.opp.ou{color:#1E874B;background:#E9F6EE}
.opp.od{color:#D64528;background:#FCEAE4}
.opp.on{color:#6B7682;background:#F1F3F6}
.kf{margin:6px 0 0;padding:0;list-style:none;counter-reset:kf}
.kf li{counter-increment:kf;position:relative;padding:9px 11px 9px 36px;margin-bottom:7px;border:1px solid #E6E9EE;border-radius:9px;font-size:11px;line-height:1.62;color:#2A3340}
.kf li::before{content:counter(kf);position:absolute;left:9px;top:9px;width:19px;height:19px;border-radius:50%;background:#2B3A55;color:#fff;font-size:10px;font-weight:800;display:flex;align-items:center;justify-content:center;font-family:'JetBrains Mono',monospace}
.foot{margin-top:18px;padding-top:9px;border-top:1px solid #E6E9EE;font-size:9px;color:#8A93A0;line-height:1.6}
.foot b{color:#3A4759}
.note{font-size:9.5px;color:#8A93A0;margin-top:5px}
</style>
"""

def build_html(y,m,cur,prevM,prevY,tcur,tprev,rank_cur,rankrows,r,season,
               opp_rows,opp_beta,
               temp_cur,temp_prev,rain_gs,clear_gs):
    head=('<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">'
          '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css">'
          '<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500;700;800&display=swap" rel="stylesheet">'
          +CSS+'</head><body>')

    # ── 표지 + 요약 ──
    def chip(cur_v,prev_v):
        if prev_v in (None,0): return '<span class="chip fl">— 비교불가</span>'
        d=(cur_v-prev_v)/abs(prev_v)*100
        cls='up' if d>0.5 else 'dn' if d<-0.5 else 'fl'; arr='▲' if d>0.5 else '▼' if d<-0.5 else '—'
        return f'<span class="chip {cls}">{arr} {abs(d):.0f}%</span>'
    momTxt=''
    if prevM:
        d=(cur['avg']-prevM['avg'])/prevM['avg']*100
        momTxt=f'전월({m-1}월) 평균 {f(prevM["avg"])}명 대비 <b class="{"up" if d>=0 else "dn"}">{abs(d):.0f}% {"증가" if d>=0 else "감소"}</b>'
    pyTxt=''
    if prevY:
        d=(cur['avg']-prevY['avg'])/prevY['avg']*100
        pyTxt=f' · 전년 동월({y-1}년 {m}월) 대비 <b class="{"up" if d>=0 else "dn"}">{abs(d):.0f}% {"증가" if d>=0 else "감소"}</b>'
    prov=(date.today().year==y and date.today().month==m)
    pbadge='<span class="pbadge">잠정</span>' if prov else ''
    cover=(f'<div class="cover"><div class="eyebrow">KBO ATTENDANCE MONTHLY REPORT</div>'
           f'<h1>{y}년 {m}월 관중 분석 리포트{pbadge}</h1>'
           f'<div class="period">{y}.{m:02d} · 정규시즌 {cur["n"]}경기{" · 진행 중 잠정 집계" if prov else ""} · (주)서던포스트</div>'
           f'<div class="rule"></div></div>')
    kpis=('<div class="kpis">'
          f'<div class="kpi"><div class="l">경기당 평균 관중</div><div class="v">{f(cur["avg"])}<small>명</small></div>'
          f'<div class="s">{chip(cur["avg"],prevM["avg"] if prevM else None)} vs 전월</div></div>'
          f'<div class="kpi n2"><div class="l">총 관중</div><div class="v">{man(cur["tot"])}<small>만명</small></div>'
          f'<div class="s">{cur["n"]}경기 합산</div></div>'
          f'<div class="kpi n3"><div class="l">평균 좌석 점유율</div><div class="v">{cur["occ"]*100:.0f}<small>%</small></div>'
          f'<div class="s">{chip(cur["occ"],prevM["occ"] if prevM else None)} vs 전월</div></div>'
          f'<div class="kpi n4"><div class="l">완전 매진</div><div class="v">{cur["sell"]}<small>경기</small></div>'
          f'<div class="s">전체 {cur["n"]}경기 중 {cur["sell"]/cur["n"]*100:.0f}%</div></div>'
          '</div>')
    lead=(f'<div class="lead"><b>{y}년 {m}월</b> 정규시즌 {cur["n"]}경기에 총 <b>{man(cur["tot"])}만 명</b>이 입장해 '
          f'경기당 평균 <b>{f(cur["avg"])}명</b>(좌석 점유율 {cur["occ"]*100:.0f}%)을 기록했습니다. '
          f'{momTxt}{pyTxt}.</div>')

    # ── 전체 변화(전월/전년 비교 박스) ──
    def cmpbox(title,c,p,plabel):
        if not p:
            return f'<div class="box"><div class="t">{title}</div><div class="row"><span class="big">{f(c["avg"])}명</span><span class="chip fl">{plabel} 데이터 없음</span></div></div>'
        d=(c['avg']-p['avg'])/p['avg']*100
        cls='up' if d>=0 else 'dn'
        return (f'<div class="box"><div class="t">{title}</div><div class="row">'
                f'<span class="big">{f(c["avg"])}명</span>'
                f'<span class="chip {cls}">{"▲" if d>=0 else "▼"} {abs(d):.0f}%</span>'
                f'<span class="mono" style="font-size:10px;color:#8A93A0">{plabel} {f(p["avg"])}명</span></div></div>')
    sec1=('<div class="sec"><div class="sec-h"><span class="no">01</span><h2>전체 관중 현황 · 변화</h2>'
          '<span class="sub">경기당 평균 관중 기준</span></div>'
          '<div class="cmp">'+cmpbox(f'전월 대비 ({m-1}월)',cur,prevM,f'{m-1}월')
          +cmpbox(f'전년 동월 대비 ({y-1}년 {m}월)',cur,prevY,f'{y-1}.{m}')+'</div></div>')

    # ── 팀별 현황 (표) ──
    rows=[]
    order=sorted(tcur.keys(),key=lambda t:-tcur[t]['avg'])
    for t in order:
        c=tcur[t]; p=tprev.get(t)
        d=((c['avg']-p['avg'])/p['avg']*100) if p else None
        dtd=(f'<span class="{"up" if d>=0 else "dn"}">{d:+.0f}%</span>' if d is not None else '<span style="color:#C5CCD5">—</span>')
        rkv=rank_cur.get(t)
        rk=f'{rkv:.1f}위' if rkv is not None else '—'
        rows.append(f'<tr><td><span class="dot" style="background:{TCOL.get(t,"#888")}"></span>{t}({STAD.get(t,"")})</td>'
                    f'<td>{c["n"]}</td><td>{f(c["avg"])}</td><td>{c["occ"]*100:.0f}%</td><td>{rk}</td><td>{dtd}</td></tr>')
    sec2=('<div class="sec"><div class="sec-h"><span class="no">02</span><h2>구단별 현황 · 전월 대비</h2>'
          '<span class="sub">홈경기 기준 · 평균 관중 내림차순</span></div>'
          '<table><thead><tr><th>구단(구장)</th><th>경기</th><th>평균관중</th><th>점유율</th><th>평균순위</th><th>전월비</th></tr></thead>'
          f'<tbody>{"".join(rows)}</tbody></table></div>')

    # ── 월별 추이 (관중 라인 + 점유율 히트맵, 좌우) ──
    if season and season.get('months'):
        mh=('<div class="mwrap">'
            '<div class="mcard"><div class="mt">월별 홈구장 평균 관중</div><div class="ms">구단별 · 선형 (세로축 0 미시작 · 오른쪽 끝 구단명)</div>'
            f'{svg_month_lines(season["months"],season["order"],season["att"])}</div>'
            '<div class="mcard"><div class="mt">월별 좌석 점유율</div><div class="ms">진할수록 만석 · 오른쪽=시즌 평균(%)</div>'
            f'{html_month_heat(season["months"],season["order"],season["occ"])}</div>'
            '</div>')
    else:
        mh='<div class="lead">월별 추이를 그릴 데이터가 부족합니다.</div>'
    sec_month=('<div class="sec"><div class="sec-h"><span class="no">03</span><h2>월별 추이 (관중 · 점유율)</h2>'
               f'<span class="sub">{y}시즌 누적 · 홈경기 기준</span></div>'+mh+'</div>')

    # ── 상대팀 분석 (홈팀별: 전월 vs 이번달 상대 + 증감률) ──
    def opp_list(counter):
        if not counter: return '<span style="color:#C5CCD5">—</span>'
        items=sorted(counter.items(),key=lambda kv:-(opp_beta.get(kv[0],0)))
        out=[]
        for a,n in items:
            b=opp_beta.get(a,0)
            cls='ou' if b>300 else 'od' if b<-300 else 'on'
            out.append(f'<span class="opp {cls}">{a}{("×"+str(n)) if n>1 else ""}</span>')
        return ' '.join(out)
    if opp_rows:
        otr=[]
        for x in opp_rows:
            pct=x['pct']
            pchip=(f'<span class="{"up" if pct>=0 else "dn"}">{pct:+.0f}%</span>' if pct is not None
                   else '<span style="color:#C5CCD5">—</span>')
            otr.append(f'<tr><td><span class="dot" style="background:{TCOL.get(x["h"],"#888")}"></span>{x["h"]}({STAD.get(x["h"],"")})</td>'
                       f'<td class="opc">{opp_list(x["prev_opp"])}</td>'
                       f'<td class="opc">{opp_list(x["cur_opp"])}</td>'
                       f'<td>{pchip}</td></tr>')
        opp_body=('<table class="opt"><thead><tr><th>홈팀(구장)</th><th>전월 홈경기 상대팀</th><th>이번달 홈경기 상대팀</th><th>전월대비</th></tr></thead>'
                  f'<tbody>{"".join(otr)}</tbody></table>'
                  '<div class="note">※ 상대팀 이름 색 = 그 팀이 방문할 때 홈 평균 대비 관중 동원력 — '
                  '<span class="opp ou">초록</span> 평균 이상 / <span class="opp od">빨강</span> 평균 이하 / 회색 비슷 (시즌 누적 기준) · '
                  '×n = 그 달 n경기 · 전월대비 = 해당 홈팀 평균 관중 증감률.</div>')
    else:
        opp_body='<div class="lead">이번달 홈경기 데이터가 부족합니다.</div>'
    sec_opp=('<div class="sec"><div class="sec-h"><span class="no">04</span><h2>상대팀 분석 (홈경기 상대 구성)</h2>'
             '<span class="sub">전월 vs 이번달 맞이한 상대팀 · 홈 관중 증감</span></div>'
             '<div class="lead">홈 관중은 방문팀에 따라 달라집니다. 관중 동원력이 큰 팀(초록)과의 경기가 줄고 작은 팀(빨강)과의 경기가 늘면 관중이 감소하는 흐름을 읽을 수 있습니다.</div>'
             +opp_body+'</div>')

    # ── 순위 영향 (표) ──
    if rankrows:
        rtxt=''
        if r is not None:
            strength=('뚜렷한' if abs(r)>=0.5 else '약한' if abs(r)>=0.25 else '미미한')
            sign=('양의' if r>0 else '음의')
            tail=('순위가 오른 구단일수록 관중이 늘고, 떨어진 구단일수록 줄어드는 경향입니다.' if r>0.1 else
                  '순위가 올라도 관중이 줄거나, 떨어져도 관중이 느는 등 반대 방향 경향입니다.' if r<-0.1 else
                  '순위 변화가 관중에 미친 영향은 제한적이었습니다.')
            rtxt=(f'이번달 <b>순위 변화</b>와 <b>관중 변화</b>는 <b>{sign} 상관(r={r:.2f})</b>으로 '
                  f'{strength} 관계를 보입니다. {tail}')
        rr=sorted(rankrows,key=lambda x:-x['a1'])   # 이번달 평균관중 높은 순
        trows=[]
        for x in rr:
            ch=x['r0']-x['r1']   # +면 순위 상승(좋아짐)
            rkchip=(f'<span class="up">▲{ch:.1f}</span>' if ch>0.05 else
                    f'<span class="dn">▼{abs(ch):.1f}</span>' if ch<-0.05 else '<span style="color:#C5CCD5">—</span>')
            da=x['dAtt']; dchip=f'<span class="{"up" if da>=0 else "dn"}">{da:+.0f}%</span>'
            trows.append(f'<tr><td><span class="dot" style="background:{TCOL.get(x["t"],"#888")}"></span>{x["t"]}({STAD.get(x["t"],"")})</td>'
                         f'<td>{x["r0"]:.1f}위</td><td>{x["r1"]:.1f}위</td><td>{rkchip}</td>'
                         f'<td>{f(x["a0"])}</td><td>{f(x["a1"])}</td><td>{dchip}</td></tr>')
        rank_html=(f'<div class="lead">{rtxt}</div>'
                   '<table><thead><tr><th>구단(구장)</th><th>전월 순위</th><th>이번달 순위</th><th>순위변화</th>'
                   '<th>전월 평균관중</th><th>이번달 평균관중</th><th>관중 변화</th></tr></thead>'
                   f'<tbody>{"".join(trows)}</tbody></table>'
                   '<div class="note">※ 순위 = 해당 구단의 경기일 기준 순위를 그 달 전체로 평균(소수 1자리) · 순위변화 ▲상승 / ▼하락 · '
                   '<b>양의 상관 = 순위가 오를수록 관중 증가</b> · 정렬 = 이번달 평균관중 내림차순.</div>')
    else:
        rank_html='<div class="lead">전월 비교가 가능한 구단·순위 데이터가 부족해 순위-관중 분석을 생략했습니다.</div>'
    sec3=('<div class="sec"><div class="sec-h"><span class="no">05</span><h2>순위가 관중에 미친 영향</h2>'
          '<span class="sub">경기일 기준 평균 순위 · 전월 대비</span></div>'+rank_html+'</div>')

    # ── 날씨 영향 ──
    rn=len(rain_gs); cn=len(clear_gs)
    has_wx=(temp_cur is not None) or (rn+cn>0)
    if not has_wx:
        sec4=('<div class="sec"><div class="sec-h"><span class="no">06</span><h2>날씨 영향 (기온 · 강수)</h2>'
              '<span class="sub">경기 시간대(14~21시) 기준</span></div>'
              '<div class="lead">이 달의 날씨 데이터가 아직 수집되지 않았습니다. '
              '<b>fetch_weather.py</b> 를 실행해 기온·강수를 채운 뒤 리포트를 다시 생성하면 표시됩니다.</div></div>')
    else:
        ravg=sum(g['att'] for g in rain_gs)/rn if rn else 0
        cavg=sum(g['att'] for g in clear_gs)/cn if cn else 0
        raind=((ravg-cavg)/cavg*100) if cavg else 0
        tempd=(temp_cur-temp_prev) if (temp_cur is not None and temp_prev is not None) else None
        tline=''
        if temp_cur is not None:
            tline=f'이번달 경기 시간대 평균 기온은 <b>{temp_cur:.1f}℃</b>'
            if tempd is not None:
                tline+=f', 전월 대비 <b class="{"up" if tempd>=0 else "dn"}">{tempd:+.1f}℃</b>'
            tline+='입니다. '
        if rn:
            wline=(f'{rn+cn}경기 중 <b>우천(강수) {rn}경기</b>, 맑은 날 {cn}경기였고, '
                   f'우천 경기 평균 관중은 <b>{f(ravg)}명</b>으로 맑은 날({f(cavg)}명) 대비 '
                   f'<b class="{"up" if raind>=0 else "dn"}">{abs(raind):.0f}% {"높" if raind>=0 else "낮"}았</b>습니다.')
        else:
            wline=f'{cn}경기 모두 강수 없이 진행됐습니다(맑은 날 평균 {f(cavg)}명).'
        bmax=max(ravg,cavg,1)
        wbars=(bar_row('맑음',cavg,bmax,f'{f(cavg)}명 ({cn})')
               +(bar_row('우천',ravg,bmax,f'{f(ravg)}명 ({rn})') if rn else ''))
        temp_big=f'{temp_cur:.1f}℃' if temp_cur is not None else '—'
        if tempd is not None:
            temp_delta=(f'<span class="chip {"up" if tempd>=0 else "dn"}">{"▲" if tempd>=0 else "▼"} {abs(tempd):.1f}℃</span> '
                        f'vs 전월 {temp_prev:.1f}℃')
        elif temp_cur is None:
            temp_delta='<span class="note">기온 데이터 없음</span>'
        else:
            temp_delta='<span class="note">전월 비교 없음</span>'
        sec4=('<div class="sec"><div class="sec-h"><span class="no">06</span><h2>날씨 영향 (기온 · 강수)</h2>'
              '<span class="sub">경기 시간대(14~21시) 기준</span></div>'
              f'<div class="lead">{tline}{wline}</div>'
              '<div class="wx">'
              f'<div class="wxcard"><div class="t">기온 · 전월 대비</div>'
              f'<div class="mono" style="font-size:22px;font-weight:800">{temp_big}</div>'
              f'<div style="margin-top:3px">{temp_delta}</div></div>'
              f'<div class="wxcard"><div class="t">강수 영향 · 평균 관중</div>{wbars}</div>'
              '</div>'
              '<div class="note">※ 데이터에는 예보 강수확률이 없어 <b>실제 강수량/우천여부</b> 기준으로 분석했습니다.</div></div>')

    # ── 종합 분석 (주요 결과 5가지 내외) ──
    rk={x['t']:(x['r0'],x['r1']) for x in rankrows}     # 전월→이번달 평균순위
    oshift={}                                            # 상대 구성 변화(+면 인기팀↑)
    for x in opp_rows:
        def om(cnt):
            tot=sum(cnt.values())
            return sum(opp_beta.get(a,0)*n for a,n in cnt.items())/tot if tot else 0
        oshift[x['h']]=om(x['cur_opp'])-om(x['prev_opp'])
    def reasons(t,gain):
        rs=[]
        if t in rk:
            r0,r1=rk[t]
            if gain and r0-r1>=1.0: rs.append(f'순위 상승({r0:.1f}→{r1:.1f}위)')
            if (not gain) and r0-r1<=-1.0: rs.append(f'연패 등으로 순위 하락({r0:.1f}→{r1:.1f}위)')
        sh=oshift.get(t)
        if sh is not None:
            if gain and sh>=500: rs.append('관중 동원력 높은 팀과의 홈경기 증가')
            if (not gain) and sh<=-500: rs.append('관중 동원력 낮은 팀과의 홈경기 증가')
        return rs
    chg=[]
    for t in tcur:
        p=tprev.get(t)
        if not p or p['avg']==0: continue
        chg.append({'t':t,'d':(tcur[t]['avg']-p['avg'])/p['avg']*100})
    chg.sort(key=lambda x:x['d'])
    kf=[]; named=set()
    # 1) 전체 흐름
    dM=((cur['avg']-prevM['avg'])/prevM['avg']*100) if prevM else None
    dY=((cur['avg']-prevY['avg'])/prevY['avg']*100) if prevY else None
    if dM is not None:
        wd=('늘었습니다' if dM>1 else '줄었습니다' if dM<-1 else '전월과 비슷했습니다')
        seg=f'전월 대비 <b class="{"up" if dM>=0 else "dn"}">{dM:+.1f}%</b>'
        if dY is not None: seg+=f', 전년 동월 대비 <b class="{"up" if dY>=0 else "dn"}">{dY:+.1f}%</b>'
        kf.append(f'이번달 경기당 평균 관중은 <b>{f(cur["avg"])}명</b>으로 {seg}, 전반적으로 {wd}.')
    # 2) 증가 상위
    ups=[c for c in chg if c['d']>0][::-1][:2]
    if ups:
        parts=[]
        for c in ups:
            rs=reasons(c['t'],True); named.add(c['t'])
            parts.append(f'<b>{c["t"]} ({c["d"]:+.0f}%)</b>'+(('—'+' · '.join(rs)) if rs else ''))
        kf.append('관중이 늘어난 대표 구단: '+'; '.join(parts)+'.')
    # 3) 감소 상위
    dns=[c for c in chg if c['d']<0][:2]
    if dns:
        parts=[]
        for c in dns:
            rs=reasons(c['t'],False); named.add(c['t'])
            parts.append(f'<b>{c["t"]} ({c["d"]:+.0f}%)</b>'+(('—'+' · '.join(rs)) if rs else ''))
        kf.append('관중이 줄어든 대표 구단: '+'; '.join(parts)+'.')
    # 4) 상대팀 구성 효과 (위에서 안 다룬 구단 위주)
    if oshift:
        mx=max(oshift,key=lambda k:oshift[k]); mn=min(oshift,key=lambda k:oshift[k])
        bits=[]
        if oshift[mx]>=400 and mx not in named: bits.append(f'<b>{mx}</b>은 관중 동원력 높은 팀과의 홈경기가 늘어 유리했고')
        if oshift[mn]<=-400 and mn not in named: bits.append(f'<b>{mn}</b>은 관중 동원력 낮은 팀과의 경기가 많아 불리했습니다')
        if bits: kf.append('상대팀 구성 측면에서 '+', '.join(bits)+'.')
    # 5) 순위-관중 상관 (유의할 때만 방향 단정)
    if r is not None and rankrows:
        if r>0.1:
            downs=[x['t'] for x in sorted(rankrows,key=lambda x:x['r1']-x['r0'],reverse=True) if x['r1']-x['r0']>=1.0][:3]
            ups2=[x['t'] for x in sorted(rankrows,key=lambda x:x['r0']-x['r1'],reverse=True) if x['r0']-x['r1']>=1.0][:3]
            tailb=''
            if downs: tailb+=f' 순위가 떨어진 {"·".join(downs)} 등은 관중도 함께 줄고,'
            if ups2: tailb+=f' 오른 {"·".join(ups2)} 등은 늘었습니다.'
            kf.append(f'순위와 관중은 <b>양의 상관(r={r:.2f})</b>을 보였습니다.{tailb}')
        elif r<-0.1:
            kf.append(f'순위와 관중은 <b>음의 상관(r={r:.2f})</b>으로, 순위 변화와 관중이 반대로 움직인 이례적 흐름이었습니다.')
        else:
            kf.append(f'이번달 순위 변화와 관중 사이의 관계는 뚜렷하지 않았습니다(r={r:.2f}).')
    # 6) 날씨(강수 영향 뚜렷할 때만)
    if rain_gs and clear_gs:
        rn=len(rain_gs); cn=len(clear_gs)
        ravg=sum(g['att'] for g in rain_gs)/rn; cavg=sum(g['att'] for g in clear_gs)/cn
        rd=(ravg-cavg)/cavg*100 if cavg else 0
        if abs(rd)>=8 and rn>=3:
            kf.append(f'우천 {rn}경기 평균({f(ravg)}명)은 맑은 날 대비 <b class="{"up" if rd>=0 else "dn"}">{rd:+.0f}%</b>로, 날씨도 일부 영향을 줬습니다.')
    kf=kf[:6]
    summary_body=('<ol class="kf">'+''.join(f'<li>{x}</li>' for x in kf)+'</ol>') if kf else \
                 '<div class="lead">전월 비교 데이터가 부족해 종합 분석을 생략합니다.</div>'
    sec_sum=('<div class="sec"><div class="sec-h"><span class="no">07</span><h2>종합 분석 (주요 결과)</h2>'
             '<span class="sub">관중 증감의 원인 — 상대팀·순위·날씨 종합</span></div>'+summary_body+'</div>')

    foot=('<div class="foot"><b>출처</b> 관중·결과 = KBO 공식 기록 / visualbaseball 기반 산출 · '
          '날씨 = Open-Meteo 과거 기상(구장 좌표·경기 시간대) · 점유율 = 관중 ÷ 구장 수용인원 · '
          '순위 = 경기 직전 기준. <b>완전 매진</b> = 점유율 100% 이상. '
          '진행 중 시즌은 잠정값일 수 있습니다. 제작 (주)서던포스트.</div>')

    return (head
            +'<div class="page">'+cover+kpis+lead+sec1+sec2+'</div>'
            +'<div class="page">'+sec_month+sec_opp+'</div>'
            +'<div class="page">'+sec3+sec4+'</div>'
            +'<div class="page">'+sec_sum+foot+'</div>'
            +'</body></html>')

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
    for t in tcur:
        c=tcur[t]; p=tprev.get(t); rc=rank_cur.get(t); rp=rank_prev.get(t)
        if not p or rc is None or rp is None or p['avg']==0: continue
        rows.append({'t':t,'r0':rp,'r1':rc,'dRank':rc-rp,
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
                opp_rows=opp_rows,opp_beta=opp_beta,
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
    msg.set_content(f'{y}년 {m}월 KBO 관중 분석 월간 리포트를 첨부합니다.\n\n— 자동 발송 (주)서던포스트')
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
                    res['temp_cur'],res['temp_prev'],res['rain_gs'],res['clear_gs'])
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
