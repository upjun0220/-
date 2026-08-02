# -*- coding: utf-8 -*-
# Radar-Guard Demo Booth - WOOD Portal Frame fabrication drawing (English only, glyph-safe)
# 2x4 SPF lumber version (replaces 3030 aluminium). Joints = diagonal braces + metal angle brackets + lag/wood screws.
import math
FONT="DejaVu Sans, Liberation Sans, sans-serif"
INK="#1c2530"; DARK="#3a4048"; METAL="#4a5560"
WOOD="#e0b877"; WOOD2="#cfa25f"; WOOD3="#b98a45"; GRAIN="#a9793c"
BLUE="#1f3a63"; RED="#c0392b"; LINE="#2a2f36"

def txt(x,y,t,sz=12,col=INK,anc="start",w="normal",it="normal"):
    return f'<text x="{x}" y="{y}" font-size="{sz}" fill="{col}" text-anchor="{anc}" font-weight="{w}" font-style="{it}" font-family="{FONT}">{t}</text>'
def line(x1,y1,x2,y2,col=LINE,w=1.4,dash="",cap="butt"):
    d=f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{col}" stroke-width="{w}"{d} stroke-linecap="{cap}"/>'
def rect(x,y,w,h,fill,stroke=LINE,sw=1.4,rx=0):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" rx="{rx}"/>'
def poly(pts,fill,stroke=LINE,sw=1.4):
    p=" ".join(f"{a:.1f},{b:.1f}" for a,b in pts)
    return f'<polygon points="{p}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
def circ(x,y,r,fill,stroke=LINE,sw=1.2):
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
def tick(x,y,ang=45,L=6,col=LINE):
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

# --- WOOD member renderers (lumber look: fill + grain lines) ---
def wood_v(x,ytop,ybot,wpx):
    s=rect(x,ytop,wpx,ybot-ytop,WOOD,LINE,1.4)
    for gx in (x+wpx*0.32,x+wpx*0.62):
        s+=line(gx,ytop+4,gx,ybot-4,GRAIN,0.6)
    return s
def wood_h(xl,xr,y,hpx):
    s=rect(xl,y,xr-xl,hpx,WOOD2,LINE,1.4)
    for gy in (y+hpx*0.35,y+hpx*0.68):
        s+=line(xl+3,gy,xr-3,gy,GRAIN,0.6)
    return s
def wood_brace(x1,y1,x2,y2,wpx=12):
    # a 2x4 diagonal member drawn as a thick capped bar with an outline
    s=line(x1,y1,x2,y2,LINE,wpx+2,"","round")
    s+=line(x1,y1,x2,y2,WOOD3,wpx,"","round")
    return s
def lbracket(cx,cy,size=16,flip=(1,1)):
    # metal L angle bracket at inside corner (two legs) with screw dots
    fx,fy=flip; t=4
    s =rect(min(cx,cx+fx*size),cy-(t if fy<0 else 0),size,t,METAL,"#20262c",1.2)
    s+=rect(cx-(t if fx<0 else 0),min(cy,cy+fy*size),t,size,METAL,"#20262c",1.2)
    s+=circ(cx+fx*size*0.6,cy+fy*(t/2),1.6,"#20262c","#20262c")
    s+=circ(cx+fx*(t/2),cy+fy*size*0.6,1.6,"#20262c","#20262c")
    return s

W,H=1400,1000
def title_block(sheet_no):
    x,y,w,h=1010,822,350,150
    s=rect(x,y,w,h,"#fff",LINE,1.5)
    s+=line(x,y+26,x+w,y+26,LINE,1.0)+line(x,y+52,x+w,y+52,LINE,1.0)
    s+=line(x,y+92,x+w,y+92,LINE,1.0)+line(x,y+121,x+w,y+121,LINE,1.0)
    s+=line(x+180,y+92,x+180,y+h,LINE,1.0)
    s+=txt(x+10,y+18,"RADAR-GUARD  |  DEMO BOOTH",12,BLUE,"start","bold")
    s+=txt(x+10,y+44,"Portal Frame - 2-Post Gantry (WOOD)",12,INK,"start","bold")
    s+=txt(x+10,y+70,"MATERIAL: 2x4 SPF lumber (38 x 89 mm)",10,INK)
    s+=txt(x+10,y+108,"UNITS: mm",10,INK)+txt(x+10,y+138,"SCALE: NTS",10,INK)
    s+=txt(x+190,y+108,"DATE: 2026-07-21",10,INK)+txt(x+190,y+138,"REV: W1",10,INK)
    s+=txt(x+w-10,y+138,f"SHEET {sheet_no}/2",11,BLUE,"end","bold")
    return s

# ============================ SHEET 1 ============================
def sheet1():
    E=[f'<rect width="{W}" height="{H}" fill="#ffffff"/>']
    E.append(rect(24,24,W-48,H-48,"none",LINE,2))
    E.append(rect(24,24,W-48,40,BLUE,BLUE))
    E.append(txt(40,50,"SHEET 1  -  GENERAL ASSEMBLY and DIMENSIONS  (WOOD 2x4)",16,"#fff","start","bold"))
    # ---------- FRONT ELEVATION ----------
    E.append(txt(120,96,"FRONT ELEVATION",14,BLUE,"start","bold"))
    s=0.30; x0=210; yT=150; wpx=12
    ow=1200*s; oh=2400*s
    xLo=x0; xRo=x0+ow
    xLi=xLo+wpx; xRi=xRo-wpx
    yB=yT+oh
    # posts
    E.append(wood_v(xLo,yT,yB,wpx)); E.append(wood_v(xRo-wpx,yT,yB,wpx))
    # top beam (butt between posts)
    E.append(wood_h(xLi,xRi,yT,wpx))
    # diagonal braces at top corners (45 deg) = wood corner stiffener
    braceLen=350*s
    E.append(wood_brace(xLi,yT+wpx+braceLen, xLi+braceLen,yT+wpx))
    E.append(wood_brace(xRi,yT+wpx+braceLen, xRi-braceLen,yT+wpx))
    # metal L brackets at inner corners (both top corners)
    E.append(lbracket(xLi,yT+wpx,14,(1,1))); E.append(lbracket(xRi,yT+wpx,14,(-1,1)))
    # OPEN fall-test zone
    ycz=yT+oh*0.52
    E.append(txt((xLo+xRo)/2,ycz,"OPEN",26,"#c9a15f","middle","bold"))
    E.append(txt((xLo+xRo)/2,ycz+24,"FALL-TEST ZONE - keep clear",13,"#c9a15f","middle","bold"))
    # mid-post equipment mount (~1150 up)
    yMM=yB-1150*s
    E.append(rect(xLo-6,yMM-14,wpx+12,28,DARK,"#20262c",1.4))
    E.append(rect(xRo-wpx-6,yMM-14,wpx+12,28,DARK,"#20262c",1.4))
    # radar housing at top-center under beam (label sent to right margin, away from braces)
    xc=(xLo+xRo)/2
    E.append(rect(xc-20,yT+wpx,40,24,DARK,"#20262c",1.4))
    E.append(line(xc,yT+wpx+24,xc,yT+wpx+40,RED,1.6))
    E.append(poly([(xc-4,yT+wpx+38),(xc+4,yT+wpx+38),(xc,yT+wpx+46)],RED,RED))
    E.append(line(xc+20,yT+wpx+6,xRo+30,yT+50,"#888",0.7))
    E.append(txt(xRo+34,yT+44,"3D-print radar housing",10,DARK,"start","bold"))
    E.append(txt(xRo+34,yT+58,"(screwed to beam,",9,DARK))
    E.append(txt(xRo+34,yT+70,"antenna faces down)",9,DARK))
    # feet + sandbag ballast
    for xx in (xLo+wpx/2,xRo-wpx/2):
        E.append(rect(xx-9,yB,18,6,DARK)); E.append(circ(xx,yB+11,4,"#222"))
    # sandbag icons on feet
    for xx in (xLo,xRo-30):
        E.append(rect(xx,yB+2,30,16,"#6b7078","#3a3f46",1.2,4))
    E.append(txt(xLo+15,yB+38,"sandbag ballast",8,"#555","middle"))
    E.append(txt(xRo-15,yB+38,"sandbag ballast",8,"#555","middle"))
    # labels / balloons
    E.append(balloon(xLo-2,yT+oh*0.40,1)); E.append(txt(xLo-40,yT+oh*0.40+4,"POST",10,BLUE,"end","bold"))
    E.append(balloon(xc,yT-6,2)); E.append(txt(xc-16,yT-2,"TOP BEAM",10,BLUE,"end","bold"))
    # diagonal brace callout (left brace, out in the open zone)
    E.append(line(xLi+braceLen*0.5,yT+wpx+braceLen*0.5, xLi+90,yT+oh*0.30,"#888",0.7))
    E.append(balloon(xLi+90,yT+oh*0.30,3)); E.append(txt(xLi+104,yT+oh*0.30+4,"DIAGONAL BRACE",10,BLUE,"start","bold"))
    # angle bracket callout (outer top-left corner, leader up-left)
    E.append(line(xLi+4,yT+wpx+4, xLo-6,yT+34,"#888",0.7))
    E.append(balloon(xLo-6,yT+34,5)); E.append(txt(xLo-20,yT+38,"ANGLE BRACKET",10,BLUE,"end","bold"))
    E.append(balloon(xRo-wpx-6,yMM-14,4)); E.append(txt(xRo+10,yMM+4,"Equipment mount",10,BLUE,"start","bold"))
    # dimensions
    E.append(ext_line(xLo,yT,150,yT)); E.append(ext_line(xLo,yB,150,yB))
    E.append(dim_v(yT,yB,158,"2400"))
    E.append(ext_line(xLo,yB,xLo,yB+56)); E.append(ext_line(xRo,yB,xRo,yB+56))
    E.append(dim_h(xLo,xRo,yB+52,"1200"))
    E.append(ext_line(xRo,yMM,xRo+120,yMM)); E.append(ext_line(xRo,yB,xRo+120,yB))
    E.append(dim_v(yMM,yB,xRo+150,"1150"))
    E.append(ext_line(xc+22,yT+wpx,xRo+240,yT+wpx)); E.append(ext_line(xRo,yB,xRo+240,yB))
    E.append(dim_v(yT+wpx,yB,xRo+235,"2300  RADAR FACE"))
    E.append(txt(xLo, yB+76,"Overall width 1200 - clear span between posts 1140",10,"#555"))

    # ---------- SIDE ELEVATION ----------
    sx=760
    E.append(txt(sx,96,"SIDE ELEVATION",14,BLUE,"start","bold"))
    px=sx+150; dpx=89*s  # post shows 89mm depth from the side
    E.append(wood_v(px,yT,yB,dpx))
    # wide foot 600 front-back
    footL=px+dpx/2-300*s; footR=px+dpx/2+300*s
    E.append(wood_h(footL,footR,yB-wpx,wpx))
    # diagonal brace post->foot both sides (kick brace) for front-back stability
    E.append(wood_brace(px+dpx/2, yB-wpx, px+dpx/2-160*s, yB-wpx-220*s))
    E.append(wood_brace(px+dpx/2, yB-wpx, px+dpx/2+160*s, yB-wpx-220*s))
    # rubber pads + sandbag at both ends
    for xx in (footL,footR-8):
        E.append(rect(xx,yB,10,9,"#222"))
    E.append(rect(footL-2,yB-wpx-2,20,14,"#6b7078","#3a3f46",1.2,4))
    E.append(rect(footR-18,yB-wpx-2,20,14,"#6b7078","#3a3f46",1.2,4))
    E.append(txt((footL+footR)/2,yB+26,"rubber pads + sandbag ballast",9,DARK,"middle"))
    # mid mount depth
    E.append(rect(px-14,yMM-14,dpx+28,28,DARK,"#20262c",1.4))
    # dims
    E.append(ext_line(footL,yB,footL,yB+50)); E.append(ext_line(footR,yB,footR,yB+50))
    E.append(dim_h(footL,footR,yB+46,"600"))
    E.append(txt(sx,yB+64,"89 mm-deep post + wide 600 foot",10,"#555"))
    E.append(txt(sx,yB+78,"+ kick braces = anti-tip (no bottom beam).",10,"#555"))

    E.append(title_block(1))
    E.append(txt(40,H-30,"NOTE: Bottom OPEN for fall test (no cross-member). Rigidity = diagonal braces + metal angle brackets + wide ballasted feet. 2x4 SPF, lag/wood screws, no welding.",9.5,"#444"))
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d">%s</svg>'%(W,H,''.join(E))

# ============================ SHEET 2 ============================
def iso(x,y,z,ox,oy,s=1.0):
    c=math.cos(math.radians(30)); sn=math.sin(math.radians(30))
    return (ox+(x-y)*c*s, oy+(x+y)*sn*s - z*s)
def isobox(x0,y0,z0,dx,dy,dz,ox,oy,s,ctop=WOOD,cfront=WOOD2,cside=WOOD3):
    P=lambda X,Y,Z: iso(X,Y,Z,ox,oy,s)
    top=[P(x0,y0,z0+dz),P(x0+dx,y0,z0+dz),P(x0+dx,y0+dy,z0+dz),P(x0,y0+dy,z0+dz)]
    fr =[P(x0,y0,z0),P(x0+dx,y0,z0),P(x0+dx,y0,z0+dz),P(x0,y0,z0+dz)]
    sd =[P(x0+dx,y0,z0),P(x0+dx,y0+dy,z0),P(x0+dx,y0+dy,z0+dz),P(x0+dx,y0,z0+dz)]
    return poly(fr,cfront)+poly(sd,cside)+poly(top,ctop)

def sheet2():
    E=[f'<rect width="{W}" height="{H}" fill="#ffffff"/>']
    E.append(rect(24,24,W-48,H-48,"none",LINE,2))
    E.append(rect(24,24,W-48,40,BLUE,BLUE))
    E.append(txt(40,50,"SHEET 2  -  EXPLODED ASSEMBLY, CUT LIST and JOINT DETAIL  (WOOD 2x4)",15,"#fff","start","bold"))

    # ---- EXPLODED ISO (left) ----
    E.append(txt(70,96,"EXPLODED ASSEMBLY",14,BLUE,"start","bold"))
    ox,oy,s=250,470,0.40
    # posts (2)
    E.append(isobox(0,0,0,30,30,760, ox,oy,s))
    E.append(isobox(0,300,0,30,30,760, ox,oy,s))
    # top beam lifted above
    E.append(isobox(0,30,800,30,270,30, ox,oy,s, ctop="#e8c88a"))
    # feet
    E.append(isobox(-120,0,-70,270,30,30, ox,oy,s, ctop="#c9a15f"))
    E.append(isobox(-120,300,-70,270,30,30, ox,oy,s, ctop="#c9a15f"))
    # diagonal braces floating near top corners
    for gy in (30,300):
        gp=iso(15,gy,700,ox,oy,s)
        E.append(line(gp[0]-4,gp[1]+24,gp[0]+22,gp[1]-2,WOOD3,9,"","round"))
        E.append(line(gp[0]-4,gp[1]+24,gp[0]+22,gp[1]-2,LINE,1.2,"","round"))
    def leader(px,py,n,tx,ty,label):
        return line(px,py,tx,ty,"#888",0.8)+balloon(tx,ty,n)+txt(tx+16,ty+4,label,10,BLUE,"start","bold")
    E.append(leader(*iso(15,0,400,ox,oy,s),1,110,500,"POST  x2"))
    E.append(leader(*iso(15,150,815,ox,oy,s),2,360,150,"TOP BEAM  x1"))
    E.append(leader(*iso(15,30,700,ox,oy,s),3,360,210,"DIAGONAL BRACE  x2"))
    E.append(txt(120,590,"NO bottom beam - fall zone open",10,RED,"start","bold"))
    E.append(leader(*iso(0,15,-55,ox,oy,s),6,110,690,"PEDESTAL FOOT  x2"))
    E.append(txt(70,760,"Assembly: butt beam between posts, fix with angle brackets + lag screws,",10,"#555"))
    E.append(txt(70,776,"add diagonal braces, then wide feet + kick braces, then radar housing + sandbags.",10,"#555"))

    # ---- CUT LIST (top right) ----
    tx0,ty0=760,145; cw=590
    E.append(txt(tx0,110,"CUT LIST  /  BILL OF MATERIALS",14,BLUE,"start","bold"))
    rows=[("ID","PART","SPEC","LEN (mm)","QTY","MATERIAL"),
          ("1","Vertical post","2x4 SPF (38 x 89)","2400","2","Wood"),
          ("2","Top cross-beam","2x4 SPF (38 x 89)","1140","1","Wood"),
          ("3","Diagonal brace","2x4 SPF, 45 deg both ends","~500","2","Wood"),
          ("6","Pedestal foot (wide)","2x4 SPF (38 x 89)","600","2","Wood"),
          ("7","Kick brace (foot)","2x4 SPF, 45 deg","~300","2","Wood"),
          ("5","Corner angle bracket","90 mm steel L-angle","-","4~8","Steel"),
          ("8","Lag screw","M8 x 90 (pilot-drill)","-","~16","Steel"),
          ("9","Wood screw","4.0 x 50","-","~40","Steel"),
          ("10","Rubber pad / felt","under foot","-","4","Rubber"),
          ("11","Sandbag ballast","~10-15 kg each","-","2","-"),
          ("-","Radar housing","3D-print PETG","-","1","see housing"),]
    colx=[tx0,tx0+40,tx0+185,tx0+375,tx0+460,tx0+510]
    rh=25
    E.append(rect(tx0-6,ty0-18,cw,rh*len(rows)+10,"#fff",LINE,1.2))
    for i,r in enumerate(rows):
        yy=ty0+i*rh
        if i==0:
            E.append(rect(tx0-6,ty0-18,cw,rh,"#e9eef4",LINE,1.0))
        else:
            E.append(line(tx0-6,yy-18,tx0-6+cw,yy-18,"#dde3ea",0.8))
        for c,val in enumerate(r):
            bold="bold" if (i==0 or c==0) else "normal"
            col = BLUE if i==0 else INK
            E.append(txt(colx[c],yy,val,10 if i else 10.5,col,"start",bold))
    E.append(txt(tx0,ty0+rh*len(rows)+8,"Wood = cheaper + far less light reflection than aluminium (better for camera/radar demo).",10,RED,"start","bold"))

    # ---- JOINT DETAIL (bottom right) ----
    jx,jy=780,640
    E.append(txt(jx,jy-14,"DETAIL A - WOOD CORNER JOINT (typ. top 2 corners)",13,BLUE,"start","bold"))
    # post + beam (butt)
    E.append(rect(jx+70,jy,26,150,WOOD,LINE,1.6))          # post
    E.append(rect(jx+70,jy,180,26,WOOD2,LINE,1.6))         # beam
    # diagonal brace across corner
    E.append(line(jx+96,jy+120,jx+186,jy+26,WOOD3,16,"","round"))
    E.append(line(jx+96,jy+120,jx+186,jy+26,LINE,1.4,"","round"))
    # metal angle bracket at inner corner
    E.append(rect(jx+96,jy+26,40,5,METAL,"#20262c",1.2))
    E.append(rect(jx+96,jy+26,5,40,METAL,"#20262c",1.2))
    # lag/wood screws
    for (bx,by) in [(jx+120,jy+38),(jx+108,jy+55),(jx+150,jy+95),(jx+128,jy+75)]:
        E.append(circ(bx,by,3.4,"#20262c","#000",1)); E.append(circ(bx,by,1.3,"#888"))
    E.append(txt(jx+205,jy+66,"Butt joint + diagonal brace,",10,INK))
    E.append(txt(jx+205,jy+82,"metal L-angle both faces,",10,INK))
    E.append(txt(jx+205,jy+98,"lag screws (pilot-drilled).",10,INK))
    E.append(txt(jx+205,jy+122,"-> stops racking / sag",10,RED,"start","bold"))
    E.append(txt(jx+205,jy+138,"-> no welding, hand tools only",10,RED,"start","bold"))

    E.append(title_block(2))
    E.append(txt(40,H-30,"NOTE: Cut ends square (+/-1 mm). Pre-drill pilot holes before lag screws to avoid splitting. Radar face height 2300 mm set by trimming post / shims. Assembly with drill-driver only.",9.5,"#444"))
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d">%s</svg>'%(W,H,''.join(E))

open('frame_wood_sheet1.svg','w').write(sheet1())
open('frame_wood_sheet2.svg','w').write(sheet2())
import cairosvg
cairosvg.svg2png(url='frame_wood_sheet1.svg',write_to='frame_wood_sheet1.png',output_width=1680)
cairosvg.svg2png(url='frame_wood_sheet2.svg',write_to='frame_wood_sheet2.png',output_width=1680)
print("wood sheets done")
