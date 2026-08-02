# -*- coding: utf-8 -*-
# Radar-Guard Demo Booth - Portal Frame fabrication drawing (English only)
FONT="DejaVu Sans, Liberation Sans, sans-serif"
INK="#1c2530"; STEEL="#c2c8d0"; STEEL2="#aab1bb"; DARK="#3a4048"; METAL="#4a5560"
BLUE="#1f3a63"; RED="#c0392b"; LINE="#2a2f36"

def T(s): return s
def txt(x,y,t,sz=12,col=INK,anc="start",w="normal",it="normal"):
    return f'<text x="{x}" y="{y}" font-size="{sz}" fill="{col}" text-anchor="{anc}" font-weight="{w}" font-style="{it}" font-family="{FONT}">{t}</text>'
def line(x1,y1,x2,y2,col=LINE,w=1.4,dash=""):
    d=f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{col}" stroke-width="{w}"{d}/>'
def rect(x,y,w,h,fill,stroke=LINE,sw=1.4,rx=0):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" rx="{rx}"/>'
def poly(pts,fill,stroke=LINE,sw=1.4):
    p=" ".join(f"{a:.1f},{b:.1f}" for a,b in pts)
    return f'<polygon points="{p}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
def circ(x,y,r,fill,stroke=LINE,sw=1.2):
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'

def tick(x,y,ang=45,L=6,col=LINE):
    import math
    dx=L*math.cos(math.radians(ang)); dy=L*math.sin(math.radians(ang))
    return line(x-dx,y-dy,x+dx,y+dy,col,1.2)
def dim_h(x1,x2,y,t,col=RED):
    s=line(x1,y,x2,y,col,1.1)
    s+=tick(x1,y,45,5,col)+tick(x2,y,45,5,col)
    s+=txt((x1+x2)/2,y-5,t,11,col,"middle","bold")
    return s
def dim_v(y1,y2,x,t,col=RED):
    s=line(x,y1,x,y2,col,1.1)
    s+=tick(x,y1,45,5,col)+tick(x,y2,45,5,col)
    s+=f'<text x="{x-5}" y="{(y1+y2)/2}" font-size="11" fill="{col}" text-anchor="middle" font-weight="bold" font-family="{FONT}" transform="rotate(-90 {x-5} {(y1+y2)/2})">{t}</text>'
    return s
def ext_line(x1,y1,x2,y2,col="#888"):
    return line(x1,y1,x2,y2,col,0.7)
def balloon(x,y,n):
    return circ(x,y,11,"#fff",BLUE,1.6)+txt(x,y+4,str(n),12,BLUE,"middle","bold")

def profile_v(x,ytop,ybot,wpx=11):  # vertical extrusion with slot lines
    s=rect(x,ytop,wpx,ybot-ytop,STEEL,LINE,1.4)
    s+=line(x+wpx/2,ytop,x+wpx/2,ybot,"#9aa1ab",0.7)
    return s
def profile_h(xl,xr,y,hpx=11):
    s=rect(xl,y,xr-xl,hpx,STEEL,LINE,1.4)
    s+=line(xl,y+hpx/2,xr,y+hpx/2,"#9aa1ab",0.7)
    return s
def gusset(cx,cy,size=26,flip=(1,1)):  # metal corner gusset (triangle plate + bolts)
    fx,fy=flip
    p=[(cx,cy),(cx+fx*size,cy),(cx,cy+fy*size)]
    s=poly(p,METAL,"#20262c",1.4)
    s+=circ(cx+fx*size*0.45,cy+fy*4,2.1,"#20262c","#20262c")
    s+=circ(cx+fx*5,cy+fy*size*0.45,2.1,"#20262c","#20262c")
    return s

# ============================ SHEET 1 ============================
W,H=1400,1000
def title_block(sheet_no):
    x,y,w,h=1010,822,350,150
    s=rect(x,y,w,h,"#fff",LINE,1.5)
    s+=line(x,y+26,x+w,y+26,LINE,1.0)+line(x,y+52,x+w,y+52,LINE,1.0)
    s+=line(x,y+92,x+w,y+92,LINE,1.0)+line(x,y+121,x+w,y+121,LINE,1.0)
    s+=line(x+180,y+92,x+180,y+h,LINE,1.0)+line(x+180,y+121,x+180,y+121,LINE,1.0)
    s+=txt(x+10,y+18,"RADAR-GUARD  |  DEMO BOOTH",12,BLUE,"start","bold")
    s+=txt(x+10,y+44,"Portal Frame - 2-Post Gantry",12,INK,"start","bold")
    s+=txt(x+10,y+70,"MATERIAL: 3030 Aluminium T-slot extrusion",10,INK)
    s+=txt(x+10,y+108,"UNITS: mm",10,INK)+txt(x+10,y+138,"SCALE: NTS",10,INK)
    s+=txt(x+190,y+108,"DATE: 2026-07-15",10,INK)+txt(x+190,y+138,"REV: B",10,INK)
    s+=txt(x+w-10,y+138,f"SHEET {sheet_no}/2",11,BLUE,"end","bold")
    return s

def sheet1():
    E=[f'<rect width="{W}" height="{H}" fill="#ffffff"/>']
    E.append(rect(24,24,W-48,H-48,"none",LINE,2))
    E.append(rect(24,24,W-48,40,BLUE,BLUE))
    E.append(txt(40,50,"SHEET 1  -  GENERAL ASSEMBLY and DIMENSIONS",17,"#fff","start","bold"))
    # ---------- FRONT ELEVATION ----------
    E.append(txt(120,96,"FRONT ELEVATION",14,BLUE,"start","bold"))
    s=0.315; x0=210; yT=120; wpx=11
    ow=1200*s; oh=2400*s
    xLo=x0; xRo=x0+ow                    # outer post edges
    xLi=xLo+wpx; xRi=xRo-wpx             # inner
    yB=yT+oh                             # floor line
    # posts
    E.append(profile_v(xLo,yT,yB,wpx)); E.append(profile_v(xRo-wpx,yT,yB,wpx))
    # top beam (between posts)
    E.append(profile_h(xLi,xRi,yT,wpx))
    # LARGE metal corner gussets (top x2) = primary stiffener, out of fall zone
    E.append(gusset(xLi,yT+wpx,46,(1,1))); E.append(gusset(xRi,yT+wpx,46,(-1,1)))
    # base gussets (post-to-foot) at floor = rigid base
    E.append(gusset(xLo+wpx,yB-2,30,(1,-1))); E.append(gusset(xRo-wpx,yB-2,30,(-1,-1)))
    # OPEN fall-test zone (NO member crosses here)
    ycz=yT+oh*0.5
    E.append(txt((xLo+xRo)/2,ycz,"OPEN",26,"#aab1bb","middle","bold"))
    E.append(txt((xLo+xRo)/2,ycz+24,"FALL-TEST ZONE - keep clear",13,"#aab1bb","middle","bold"))
    # mid-post equipment mounts (~1150 up)
    yMM=yB-1150*s
    E.append(rect(xLo-6,yMM-14,wpx+12,28,DARK,"#20262c",1.4))
    E.append(rect(xRo-wpx-6,yMM-14,wpx+12,28,DARK,"#20262c",1.4))
    # radar housing at top-center under beam
    xc=(xLo+xRo)/2
    E.append(rect(xc-22,yT+wpx,44,26,DARK,"#20262c",1.4))
    E.append(line(xc,yT+wpx+26,xc,yT+wpx+40,RED,1.6))
    E.append(poly([(xc-4,yT+wpx+38),(xc+4,yT+wpx+38),(xc,yT+wpx+46)],RED,RED))
    E.append(txt(xc+30,yT+wpx+18,"3D-printed radar housing",10,DARK,"start","bold"))
    E.append(txt(xc+30,yT+wpx+31,"(antenna faces down - nadir)",9,DARK))
    # leveling feet
    for xx in (xLo+wpx/2,xRo-wpx/2):
        E.append(rect(xx-9,yB,18,7,DARK)); E.append(circ(xx,yB+11,4,"#222"))
    # labels / balloons
    E.append(balloon(xLo-2,yT+oh*0.42,1)); E.append(txt(xLo-40,yT+oh*0.42+4,"POST",10,BLUE,"end","bold"))
    E.append(balloon(xc,yT-4,2)); E.append(txt(xc+16,yT-2,"TOP BEAM",10,BLUE,"start","bold"))
    E.append(txt(xLi+34,yT+wpx+52,"LARGE gusset (primary stiffener)",9,"#555","start"))
    E.append(balloon(xLi+16,yT+wpx+16,5)); E.append(txt(xLi+30,yT+wpx+30,"METAL GUSSET",10,BLUE,"start","bold"))
    E.append(txt(xRo+16,yMM+4,"4  Equipment mount",10,BLUE,"start","bold"))
    E.append(balloon(xRo-wpx-6,yMM-14,4))
    # dimensions
    E.append(ext_line(xLo,yT,150,yT)); E.append(ext_line(xLo,yB,150,yB))
    E.append(dim_v(yT,yB,158,"2400"))
    E.append(ext_line(xLo,yB,xLo,yB+50)); E.append(ext_line(xRo,yB,xRo,yB+50))
    E.append(dim_h(xLo,xRo,yB+46,"1200"))
    # bottom beam removed - fall zone kept fully open
    E.append(ext_line(xRo,yMM,xRo+120,yMM)); E.append(ext_line(xRo,yB,xRo+120,yB))
    E.append(dim_v(yMM,yB,xRo+150,"1150"))
    E.append(ext_line(xc+22,yT+wpx,xRo+240,yT+wpx)); E.append(ext_line(xRo,yB,xRo+240,yB))
    E.append(dim_v(yT+wpx,yB,xRo+235,"2300  RADAR FACE"))
    E.append(txt(xLo, yB+70,"Overall footprint width 1200 - span between posts 1140",10,"#555"))

    # ---------- SIDE ELEVATION ----------
    sx=760
    E.append(txt(sx,96,"SIDE ELEVATION",14,BLUE,"start","bold"))
    px=sx+120
    E.append(profile_v(px,yT,yB,wpx))
    # foot 400 front-back
    footL=px+wpx/2-300*s; footR=px+wpx/2+300*s
    E.append(profile_h(footL,footR,yB-wpx,wpx))
    # base gusset both sides
    E.append(gusset(px+wpx/2,yB-wpx,20,(1,-1))); E.append(gusset(px+wpx/2,yB-wpx,20,(-1,-1)))
    # rubber feet at BOTH ends
    for xx in (footL,footR-8):
        E.append(rect(xx,yB,10,10,"#222")); E.append(txt(xx+5,yB+24,"rubber",8,"#555","middle"))
    E.append(txt((footL+footR)/2,yB+40,"foot end-caps (rubber)",9,DARK,"middle"))
    # mid mount depth
    E.append(rect(px-14,yMM-14,wpx+28,28,DARK,"#20262c",1.4))
    # dims
    E.append(ext_line(footL,yB,footL,yB+50)); E.append(ext_line(footR,yB,footR,yB+50))
    E.append(dim_h(footL,footR,yB+46,"600"))
    E.append(txt(sx,yB+90,"Wide 600 mm front-to-back foot = front-back stability (no bottom beam).",10,"#555"))
    E.append(txt(sx,yB+106,"Rubber end-caps at both tips. Radar face 2300 mm via leveling feet.",10,"#555"))

    E.append(title_block(1))
    E.append(txt(40,H-30,"NOTE: Bottom OPEN for fall test (no cross-member in fall zone). Rigidity = LARGE top gussets + rigid base gussets + wide feet. 3030 extrusion, M6 T-nuts, no welding.",10,"#444"))
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d">%s</svg>'%(W,H,''.join(E))

open('frame_sheet1.svg','w').write(sheet1())
import cairosvg
cairosvg.svg2png(url='frame_sheet1.svg',write_to='frame_sheet1.png',output_width=1680)
print("sheet1 done")

# ============================ SHEET 2 ============================
import math
def iso(x,y,z,ox,oy,s=1.0):
    c=math.cos(math.radians(30)); sn=math.sin(math.radians(30))
    return (ox+(x-y)*c*s, oy+(x+y)*sn*s - z*s)
def isobox(x0,y0,z0,dx,dy,dz,ox,oy,s,ctop=STEEL,cfront=STEEL2,cside="#9298a1"):
    P=lambda X,Y,Z: iso(X,Y,Z,ox,oy,s)
    top=[P(x0,y0,z0+dz),P(x0+dx,y0,z0+dz),P(x0+dx,y0+dy,z0+dz),P(x0,y0+dy,z0+dz)]
    fr =[P(x0,y0,z0),P(x0+dx,y0,z0),P(x0+dx,y0,z0+dz),P(x0,y0,z0+dz)]
    sd =[P(x0+dx,y0,z0),P(x0+dx,y0+dy,z0),P(x0+dx,y0+dy,z0+dz),P(x0+dx,y0,z0+dz)]
    return poly(fr,cfront)+poly(sd,cside)+poly(top,ctop)

def sheet2():
    E=[f'<rect width="{W}" height="{H}" fill="#ffffff"/>']
    E.append(rect(24,24,W-48,H-48,"none",LINE,2))
    E.append(rect(24,24,W-48,40,BLUE,BLUE))
    E.append(txt(40,50,"SHEET 2  -  EXPLODED ASSEMBLY, CUT LIST and JOINT DETAIL",17,"#fff","start","bold"))

    # ---- EXPLODED ISO (left) ----
    E.append(txt(70,96,"EXPLODED ASSEMBLY",14,BLUE,"start","bold"))
    ox,oy,s=250,440,0.40
    P=30  # profile section 30mm -> use small
    # posts (2) vertical, exploded apart in Y
    E.append(isobox(0,0,0,30,30,760, ox,oy,s))          # left post (z up shortened scale)
    E.append(isobox(0,300,0,30,30,760, ox,oy,s))        # right post
    # top beam (between posts) lifted up (exploded above)
    E.append(isobox(0,30,800,30,270,30, ox,oy,s, ctop="#cfd4db"))
    # bottom beam
    # (bottom beam removed - fall zone open)
    # feet
    E.append(isobox(-120,0,-70,270,30,30, ox,oy,s, ctop="#b7bec9"))
    E.append(isobox(-120,300,-70,270,30,30, ox,oy,s, ctop="#b7bec9"))
    # gusset plates floating near top corners
    for gy in (30,300):
        gp=iso(15,gy,720,ox,oy,s)
        E.append(poly([(gp[0],gp[1]),(gp[0]+26,gp[1]+6),(gp[0]+8,gp[1]+28)],METAL,"#20262c",1.4))
    # balloons + leaders
    def leader(px,py,n,tx,ty,label):
        return line(px,py,tx,ty,"#888",0.8)+balloon(tx,ty,n)+txt(tx+16,ty+4,label,10,BLUE,"start","bold")
    E.append(leader(*iso(15,0,400,ox,oy,s),1,120,470,"POST  x2"))
    E.append(leader(*iso(15,150,815,ox,oy,s),2,360,150,"TOP BEAM  x1"))
    E.append(txt(120,560,"NO bottom beam - fall zone open",10,RED,"start","bold"))
    E.append(leader(*iso(0,15,-55,ox,oy,s),6,120,650,"PEDESTAL FOOT  x2"))
    E.append(leader(*iso(15,30,720,ox,oy,s),5,360,210,"METAL GUSSET  x4"))
    E.append(txt(70,720,"Assembly: bolt LARGE top gussets + base gussets (M6 T-nuts), then wide feet, then radar housing.",10,"#555"))

    # ---- CUT LIST (top right) ----
    tx0,ty0=760,145; cw=580
    E.append(txt(tx0,110,"CUT LIST  /  BILL OF MATERIALS",14,BLUE,"start","bold"))
    rows=[("ID","PART","PROFILE / SPEC","LEN (mm)","QTY","MATERIAL"),
          ("1","Vertical post","3030 extrusion","2400","2","Aluminium"),
          ("2","Top cross-beam","3030 extrusion","1140","1","Aluminium"),
          ("6","Pedestal foot (wide)","3030 extrusion","600","2","Aluminium"),
          ("5","TOP corner gusset","90 deg, 6 mm thk, large","-","2","STEEL"),
          ("7","Base gusset (post-foot)","90 deg, 6 mm thk","-","2","STEEL"),
          ("4","Equipment mount plate","150 x 80 x 5 mm","-","2","STEEL"),
          ("8","M6 T-nut + button bolt","M6 x 12","-","~32","Steel"),
          ("9","Leveling foot","M8 adjustable","-","2","Steel/rubber"),
          ("10","Foot end-cap (rubber)","for 3030 end","-","4","Rubber"),
          ("-","Radar housing","3D-print PETG","-","1","see housing"),]
    colx=[tx0,tx0+40,tx0+185,tx0+360,tx0+445,tx0+495]
    rh=26
    E.append(rect(tx0-6,ty0-18,cw,rh*len(rows)+10,"#fff",LINE,1.2))
    for i,r in enumerate(rows):
        yy=ty0+i*rh
        if i==0:
            E.append(rect(tx0-6,ty0-18,cw,rh,"#e9eef4",LINE,1.0))
        else:
            E.append(line(tx0-6,yy-18,tx0-6+cw,yy-18,"#dde3ea",0.8))
        for c,val in enumerate(r):
            bold="bold" if (i==0 or c==0) else "normal"
            col = BLUE if i==0 else (RED if (r[5]=="STEEL" and c==5) else INK)
            E.append(txt(colx[c],yy,val,10 if i else 10.5,col,"start",bold))
    E.append(txt(tx0,ty0+rh*len(rows)+8,"Steel gussets/brackets = rigid metal joints (per request) - stiffer than plastic inner connectors.",10,RED,"start","bold"))

    # ---- JOINT DETAIL (bottom right) ----
    jx,jy=780,620
    E.append(txt(jx,jy-14,"DETAIL A - METAL CORNER JOINT (typ. 4 places)",13,BLUE,"start","bold"))
    # post + beam
    E.append(rect(jx+70,jy,26,150,STEEL,LINE,1.6))           # post
    E.append(rect(jx+70,jy,180,26,STEEL,LINE,1.6))           # beam
    # steel gusset plate over corner
    E.append(poly([(jx+96,jy+26),(jx+186,jy+26),(jx+96,jy+120)],METAL,"#20262c",1.6))
    # bolts
    for (bx,by) in [(jx+120,jy+40),(jx+160,jy+40),(jx+110,jy+70),(jx+110,jy+100)]:
        E.append(circ(bx,by,4,"#20262c","#000",1))
        E.append(circ(bx,by,1.6,"#888"))
    E.append(txt(jx+200,jy+70,"Steel gusset plate,",10,INK)+txt(jx+200,jy+86,"6 mm large, bolted",10,INK)+txt(jx+200,jy+102,"M6 T-nuts into slots",10,INK))
    E.append(txt(jx+200,jy+126,"-> removes joint play",10,RED,"start","bold"))
    E.append(txt(jx+200,jy+142,"-> no welding",10,RED,"start","bold"))

    E.append(title_block(2))
    E.append(txt(40,H-30,"NOTE: Fabricate each part to length, deburr ends square (+/-0.5 mm). Assembly on site with hex key only. Radar face height set to 2300 mm via leveling feet.",10,"#444"))
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d">%s</svg>'%(W,H,''.join(E))

open('frame_sheet2.svg','w').write(sheet2())
cairosvg.svg2png(url='frame_sheet2.svg',write_to='frame_sheet2.png',output_width=1680)
print("sheet2 done")
