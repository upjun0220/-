# -*- coding: utf-8 -*-
# Radar-Guard WOOD demo booth - LEGO/IKEA style assembly booklet (Korean)
# Bolt-together kit: 4x4 posts, lap-jointed beam, all holes PRE-DRILLED by shop, WRENCH-ONLY assembly.
import math
KR="Noto Sans CJK KR, DejaVu Sans, sans-serif"
INK="#1c2530"; SUB="#555"; DARK="#3a4048"; METAL="#5b6570"; MET2="#7c8794"
WOOD="#e0b877"; WOODA="#f0c982"; WOOD2="#cfa25f"; WOOD3="#b98a45"; GRAIN="#a9793c"
GHOST="#e6e6e6"; GHOSTL="#dcdcdc"
BLUE="#1f3a63"; RED="#c0392b"; GREEN="#1f7a4d"; LINE="#2a2f36"; PAPER="#ffffff"
W,H=1400,990

def txt(x,y,t,sz=13,col=INK,anc="start",w="normal"):
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{sz}" fill="{col}" text-anchor="{anc}" font-weight="{w}" font-family="{KR}">{esc(t)}</text>'
def esc(t): return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
def line(x1,y1,x2,y2,col=LINE,w=1.4,dash="",cap="butt"):
    d=f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{col}" stroke-width="{w}"{d} stroke-linecap="{cap}"/>'
def rect(x,y,w,h,fill,stroke=LINE,sw=1.4,rx=0):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" rx="{rx}"/>'
def poly(pts,fill,stroke=LINE,sw=1.4):
    p=" ".join(f"{a:.1f},{b:.1f}" for a,b in pts); return f'<polygon points="{p}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
def circ(x,y,r,fill,stroke=LINE,sw=1.2):
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
def balloon(x,y,n,col=BLUE,r=13):
    return circ(x,y,r,"#fff",col,1.8)+f'<text x="{x:.1f}" y="{y+5:.1f}" font-size="15" fill="{col}" text-anchor="middle" font-weight="bold" font-family="{KR}">{n}</text>'
def tick(x,y,L=5,col=RED):
    return line(x-L,y-L,x+L,y+L,col,1.2)
def dim_v(y1,y2,x,t,col=RED):
    s=line(x,y1,x,y2,col,1.1)+tick(x,y1,4,col)+tick(x,y2,4,col)
    s+=f'<text x="{x-6:.1f}" y="{(y1+y2)/2:.1f}" font-size="12" fill="{col}" text-anchor="middle" font-weight="bold" font-family="{KR}" transform="rotate(-90 {x-6:.1f} {(y1+y2)/2:.1f})">{esc(t)}</text>'
    return s
def dim_h(x1,x2,y,t,col=RED):
    return line(x1,y,x2,y,col,1.1)+tick(x1,y,4,col)+tick(x2,y,4,col)+txt((x1+x2)/2,y-6,t,12,col,"middle","bold")

def woodbar(x,y,w,h,active=True,grain="v"):
    f=WOODA if active else WOOD; st=LINE if active else "#b9b9b9"
    if not active: f=GHOST; st="#c7c7c7"
    s=rect(x,y,w,h,f,st,1.5)
    if active:
        if grain=="v":
            for gx in (x+w*0.34,x+w*0.66): s+=line(gx,y+4,gx,y+h-4,GRAIN,0.6)
        else:
            for gy in (y+h*0.34,y+h*0.66): s+=line(x+4,gy,x+w-4,gy,GRAIN,0.6)
    return s
def brace(x1,y1,x2,y2,active=True,wpx=13):
    col=WOOD3 if active else GHOST; oc=LINE if active else "#c7c7c7"
    return line(x1,y1,x2,y2,oc,wpx+2,"","round")+line(x1,y1,x2,y2,col,wpx,"","round")
def langle(x,y,s=15,flip=(1,1),active=True):
    fx,fy=flip; t=4.2; c=METAL if active else "#c2c2c2"; oc="#20262c" if active else "#b5b5b5"
    a=rect(min(x,x+fx*s),y-(t if fy<0 else 0),s,t,c,oc,1.1)
    a+=rect(x-(t if fx<0 else 0),min(y,y+fy*s),t,s,c,oc,1.1)
    return a
def bolt(x,y,r=3.4,active=True):
    c="#20262c" if active else "#b5b5b5"
    return circ(x,y,r,c,"#000",1)+circ(x,y,r*0.42,"#8a8f96","#8a8f96")
def sandbag(x,y,w=34,h=17,active=True):
    c="#6b7078" if active else GHOST; oc="#3a3f46" if active else "#c7c7c7"
    return rect(x,y,w,h,c,oc,1.2,5)+ (line(x+4,y+h*0.5,x+w-4,y+h*0.5,"#4c5158",0.7) if active else "")

def page_frame(title, pageno, total, subtitle=""):
    E=[f'<rect width="{W}" height="{H}" fill="{PAPER}"/>']
    E.append(rect(20,20,W-40,H-40,"none",LINE,2))
    E.append(rect(20,20,W-40,52,BLUE,BLUE))
    E.append(txt(40,54,title,22,"#fff","start","bold"))
    if subtitle: E.append(txt(W-40,52,subtitle,13,"#cdd8e8","end","bold"))
    E.append(txt(W-40,H-30,f"Radar-Guard 목재 부스  ·  {pageno} / {total}",11,SUB,"end"))
    return E

# ---------- reusable FRONT elevation ----------
def draw_front(E, ox, yF, sc, active=None, dims=False, radar=True):
    if active is None: active=set("ABCDEF")
    pw=89*sc; cs=1200*sc; Hh=2400*sc; bt=38*sc
    xLo=ox; xLi=xLo+pw; xRi=xLi+cs; xRo=xRi+pw; xc=(xLo+xRo)/2
    yTop=yF-Hh
    yBb=yF-2300*sc; yBt=yBb-bt
    aA="A" in active; aB="B" in active; aC="C" in active; aD="D" in active
    # posts
    E.append(woodbar(xLo,yTop,pw,Hh,aA)); E.append(woodbar(xRo-pw,yTop,pw,Hh,aA))
    # top diagonal braces (in plane) - knee brace BELOW beam (triangle under top corner)
    bl=340*sc
    E.append(brace(xLi,yBb+bl, xLi+bl,yBb, aC))
    E.append(brace(xRi,yBb+bl, xRi-bl,yBb, aC))
    # top beam lapped over post fronts
    E.append(woodbar(xLo,yBt,xRo-xLo,bt,aB,grain="h"))
    # L brackets top corners
    E.append(langle(xLi,yBt+bt, 15,(1,-1),"F" in active)); E.append(langle(xRi,yBt+bt,15,(-1,-1),"F" in active))
    # beam-post bolts
    for bx in (xLo+pw*0.5, xRi+pw*0.5):
        E.append(bolt(bx,yBt+bt*0.5,3.2,aB))
    # base blocks + sandbags
    for xx in (xLo,xRo-pw):
        E.append(rect(xx-3,yF,pw+6,7,DARK if aD else GHOST,"#20262c" if aD else "#c7c7c7",1.2))
    E.append(sandbag(xLo-4,yF+3,pw+8,15,aD)); E.append(sandbag(xRo-pw-4,yF+3,pw+8,15,aD))
    # radar housing
    if radar:
        E.append(rect(xc-20,yBb,40,22,DARK,"#20262c",1.4))
        E.append(line(xc,yBb+22,xc,yBb+36,RED,1.6)); E.append(poly([(xc-4,yBb+34),(xc+4,yBb+34),(xc,yBb+42)],RED,RED))
    E.append(line(xLo,yF,xRo,yF,"#999",1.0,"3,3"))  # floor
    if dims:
        E.append(line(xLo-40,yTop,xLo-40,yF,"#bbb",0.6))
        E.append(dim_v(yTop,yF,xLo-40,"2400"))
        E.append(dim_v(yBb,yF,xRo+34,"2300 레이더면"))
        E.append(dim_h(xLi,xRi,yF+42,"1200 (기둥 사이)"))
        E.append(dim_h(xLo,xRo,yF+70,"1378 전체폭"))
    return dict(xLo=xLo,xLi=xLi,xRi=xRi,xRo=xRo,xc=xc,pw=pw,yTop=yTop,yBb=yBb,yBt=yBt,yF=yF)

def draw_side(E, ox, yF, sc, active=None, dims=False, crop=None):
    if active is None: active=set("ADE")
    pd=89*sc; Hh=2400*sc; foot=600*sc
    px=ox; yTop=yF-Hh
    yTopDraw = yTop if crop is None else yF-crop*sc
    aA="A" in active; aD="D" in active; aE="E" in active
    # foot (front-back)
    fL=px+pd/2-foot/2; fR=px+pd/2+foot/2
    E.append(woodbar(fL,yF-38*sc,foot,38*sc,aD,grain="h"))
    # post (optionally cropped at top with break marks)
    E.append(woodbar(px,yTopDraw,pd,yF-yTopDraw,aA))
    if crop is not None:
        for k in (0,1):
            yy=yTopDraw+6+k*7
            E.append(line(px-3,yy+4,px+pd/2,yy-3,"#fff",3)); E.append(line(px+pd/2,yy-3,px+pd+3,yy+4,"#fff",3))
            E.append(line(px-3,yy+4,px+pd/2,yy-3,LINE,1)); E.append(line(px+pd/2,yy-3,px+pd+3,yy+4,LINE,1))
    # kick braces both sides
    E.append(brace(px+pd/2,yF-38*sc, px+pd/2-170*sc,yF-38*sc-230*sc, aE))
    E.append(brace(px+pd/2,yF-38*sc, px+pd/2+170*sc,yF-38*sc-230*sc, aE))
    # brackets + bolts at base
    E.append(langle(px+pd/2-2,yF-38*sc,13,(1,-1),aE)); E.append(langle(px+pd/2+2,yF-38*sc,13,(-1,-1),aE))
    # rubber pads + sandbag
    E.append(rect(fL,yF,10,8,"#222" if aD else GHOST)); E.append(rect(fR-10,yF,10,8,"#222" if aD else GHOST))
    E.append(sandbag(fL-2,yF-38*sc-2,20,14,aD)); E.append(sandbag(fR-18,yF-38*sc-2,20,14,aD))
    E.append(line(fL-10,yF,fR+10,yF,"#999",1.0,"3,3"))
    if dims:
        E.append(dim_h(fL,fR,yF+40,"600 (앞뒤 발)"))
    return dict(px=px,pd=pd,yF=yF,yTop=yTop,fL=fL,fR=fR)

def svg(E): return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d">%s</svg>'%(W,H,''.join(E))

# ============================================================ PAGES
def p_cover(pn,tot):
    E=page_frame("목재 시연 부스 · 조립 설명서", pn, tot, "REV W2 · 2026-07-21")
    E.append(txt(40,100,"Radar-Guard 낙상 감지 데모용 2기둥 포탈 프레임 (목재 4×4 · 볼트 조립식 키트)",14,INK,"start","bold"))
    # big front elevation
    draw_front(E, 150, 720, 0.235, active=set("ABCDEF"), dims=True)
    # spec card
    x,y=760,130; w=600
    E.append(rect(x,y,w,250,"#f6f8fb",LINE,1.4,6))
    E.append(txt(x+18,y+30,"핵심 사양",15,BLUE,"start","bold"))
    rows=[("기둥","4×4 SPF 구조목 (89×89) × 2400 · 2개"),
          ("상단빔","2×4 SPF (38×89) × 1380 · 1개 (기둥 앞면에 겹침=랩조인트)"),
          ("레이더 면 높이","바닥에서 2300 mm (소프트웨어 CEILING_H)"),
          ("기둥 사이(낙상존)","1200 mm · 바닥 완전 개방 (가로대 없음)"),
          ("결합","M8 관통볼트 + 너트, 코너 L-앵글 · 용접 없음"),
          ("조립","구멍 전량 사전천공 → 현장은 렌치/소켓만 (전동드릴 불필요)")]
    for i,(k,v) in enumerate(rows):
        yy=y+58+i*30
        E.append(txt(x+18,yy,k,12.5,INK,"start","bold")); E.append(txt(x+150,yy,v,12,SUB))
    # why-wood / radar note
    y2=y+270
    E.append(rect(x,y2,w,150,"#eef7f1",GREEN,1.4,6))
    E.append(txt(x+18,y2+28,"왜 목재 4×4 인가 (흔들림 ↔ 클러터)",14,GREEN,"start","bold"))
    for i,t in enumerate([
        "· 알루미늄보다 저렴하고 60GHz 반사가 적음(빛·전파 모두).",
        "· 정지 물체는 클러터맵이 제거하지만, 흔들리면 제거가 깨져 오탐 발생.",
        "· 4×4는 약축 강성이 2×4의 약 12배 → 상단 흔들림 최소 → 클러터 처리 유리.",
        "· 프레임 아래는 완전히 비움(가로대·개구 브레이스 금지) = 낙상존 확보."]):
        E.append(txt(x+18,y2+52+i*23,t,12,INK))
    # danger strip
    E.append(rect(40,900,W-80,40,"#fff4f2",RED,1.2,5))
    E.append(txt(58,925,"⚠ 상단 작업(2.4m)은 반드시 2인 1조 + 사다리. 볼트는 손으로 가체결 후 마지막에 렌치로 순차 조임.",12.5,RED,"start","bold"))
    return svg(E)

def p_tools(pn,tot):
    E=page_frame("① 준비물 — 공구 & 볼트백", pn, tot)
    E.append(txt(40,100,"재단소가 자른 목재 5종 + 아래 볼트백/공구만 있으면 조립 완료. 현장 드릴링·나사 박기 없음.",13,SUB))
    # tools
    E.append(rect(40,120,640,455,"#f6f8fb",LINE,1.4,6))
    E.append(txt(58,150,"필요 공구",16,BLUE,"start","bold"))
    tools=[("13mm 소켓/스패너 ×2","M8 너트 조임 — 양쪽을 동시에 잡아야 해서 2개(또는 몽키 1 + 소켓 1)"),
           ("10mm 소켓/스패너","M6 너트(L-앵글 고정용)"),
           ("몽키스패너(조절렌치) 1~2","볼트 머리 고정용, 규격 몰라도 대응"),
           ("고무망치","목재 상하지 않게 맞물림 정렬"),
           ("수평계(또는 폰 앱)","기둥 수직·빔 수평 확인"),
           ("줄자 · 연필","레이더면 2300 확인, 위치 표시"),
           ("접이식 사다리","2.4m 상단 볼트 작업"),
           ("목장갑","안전")]
    for i,(k,v) in enumerate(tools):
        yy=180+i*44
        E.append(circ(70,yy-4,4,GREEN,GREEN)); E.append(txt(84,yy,k,13,INK,"start","bold")); E.append(txt(84,yy+17,v,11.5,SUB))
    E.append(rect(58,532,604,28,"#fdecea",RED,1.0,4))
    E.append(txt(70,551,"전동드릴 불필요 — 모든 구멍은 재단소에서 미리 뚫어 옵니다(③ 지시서).",12,RED,"start","bold"))
    # bolt bag
    x=710
    E.append(rect(x,120,650,560,"#fff",LINE,1.4,6))
    E.append(txt(x+18,150,"볼트백 (BOLT BAG)",16,BLUE,"start","bold"))
    hdr=["코드","품목","규격","수량","용도"]
    cols=[x+18,x+70,x+250,x+430,x+485]
    E.append(rect(x+10,165,630,26,"#e9eef4",LINE,1.0))
    for c,t in zip(cols,hdr): E.append(txt(c,183,t,12,BLUE,"start","bold"))
    bag=[("F","L-앵글 브래킷","90mm 스틸 앵글","8","코너·발 보강"),
         ("G1","육각볼트+와셔2+너트","M8 × 130","4","빔 ↔ 기둥(랩)"),
         ("G2","육각볼트+와셔2+너트","M8 × 110","4","상단 대각브레이스"),
         ("G3","육각볼트+와셔2+너트","M8 × 90","8","발·킥브레이스"),
         ("G4","볼트+너트","M6 × 50","24","L-앵글 고정"),
         ("H","고무패드","발바닥용","4","미끄럼·수평"),
         ("J","모래주머니","10~15 kg","2","발라스트(넘어짐 방지)")]
    for i,r in enumerate(bag):
        yy=210+i*30
        E.append(line(x+10,yy-19,x+640,yy-19,"#e2e2e2",0.7))
        for c,t in zip(cols,r): E.append(txt(c,yy,t,12,INK))
    E.append(txt(x+18,210+len(bag)*30+18,"※ 볼트 길이는 최종 스택 두께에 따라 ±10mm 조정 가능. 재단소에 구멍 지름(Ø)만 정확히 요청.",11,SUB))
    # little bolt drawing
    by=470
    E.append(txt(x+18,by,"M8 관통볼트 = [볼트]─[와셔]─(목재)─[와셔]─[너트]  → 렌치로 반대편 너트 조임",12,INK,"start","bold"))
    E.append(rect(x+18,by+18,120,14,METAL,"#20262c",1.2))
    E.append(rect(x+138,by+14,10,22,"#8a8f96","#20262c",1));
    E.append(rect(x+150,by+8,150,34,WOOD,LINE,1.2))
    E.append(rect(x+302,by+14,10,22,"#8a8f96","#20262c",1))
    E.append(poly([(x+312,by+12),(x+330,by+16),(x+330,by+32),(x+312,by+36)],METAL,"#20262c",1.2))
    E.append(txt(x+18,by+70,"볼트 머리",10,SUB)); E.append(txt(x+150,by+70,"목재(사전천공 Ø9)",10,SUB)); E.append(txt(x+306,by+70,"와셔+너트",10,SUB))
    return svg(E)

def p_parts(pn,tot):
    E=page_frame("② 부품 인벤토리 — 목재 5종", pn, tot)
    E.append(txt(40,100,"재단소에서 아래 5종을 받아 개수·길이를 먼저 확인하세요. (하우징 F는 3D 프린팅 별도)",13,SUB))
    items=[("A","기둥 (Post)","4×4 SPF · 89×89","2400 mm","2"),
           ("B","상단빔 (Beam)","2×4 SPF · 38×89","1380 mm","1"),
           ("C","상단 대각브레이스","2×4 SPF · 양끝 45°","≈500 mm","2"),
           ("D","받침발 (Foot)","2×4 SPF · 38×89","600 mm","2"),
           ("E","발 킥브레이스","2×4 SPF · 양끝 45°","≈300 mm","4")]
    y=140
    for code,name,spec,length,qty in items:
        E.append(rect(40,y,W-80,110,"#f9fafb",LINE,1.2,6))
        E.append(balloon(78,y+40,code,BLUE,18))
        E.append(txt(120,y+34,name,16,INK,"start","bold"))
        E.append(txt(120,y+58,f"{spec}",12.5,SUB)); E.append(txt(120,y+78,f"길이 {length}",12.5,SUB))
        E.append(txt(120,y+98,f"수량 {qty}개",13,GREEN,"start","bold"))
        # thumbnail drawing to the right
        gx=440; gy=y+55
        if code in ("A",):
            E.append(woodbar(gx,y+18,26,74,True)); E.append(bolt(gx+13,y+30)); E.append(bolt(gx+13,y+80))
            E.append(txt(gx+40,y+34,"상단 2 · 하단 2 = 관통홀",11,SUB))
        elif code=="B":
            E.append(woodbar(gx,gy-12,240,24,True,grain="h"))
            for bx in (gx+30,gx+70,gx+170,gx+210): E.append(bolt(bx,gy))
            E.append(txt(gx+30,gy+34,"양 끝단에 기둥 관통홀 2+2",11,SUB))
        elif code in ("C","E"):
            L=150 if code=="C" else 110
            E.append(poly([(gx,gy+14),(gx+L,gy-14),(gx+L,gy-2),(gx+12,gy+26)],WOODA,LINE,1.4))
            E.append(bolt(gx+10,gy+18)); E.append(bolt(gx+L-8,gy-8))
            E.append(txt(gx+L+16,gy,"양끝 45° 컷 · 각 끝 1홀",11,SUB))
        elif code=="D":
            E.append(woodbar(gx,gy-10,150,20,True,grain="h"));
            for bx in (gx+55,gx+95): E.append(bolt(bx,gy))
            E.append(txt(gx+164,gy,"중앙에 기둥 결합홀",11,SUB))
        # tick box
        E.append(rect(W-130,y+42,26,26,"#fff",INK,1.6,4)); E.append(txt(W-96,y+62,"확인",12,SUB))
        y+=124
    E.append(txt(40,y+18,"※ 부재 총 11개(A2 B1 C2 D2 E4). 받자마자 각 길이 실측 → ③ 지시서 값과 대조.",12,SUB))
    return svg(E)

def p_drill(pn,tot):
    E=page_frame("③ 재단·천공 지시서 (재단소 제출용)", pn, tot)
    E.append(rect(40,90,W-80,40,"#fdecea",RED,1.2,5))
    E.append(txt(58,116,"핵심 요청: 아래 길이대로 절단 + 표시된 구멍을 전부 미리 천공(Ø9=M8용, Ø7=M6용) 해 주세요. 우리는 렌치로 조립만 합니다.",12.5,RED,"start","bold"))
    # cut table
    E.append(txt(40,158,"[1] 절단 리스트",15,BLUE,"start","bold"))
    hdr=["코드","부재","규격(실치수)","길이","수량","비고"]
    cols=[50,100,210,430,520,600]
    E.append(rect(40,168,660,26,"#e9eef4",LINE,1.0))
    for c,t in zip(cols,hdr): E.append(txt(c,186,t,12,BLUE,"start","bold"))
    cut=[("A","기둥","4×4 (89×89)","2400","2","곧은 결·옹이 적은 것"),
         ("B","상단빔","2×4 (38×89)","1380","1","—"),
         ("C","상단 대각브레이스","2×4 (38×89)","500","2","양끝 45°"),
         ("D","받침발","2×4 (38×89)","600","2","—"),
         ("E","발 킥브레이스","2×4 (38×89)","300","4","양끝 45°")]
    for i,r in enumerate(cut):
        yy=212+i*26; E.append(line(40,yy-18,700,yy-18,"#e2e2e2",0.7))
        for c,t in zip(cols,r): E.append(txt(c,yy,t,11.5,INK))
    # hole schedule
    E.append(txt(40,375,"[2] 천공 위치 (부재별)",15,BLUE,"start","bold"))
    hole=[("A 기둥","상단: 앞면 기준 위끝에서 40·110mm 지점 Ø9 관통(빔 결합) 2개.  하단: 아래끝에서 40·110mm Ø9 관통(발) 2개.  +측면 대각브레이스용 Ø9 1개(위끝-300mm)."),
          ("B 상단빔","양 끝단에서 안쪽으로 45·115mm 지점 Ø9 관통 각 2개(총 4). 중앙부 하우징홀은 실측 후(현장 표시 가능)."),
          ("C 대각브레이스","45° 컷면에서 25mm 지점 각 끝 Ø9 1개(총 2)."),
          ("D 받침발","길이 중앙 좌우 40mm(=80mm 간격) Ø9 2개(기둥 결합)."),
          ("E 킥브레이스","45° 컷면에서 25mm 지점 각 끝 Ø9 1개(총 2).")]
    y=395
    for k,v in hole:
        E.append(txt(58,y,k,12.5,INK,"start","bold"));
        # wrap v
        import textwrap
        for j,ln in enumerate(textwrap.wrap(v,64)):
            E.append(txt(180,y+j*18,ln,11.5,SUB))
        y+= max(2,len(textwrap.wrap(v,64)))*18+10
    E.append(txt(58,y+6,"※ 구멍 위치가 애매하면 '각 결합부 Ø9 관통 2개, 간격 70mm, 중앙 정렬'을 기본값으로. 최종 위치는 조립도(우측) 참고.",11,SUB))
    # mini elevation reference on right
    E.append(rect(760,150,600,760,"#f9fafb",LINE,1.2,6))
    E.append(txt(778,178,"위치 참고도 (구멍 ● = Ø9)",13,BLUE,"start","bold"))
    r=draw_front(E, 900, 800, 0.235, active=set("ABCDEF"), dims=True)
    # emphasize holes
    xLo,xLi,xRi,xRo,pw,yBt,yF=r["xLo"],r["xLi"],r["xRi"],r["xRo"],r["pw"],r["yBt"],r["yF"]
    for bx in (xLo+pw*0.5,xRi+pw*0.5):
        E.append(circ(bx,yBt+9,4,RED,"#000",1));
    for xx in (xLo+pw*0.5,xRo-pw*0.5):
        E.append(circ(xx,yF-14,4,RED,"#000",1))
    return svg(E)

def step_header(E,n,title,note=""):
    E.append(circ(70,120,26,BLUE,BLUE)); E.append(txt(70,129,str(n),24,"#fff","middle","bold"))
    E.append(txt(110,116,title,19,INK,"start","bold"))
    if note: E.append(txt(110,140,note,12.5,SUB))

def p_step12(pn,tot):
    E=page_frame("④ 조립 STEP 1–2 · 발 유닛 만들기", pn, tot)
    step_header(E,1,"받침발 + 킥브레이스로 '발 유닛' 2개 조립 (좌·우 동일)","바닥에 눕혀서 작업하면 쉬움")
    # side view of base build
    draw_side(E, 260, 560, 0.5, active=set("ADE"), dims=True)
    E.append(txt(90,610,"조립 순서",13,BLUE,"start","bold"))
    for i,t in enumerate([
        "1) 기둥 A 하단을 받침발 D 중앙에 직각으로 맞춘다(수평계로 90°).",
        "2) 앞·뒤에 L-앵글(F)을 대고 M8×90(G3)+너트로 기둥-발을 조인다.",
        "3) 킥브레이스 E 2개를 기둥과 발 사이 45°로 끼워 양끝 M8×90(G3)로 조인다.",
        "4) 같은 방법으로 반대쪽 발 유닛도 만든다. → 발 유닛 ×2 완성."]):
        E.append(txt(90,636+i*22,t,12.5,INK))
    step_header2(E,2,"상단 대각브레이스 C 한쪽 끝만 가체결",760,120)
    draw_front(E, 830, 560, 0.20, active=set("AC"))
    E.append(txt(800,610,"미리 준비",13,BLUE,"start","bold"))
    for i,t in enumerate([
        "· 각 기둥 A 상단 안쪽에 대각브레이스 C의 아래끝을 M8×110(G2)로",
        "  '느슨하게' 가체결만 해둔다(윗끝은 STEP4에서 빔에 고정).",
        "· 이렇게 하면 기둥 세운 뒤 높은 곳에서 브레이스 잡을 필요가 없다."]):
        E.append(txt(800,636+i*22,t,12.5,INK))
    E.append(tipbox(E,"TIP","모든 볼트는 이 단계에서 '손힘으로만' 가체결. 전체 형태가 맞은 뒤 STEP6에서 렌치로 순차 최종조임."))
    return svg(E)

def step_header2(E,n,title,x,y):
    E.append(circ(x+30,y,24,BLUE,BLUE)); E.append(txt(x+30,y+8,str(n),22,"#fff","middle","bold"))
    E.append(txt(x+66,y+7,title,16,INK,"start","bold"))

def tipbox(E,tag,t):
    E.append(rect(40,905,W-80,44,"#eef7f1",GREEN,1.2,5))
    E.append(txt(60,932,f"{tag}: {t}",12.5,GREEN,"start","bold"))
    return ""

def p_step34(pn,tot):
    E=page_frame("④ 조립 STEP 3–4 · 기둥 세우고 빔 결합", pn, tot)
    step_header(E,3,"두 발 유닛을 세우고 상단빔 B를 앞면에 걸쳐 관통볼트","2인 1조 · 사다리 필수")
    draw_front(E, 250, 620, 0.235, active=set("ABDF"))
    E.append(txt(90,660,"조립 순서",13,BLUE,"start","bold"))
    for i,t in enumerate([
        "1) 두 발 유닛을 기둥 사이 안쪽 간격 1200mm 로 세운다.",
        "2) 상단빔 B를 두 기둥 '앞면'에 걸쳐(랩) 사전천공 구멍을 맞춘다.",
        "3) 각 코너 M8×130(G1) 2개를 관통시켜 반대편 너트를 렌치로 조인다.",
        "4) 코너에 L-앵글 F를 대고 M6×50(G4)으로 보강."]):
        E.append(txt(90,686+i*22,t,12,INK))
    step_header2(E,4,"대각브레이스 C 윗끝을 빔에 고정",760,150)
    draw_front(E, 860, 640, 0.20, active=set("ABC"))
    E.append(txt(800,690,"마무리",13,BLUE,"start","bold"))
    for i,t in enumerate([
        "· STEP2에서 가체결한 C의 윗끝을 빔 아래에 M8×110(G2)로 고정.",
        "· 아래끝 볼트도 정렬 확인 후 조인다. 좌·우 대칭으로.",
        "· 이 삼각형이 좌우 흔들림(라킹)을 잡아준다."]):
        E.append(txt(800,716+i*22,t,12,INK))
    tipbox(E,"주의","빔은 반드시 기둥 '앞면에 겹쳐서' 관통볼트. 기둥 사이에 끼워 끝면(엔드그레인)에 박으면 잘 빠짐 — 그렇게 하지 말 것.")
    return svg(E)

def p_step56(pn,tot):
    E=page_frame("④ 조립 STEP 5–6 · 레이더 · 발라스트 · 수평", pn, tot)
    step_header(E,5,"레이더 하우징 장착 + 케이블 장력 제거","안테나는 정확히 바닥을 향하도록(하향)")
    # zoom of beam center + housing
    bx,by=120,300
    E.append(rect(bx,by,360,28,WOOD2,LINE,1.5,0)); E.append(txt(bx+150,by-8,"상단빔 B (하면 89mm)",11,SUB))
    E.append(rect(bx+150,by+28,60,34,DARK,"#20262c",1.5));
    E.append(bolt(bx+165,by+14)); E.append(bolt(bx+195,by+14))
    E.append(line(bx+180,by+62,bx+180,by+86,RED,2)); E.append(poly([(bx+174,by+82),(bx+186,by+82),(bx+180,by+94)],RED,RED))
    E.append(txt(bx+215,by+48,"하우징: 빔 하면에 볼트 직결",12,INK,"start","bold"))
    E.append(txt(bx+215,by+66,"안테나 개구 하향 개방(나디르)",11,SUB))
    # cable
    E.append(f'<path d="M {bx+150} {by+40} q -30 20 -60 5 q -20 -10 -30 20" fill="none" stroke="#333" stroke-width="2"/>')
    E.append(txt(bx+10,by+120,"케이블: 하우징 내부 '서비스 루프' 한 바퀴 → 기둥 따라 내려 결속.",12,INK))
    E.append(txt(bx+10,by+140,"마이크로USB 커넥터에 장력 0 (예전 데이터 손상 원인 제거).",12,RED,"start","bold"))
    step_header2(E,6,"수평 · 모래주머니 · 최종 조임 · 흔들림 점검",60,470)
    draw_front(E, 250, 840, 0.15, active=set("ABCDEF"))
    E.append(txt(560,520,"체크 순서",13,BLUE,"start","bold"))
    for i,t in enumerate([
        "1) 수평계로 기둥 수직·빔 수평. 안 맞으면 발 밑 고무패드/심으로 보정.",
        "2) 줄자로 레이더 면 = 바닥에서 2300mm 확인(소프트웨어 CEILING_H와 일치).",
        "3) 각 발 위에 모래주머니(J) 올려 발라스트.",
        "4) 모든 볼트를 렌치로 순차 최종조임(대각 → 코너 → 발 순).",
        "5) 상단을 손으로 밀어 흔들림/유격 확인. 흔들리면 해당 볼트 재조임.",
        "   → 흔들림이 없어야 레이더 클러터 처리가 안정적."]):
        E.append(txt(560,546+i*24,t,12.5,INK))
    return svg(E)

def p_final(pn,tot):
    E=page_frame("⑤ 완성 · 검수 체크리스트", pn, tot)
    draw_front(E, 150, 780, 0.255, active=set("ABCDEF"), dims=True)
    x=770
    E.append(txt(x,120,"완성 검수 체크리스트",17,BLUE,"start","bold"))
    checks=[("구조","기둥 수직·빔 수평 (수평계 확인)"),
            ("구조","상단을 밀어도 흔들림/삐걱임 없음"),
            ("구조","모든 M8 볼트 렌치로 최종조임 완료"),
            ("구조","발에 모래주머니 + 고무패드"),
            ("치수","레이더 면 = 바닥 2300mm (±5mm)"),
            ("치수","기둥 사이 1200mm 개방(가로대 없음)"),
            ("레이더","안테나 개구 정확히 하향(나디르)"),
            ("레이더","케이블 서비스 루프 + 기둥 결속, 커넥터 장력 0"),
            ("레이더","빈방 상태로 클러터맵 재수집(정지 프레임 등록)"),
            ("데이터","높이 바뀌었으면 baseline·낙상 문턱 재검증")]
    y=150
    for cat,t in checks:
        E.append(rect(x,y-14,20,20,"#fff",INK,1.6,4))
        E.append(txt(x+30,y+2,f"[{cat}] {t}",12.5,INK)); y+=34
    E.append(rect(x,y+6,560,120,"#fff4f2",RED,1.2,5))
    E.append(txt(x+16,y+30,"남은 확정 1건",13,RED,"start","bold"))
    for i,t in enumerate([
        "· 레이더 하우징: IWR6843ISK-ODS EVM 실측(가로·세로·두께,",
        "  M3홀 4점, 마이크로USB 커넥터 방향) → gen_housing.py 반영 후 재출력.",
        "· 빔 중앙 하우징 볼트홀은 하우징 확정 후 현장 표시/천공."]):
        E.append(txt(x+16,y+52+i*22,t,11.5,INK))
    return svg(E)

from textwrap import wrap as _wrap
def wrap(s,n): return _wrap(s,n)
def diagram_box(E,x=50,y=150,w=690,h=735):
    E.append(rect(x,y,w,h,"#f9fafb","#e3e6ea",1.2,8))

def step_page(pn,tot,n,title,note,drawer,steps,warn=None,warncol=GREEN):
    E=page_frame(f"④ 조립 STEP {n} / 6", pn, tot)
    diagram_box(E); drawer(E)
    tx=790
    E.append(circ(tx+24,182,25,BLUE,BLUE)); E.append(txt(tx+24,190,str(n),23,"#fff","middle","bold"))
    E.append(txt(tx+62,178,title,17,INK,"start","bold"))
    if note: E.append(txt(tx+62,204,note,12.5,SUB))
    y=252
    for s in steps:
        lns=wrap(s,30)
        for j,ln in enumerate(lns):
            E.append(txt(tx if j==0 else tx+14,y,ln,13.5,INK)); y+=25
        y+=8
    if warn:
        bg="#eef7f1" if warncol==GREEN else "#fff4f2"
        lns=wrap(warn,38); bh=len(lns)*22+24
        E.append(rect(tx,y+8,560,bh,bg,warncol,1.3,6)); yy=y+34
        for ln in lns: E.append(txt(tx+16,yy,ln,12.5,warncol,"start","bold")); yy+=22
    return svg(E)

def d_base(E):
    draw_side(E, 330, 770, 0.60, active=set("ADE"), dims=True, crop=780)
    E.append(txt(356,300,"발 유닛 (측면도)",12.5,SUB,"middle"))
def d_front(active,dims=False):
    def f(E): draw_front(E, 235, 800, 0.25, active=active, dims=dims)
    return f
def d_housing(E):
    bx,by=170,360
    E.append(rect(bx,by,430,30,WOOD2,LINE,1.6)); E.append(txt(bx+215,by-14,"상단빔 B 하면 (89 mm 폭)",12,SUB,"middle"))
    E.append(rect(bx+180,by+30,70,42,DARK,"#20262c",1.6))
    E.append(bolt(bx+200,by+15)); E.append(bolt(bx+230,by+15))
    E.append(line(bx+215,by+72,bx+215,by+104,RED,2.6)); E.append(poly([(bx+207,by+100),(bx+223,by+100),(bx+215,by+116)],RED,RED))
    E.append(txt(bx+215,by+150,"안테나 개구 = 하향(나디르)",12.5,INK,"middle","bold"))
    E.append(f'<path d="M {bx+180} {by+45} q -40 26 -84 6 q -26 -13 -44 24" fill="none" stroke="#333" stroke-width="2.4"/>')
    E.append(txt(bx-40,by+210,"케이블: 하우징 내부 서비스 루프 → 기둥 따라 결속",11.5,INK))
    E.append(txt(bx-40,by+232,"→ 마이크로USB 커넥터 장력 0",11.5,RED,"start","bold"))

def p_s1(pn,tot): return step_page(pn,tot,1,"'발 유닛' 2개 만들기","받침발 D + 킥브레이스 E · 바닥에 눕혀 작업",d_base,[
    "1) 기둥 A 하단을 받침발 D 중앙에 직각(90°)으로 맞춘다.",
    "2) 앞·뒤에 L-앵글 F를 대고 M8×90(G3)+너트로 기둥–발을 조인다.",
    "3) 킥브레이스 E 2개를 45°로 끼워 양끝 M8×90(G3)로 조인다.",
    "4) 같은 방법으로 반대쪽도. → 발 유닛 ×2 완성."],
    "TIP: 이 단계 볼트는 손힘으로만 가체결. 최종조임은 STEP6.")
def p_s2(pn,tot): return step_page(pn,tot,2,"상단 대각브레이스 C 가체결","기둥을 세우기 전에 미리 달아둔다",d_front(set("AC")),[
    "· 기둥 A 상단 안쪽에 대각브레이스 C의 '아래끝만' M8×110(G2)로 느슨히 가체결.",
    "· 윗끝은 기둥을 세운 뒤 STEP4에서 빔에 고정한다.",
    "· 미리 달면 높은 곳에서 브레이스를 잡지 않아도 된다."],
    "TIP: 좌·우 기둥 모두 같은 위치에 대칭으로.")
def p_s3(pn,tot): return step_page(pn,tot,3,"기둥 세우고 상단빔 B 결합","2인 1조 · 사다리 필수",d_front(set("ABDF")),[
    "1) 두 발 유닛을 기둥 안쪽 간격 1200mm로 세운다.",
    "2) 상단빔 B를 두 기둥 '앞면'에 걸쳐(랩) 사전천공 구멍을 맞춘다.",
    "3) 각 코너 M8×130(G1) 2개를 관통 → 반대편 너트를 렌치로 조인다.",
    "4) 코너에 L-앵글 F를 대고 M6×50(G4)으로 보강."],
    "주의: 빔은 반드시 기둥 앞면에 '겹쳐서' 관통볼트. 기둥 사이에 끼워 끝면(엔드그레인)에 박기 금지 — 잘 빠진다.",RED)
def p_s4(pn,tot): return step_page(pn,tot,4,"대각브레이스 C 윗끝 고정","좌·우 대칭",d_front(set("ABC")),[
    "· STEP2에서 가체결한 C의 윗끝을 빔 아래에 M8×110(G2)로 고정.",
    "· 아래끝 볼트도 정렬 확인 후 조인다.",
    "· 이 삼각형이 좌우 흔들림(라킹)을 잡아준다."],
    "TIP: 아직 완전히 조이지 말고 STEP6에서 전체 순차 조임.")
def p_s5(pn,tot): return step_page(pn,tot,5,"레이더 하우징 장착 + 케이블 장력 제거","안테나가 정확히 바닥을 향하게",d_housing,[
    "1) 하우징을 빔 중앙 하면(89mm)에 볼트로 직결. 안테나 개구는 하향(나디르).",
    "2) 케이블은 하우징 내부 서비스 루프 1바퀴 후 기둥 따라 내려 결속.",
    "3) 마이크로USB 커넥터에 장력 0 (예전 데이터 손상 근본원인 제거).",
    "4) 줄자로 레이더 면 = 바닥 2300mm 확인."],
    "TIP: 하우징 STL·치수는 IWR6843 EVM 실측 후 확정(마지막 페이지 참고).")
def p_s6(pn,tot): return step_page(pn,tot,6,"수평·발라스트·최종조임·흔들림 점검","완성 직전 마무리",d_front(set("ABCDEF"),dims=True),[
    "1) 수평계로 기둥 수직·빔 수평. 안 맞으면 발 밑 고무패드/심 보정.",
    "2) 각 발 위에 모래주머니(J)로 발라스트.",
    "3) 모든 볼트를 렌치로 순차 최종조임(대각 → 코너 → 발).",
    "4) 상단을 손으로 밀어 흔들림/유격 확인 → 없어야 클러터 처리 안정."],
    "흔들림이 남으면 해당 코너·발 볼트를 다시 조이고, 그래도 크면 대각브레이스를 추가한다.")

pages=[p_cover,p_tools,p_parts,p_drill,p_s1,p_s2,p_s3,p_s4,p_s5,p_s6,p_final]
tot=len(pages)
import cairosvg, io
from pypdf import PdfWriter, PdfReader
from PIL import Image
w=PdfWriter()
for i,fn in enumerate(pages,1):
    s=fn(i,tot)
    open(f'_pg{i}.svg','w').write(s)
    cairosvg.svg2png(bytestring=s.encode(),write_to=f'_pg{i}.png',output_width=2000,background_color='white')
    w.add_page(PdfReader(io.BytesIO(cairosvg.svg2pdf(bytestring=s.encode()))).pages[0])
with open('조립설명서.pdf','wb') as f: w.write(f)
Image.open('_pg1.png').convert('RGB').save('booklet_cover.png')
print("booklet done pages=",tot)
