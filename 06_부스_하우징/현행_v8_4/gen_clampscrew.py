#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""완전 프린트 손잡이볼트 (둥근 굵은 나사) — 뚜껑 8mm 구멍에 셀프탭으로 조임. 2개 필요."""
import numpy as np, trimesh
from trimesh.creation import cylinder, icosphere, box

r_core=3.0; r_pitch=3.7; bead=1.2; pitch=3.0; shaft_len=15.0   # 나사부
knob_r=11.0; knob_h=9.0; flutes=12                              # 손잡이(널링)

def thread(length):
    core=cylinder(radius=r_core,height=length,sections=48); core.apply_translation([0,0,length/2])
    tmax=2*np.pi*length/pitch; n=int(tmax*r_pitch/0.9); beads=[]
    for i in range(n+1):
        th=tmax*i/n; z=pitch*th/(2*np.pi)
        if z<bead*0.5 or z>length-bead*0.5: continue
        s=icosphere(subdivisions=1,radius=bead); s.apply_translation([r_pitch*np.cos(th),r_pitch*np.sin(th),z]); beads.append(s)
    return trimesh.boolean.union([core]+beads,engine='manifold')

# 손잡이(널링): 원판 - 둘레 홈
knob=cylinder(radius=knob_r,height=knob_h,sections=64); knob.apply_translation([0,0,knob_h/2])
cuts=[]
for i in range(flutes):
    a=2*np.pi*i/flutes
    c=cylinder(radius=1.4,height=knob_h*1.2,sections=12); c.apply_translation([knob_r*np.cos(a),knob_r*np.sin(a),knob_h/2]); cuts.append(c)
knob=knob.difference(cuts,engine='manifold')
# 손잡이 윗면 파지 홈(십자)
gx=box([knob_r*1.6,2.0,2.2]); gx.apply_translation([0,0,knob_h-0.3])
gy=box([2.0,knob_r*1.6,2.2]); gy.apply_translation([0,0,knob_h-0.3])
knob=knob.difference([gx,gy],engine='manifold')

sh=thread(shaft_len); sh.apply_translation([0,0,-shaft_len])   # 손잡이 아래로 나사부
screw=trimesh.boolean.union([knob,sh],engine='manifold')
screw.export('clamp_screw.stl')
print('clamp_screw watertight:',screw.is_watertight,'major_dia≈%.1f'%(2*(r_pitch+bead)),'len≈%.0f'%(knob_h+shaft_len))
