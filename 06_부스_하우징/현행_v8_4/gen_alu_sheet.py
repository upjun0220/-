# -*- coding: utf-8 -*-
# Radar-Guard demo frame - ALUMINIUM 3030 vendor fabrication sheet (Korean, width 1500)
# One clean page: only what the fabricator needs (dims, cut list, joint, assembly note).
import math
KR="Noto Sans CJK KR, DejaVu Sans, sans-serif"
INK="#1c2530"; SUB="#555"; STEEL="#c2c8d0"; STEEL2="#aab1bb"; SLOT="#9aa1ab"
METAL="#4a5560"; DARK="#3a4048"; BLUE="#1f3a63"; RED="#c0392b"; LINE="#2a2f36"
W,H=1400,990

def esc(t): return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
def txt(x,y,t,sz=13,col=INK,anc="start",w="normal"):
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{sz}" fill="{col}" text-anchor="{anc}" font-weight="{w}" font-family="{KR}">{esc(t)}</text>'
def line(x1,y1,x2,y2,col=LINE,w=1.4,dash=""):
    d=f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{col}" stroke-width="{w}"{d}/>'
def rect(x,y,w,h,fill,stroke=LINE,sw=1.4,rx=0):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" rx="{rx}"/>'
def poly(pts,fill,stroke=LINE,sw=1.4):
    p=" ".join(f"{a:.1f},{b:.1f}" for a,b in pts); return f'<polygon points="{p}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
def circ(x,y,r,fill,stroke=LINE,sw=1.2):
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
def tick(x,y,L=5,col=RED):
    return line(x-L,y-L,x+L,y+L,col,1.2)
def dim_v(y1,y2,x,t,col=RED):
    s=line(x,y1,x,y2,col,1.1)+tick(x,y1,4,col)+tick(x,y2,4,col)
    s+=f'<text x="{x-6:.1f}" y="{(y1+y2)/2:.1f}" font-size="12" fill="{col}" text-anchor="middle" font-weight="bold" font-family="{KR}" transform="rotate(-90 {x-6:.1f} {(y1+y2)/2:.1f})">{esc(t)}</text>'
    return s
def dim_h(x1,x2,y,t,col=RED):
    return line(x1,y,x2,y,col,1.1)+tick(x1,y,4,col)+tick(x2,y,4,col)+txt((x1+x2)/2,y-6,t,12,col,"middle","bold")
def balloon(x,y,n,col=BLUE,r=12):
    return circ(x,y,r,"#fff",col,1.7)+f'<text x="{x:.1f}" y="{y+5:.1f}" font-size="13" fill="{col}" text-anchor="middle" font-weight="bold" font-family="{KR}">{n}</text>'

def prof_v(x,ytop,ybot,w):
    return rect(x,ytop,w,ybot-ytop,STEEL,LINE,1.4)+line(x+w/2,ytop,x+w/2,ybot,SLOT,0.7)
def prof_h(xl,xr,y,h):
    return rect(xl,y,xr-xl,h,STEEL,LINE,1.4)+line(xl,y+h/2,xr,y+h/2,SLOT,0.7)
def gusset(cx,cy,size,flip):
    fx,fy=flip
    s=poly([(cx,cy),(cx+fx*size,cy),(cx,cy+fy*size)],METAL,"#20262c",1.4)
    s+=circ(cx+fx*size*0.42,cy+fy*4,2.0,"#20262c","#20262c")
    s+=circ(cx+fx*5,cy+fy*size*0.42,2.0,"#20262c","#20262c")
    return s

def sheet():
    E=[f'<rect width="{W}" height="{H}" fill="#ffffff"/>']
    E.append(rect(20,20,W-40,H-40,"none",LINE,2))
    E.append(rect(20,20,W-40,50,BLUE,BLUE))
    E.append(txt(40,53,"RADAR-GUARD 시연 프레임 · 알루미늄 3030 · 제작도 (업체 제출용)",20,"#fff","start","bold"))
    E.append(txt(W-40,52,"폭 1.5 m · 단위 mm",12,"#cdd8e8","end","bold"))

    # ---------------- FRONT ELEVATION ----------------
    E.append(txt(60,102,"정면도 (FRONT)",14,BLUE,"start","bold"))
    sc=0.205; yF=790; pw=30*sc
    x0=95
    ow=1500*sc                     # overall width 1500
    xLo=x0; xLi=xLo+pw; xRo=x0+ow; xRi=xRo-pw
    yTop=yF-2400*sc
    # posts
    E.append(prof_v(xLo,yTop,yF,pw)); E.append(prof_v(xRo-pw,yTop,yF,pw))
    # top beam between posts
    E.append(prof_h(xLi,xRi,yTop,pw))
    # large top corner gussets + base gussets
    E.append(gusset(xLi,yTop+pw,30,(1,1))); E.append(gusset(xRi,yTop+pw,30,(-1,1)))
    E.append(gusset(xLo+pw,yF-1,20,(1,-1))); E.append(gusset(xRo-pw,yF-1,20,(-1,-1)))
    # OPEN fall zone text
    yc=yTop+2400*sc*0.5
    E.append(txt((xLo+xRo)/2,yc,"OPEN",22,"#aab1bb","middle","bold"))
    E.append(txt((xLo+xRo)/2,yc+22,"낙상존 · 하단 개방 (가로대 금지)",12,"#9aa1ab","middle","bold"))
    # leveling feet
    for xx in (xLo+pw/2,xRo-pw/2):
        E.append(rect(xx-7,yF,14,6,DARK)); E.append(circ(xx,yF+11,4,"#222"))
    # dims
    E.append(line(xLo-38,yTop,xLo,yTop,"#bbb",0.6)); E.append(line(xLo-38,yF,xLo,yF,"#bbb",0.6))
    E.append(dim_v(yTop,yF,xLo-38,"2400"))
    E.append(line(xRi,yTop+pw,xRo+46,yTop+pw,"#bbb",0.6)); E.append(line(xRo,yF,xRo+46,yF,"#bbb",0.6))
    E.append(dim_v(yTop+pw,yF,xRo+44,"2300 레이더면"))
    E.append(line(xLi,yTop,xLi,yTop-20,"#bbb",0.6)); E.append(line(xRi,yTop,xRi,yTop-20,"#bbb",0.6))
    E.append(dim_h(xLi,xRi,yTop-10,"1440 (기둥 사이)"))
    E.append(line(xLo,yF,xLo,yF+52,"#bbb",0.6)); E.append(line(xRo,yF,xRo,yF+52,"#bbb",0.6))
    E.append(dim_h(xLo,xRo,yF+48,"1500 전체폭"))
    E.append(balloon(xLo-2,yc+70,1)); E.append(txt(xLo-38,yc+74,"기둥",10,BLUE,"end","bold"))
    E.append(balloon((xLo+xRo)/2,yTop-2,2)); E.append(txt((xLo+xRo)/2+16,yTop-2,"상단보",10,BLUE,"start","bold"))
    E.append(balloon(xLi+16,yTop+pw+14,4)); E.append(txt(xLi+30,yTop+pw+18,"스틸 거셋",10,BLUE,"start","bold"))

    # ---------------- SIDE ELEVATION ----------------
    E.append(txt(500,102,"측면도 (SIDE)",14,BLUE,"start","bold"))
    px=560
    E.append(prof_v(px,yTop,yF,pw))
    foot=600*sc; fL=px+pw/2-foot/2; fR=px+pw/2+foot/2
    E.append(prof_h(fL,fR,yF-pw,pw))
    E.append(gusset(px+pw/2,yF-pw,14,(1,-1))); E.append(gusset(px+pw/2,yF-pw,14,(-1,-1)))
    for xx in (fL,fR-8):
        E.append(rect(xx,yF,8,8,"#222"))
    E.append(line(fL,yF,fL,yF+42,"#bbb",0.6)); E.append(line(fR,yF,fR,yF+42,"#bbb",0.6))
    E.append(dim_h(fL,fR,yF+40,"600 (앞뒤 발)"))
    E.append(txt(500,yF+70,"넓은 600 발 + 레벨링 풋으로 앞뒤 안정 · 하단보 없음",10.5,SUB))
    E.append(txt(500,yF+88,"레이더면 2300은 레벨링 풋으로 정밀 조정",10.5,SUB))

    # ---------------- CUT LIST (right top) ----------------
    tx=720
    E.append(txt(tx,102,"절단 리스트 / BOM",14,BLUE,"start","bold"))
    hdr=["코드","부재","규격","길이","수량","재질"]
    cols=[tx,tx+40,tx+185,tx+400,tx+485,tx+540]
    E.append(rect(tx-8,112,648,26,"#e9eef4",LINE,1.0))
    for c,t in zip(cols,hdr): E.append(txt(c,130,t,12,BLUE,"start","bold"))
    rows=[("1","기둥(수직)","3030 프로파일","2400","2","알루미늄"),
          ("2","상단 가로보","3030 프로파일","1440","1","알루미늄"),
          ("3","받침발(넓은)","3030 프로파일","600","2","알루미늄"),
          ("4","상단 코너 거셋","90°, 6t, 대형","-","2","스틸"),
          ("5","베이스 거셋","90°, 6t","-","2","스틸"),
          ("6","M6 T너트+버튼볼트","M6 × 12","-","약 32","스틸"),
          ("7","레벨링 풋","M8 조절","-","2","스틸/고무"),
          ("8","엔드캡","3030용 고무","-","4","고무")]
    for i,r in enumerate(rows):
        yy=158+i*26; E.append(line(tx-8,yy-18,tx+640,yy-18,"#e2e2e2",0.7))
        for c,t in zip(cols,r):
            col = RED if (r[5]=="스틸" and c==cols[5]) else INK
            E.append(txt(c,yy,t,11.5,col))
    E.append(rect(tx-8,158+len(rows)*26-6,648,26,"#fff4f2",RED,1.0,4))
    E.append(txt(tx,158+len(rows)*26+11,"※ 레이더 하우징은 별도(자체 3D출력) — 업체 작업 아님.",11.5,RED,"start","bold"))

    # ---------------- JOINT DETAIL (right mid) ----------------
    jy=470
    E.append(txt(tx,jy,"조인트 상세 A — 스틸 코너 거셋 (상·하단 4곳)",13,BLUE,"start","bold"))
    jx=tx+20
    E.append(rect(jx+60,jy+20,24,140,STEEL,LINE,1.5))     # post
    E.append(rect(jx+60,jy+20,160,24,STEEL,LINE,1.5))     # beam
    E.append(poly([(jx+84,jy+44),(jx+164,jy+44),(jx+84,jy+124)],METAL,"#20262c",1.5))
    for (bx,by) in [(jx+110,jy+58),(jx+140,jy+58),(jx+98,jy+88),(jx+98,jy+112)]:
        E.append(circ(bx,by,3.6,"#20262c","#000",1)); E.append(circ(bx,by,1.5,"#8a8f96"))
    E.append(txt(jx+240,jy+66,"6t 스틸 거셋판을 코너에 대고",11.5,INK))
    E.append(txt(jx+240,jy+86,"M6 T너트로 볼트 체결",11.5,INK))
    E.append(txt(jx+240,jy+112,"→ 유격 제거 · 용접 없음",11.5,RED,"start","bold"))

    # ---------------- ASSEMBLY NOTE (right lower) ----------------
    ny=680
    E.append(rect(tx-8,ny,648,120,"#f6f8fb",LINE,1.2,6))
    E.append(txt(tx+8,ny+26,"제작·조립 요청 사항",13,BLUE,"start","bold"))
    for i,t in enumerate([
        "· 3030 프로파일을 위 길이대로 절단, 스틸 거셋(90°·6t) 제작/조달.",
        "· 전 조립 M6 T너트 볼트 — 용접 없음. 소량 1대.",
        "· 하단 완전 개방(낙상 실험존): 바닥·중앙 가로대 절대 금지.",
        "· 2400 높이엔 3030이 다소 슬림 → 4040 또는 거셋 확대 권장 시 상의."]):
        E.append(txt(tx+8,ny+52+i*20,t,11.5,INK))

    # ---------------- TITLE BLOCK ----------------
    tb_x,tb_y,tb_w,tb_h=1010,832,350,138
    E.append(rect(tb_x,tb_y,tb_w,tb_h,"#fff",LINE,1.5))
    E.append(line(tb_x,tb_y+30,tb_x+tb_w,tb_y+30,LINE,1.0)+line(tb_x,tb_y+62,tb_x+tb_w,tb_y+62,LINE,1.0))
    E.append(line(tb_x,tb_y+100,tb_x+tb_w,tb_y+100,LINE,1.0)+line(tb_x+175,tb_y+100,tb_x+175,tb_y+tb_h,LINE,1.0))
    E.append(txt(tb_x+12,tb_y+20,"RADAR-GUARD · 시연 프레임",12,BLUE,"start","bold"))
    E.append(txt(tb_x+12,tb_y+50,"재질: 3030 알루미늄 T-slot",11,INK))
    E.append(txt(tb_x+12,tb_y+84,"용접 없음 · 볼트 조립",11,INK))
    E.append(txt(tb_x+12,tb_y+122,"단위 mm · NTS",10.5,INK))
    E.append(txt(tb_x+185,tb_y+122,"2026-07-22 · REV C(1.5m)",10.5,INK))
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d">%s</svg>'%(W,H,''.join(E))

s=sheet()
open('frame_alu_vendor.svg','w').write(s)
import cairosvg, io
from pypdf import PdfWriter, PdfReader
cairosvg.svg2png(bytestring=s.encode(),write_to='frame_alu_vendor.png',output_width=2000,background_color='white')
w=PdfWriter(); w.add_page(PdfReader(io.BytesIO(cairosvg.svg2pdf(bytestring=s.encode()))).pages[0])
open('frame_alu_vendor.pdf','wb').write(b'')
with open('frame_alu_vendor.pdf','wb') as f: w.write(f)
print("alu sheet done")
