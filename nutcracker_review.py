#!/usr/bin/env python3
"""NUTCRACKER graphical review console; local X11/Tk/MPV."""
import argparse
import json
import os
import re
import subprocess
import time
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from types import SimpleNamespace
import nutcracker as nc
from nutcracker_player import Player, timestamp


def monitors():
    out = subprocess.check_output(['xrandr','--listmonitors'], text=True)
    return [tuple(map(int,m.groups())) for m in re.finditer(r'(\d+)/\d+x(\d+)/\d+([+-]\d+)([+-]\d+)',out)]


def safe_geometry(rect):
    w,h,x,y = rect
    for mw,mh,mx,my in monitors():
        if mx <= x < mx+mw-100 and my <= y < my+mh-100:
            return [min(w,mw),min(h,mh),x,y]
    mw,mh,mx,my = monitors()[0]
    return [min(w,mw),min(h,mh),mx+40,my+40]


def video_window(pid):
    for line in subprocess.check_output(['wmctrl','-lpG'],text=True).splitlines():
        p=line.split(None,8)
        if len(p)>=8 and p[2]==str(pid):
            return p[0], [int(p[5]),int(p[6]),int(p[3]),int(p[4])]
    return None,None


class Review:
    def __init__(self,root,args,player,db,settings):
        self.root,self.args,self.player,self.db,self.settings=root,args,player,db,settings
        self.started=time.monotonic(); self.saved=0; self.preview=None; self.index=0
        self.rows=[]; self.context=1.0
        root.title('NUTCRACKER — '+args.video.stem)
        w,h,x,y=safe_geometry(settings.get('console',[1100,850,40,40]))
        root.geometry(f'{w}x{h}+{x}+{y}')
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.minsize(640, 500)
        style=ttk.Style(root)
        style.configure('Review.TButton',padding=(12,8))
        nav=ttk.Frame(root); nav.pack(fill='x',padx=12,pady=(10,4))
        self.prev_button=ttk.Button(nav,text='← Previous evidence',style='Review.TButton',command=lambda:self.move(-1))
        self.prev_button.pack(side='left',padx=(0,8))
        self.next_button=ttk.Button(nav,text='Next evidence →',style='Review.TButton',command=lambda:self.move(1))
        self.next_button.pack(side='left',padx=4)
        ttk.Label(nav,text='Ctrl+Left / Ctrl+Right').pack(side='left',padx=8)
        root.bind('<Control-Left>',lambda e:self.keyboard_move(-1))
        root.bind('<Control-Right>',lambda e:self.keyboard_move(1))
        bar=ttk.Frame(root); bar.pack(fill='x',padx=8,pady=6)
        self.tier=tk.StringVar(value=args.tier or settings.get('tier','focused'))
        tier=ttk.Combobox(bar,textvariable=self.tier,values=nc.TIERS,state='readonly',width=16); tier.pack(side='left'); tier.bind('<<ComboboxSelected>>',lambda e:self.refresh())
        self.info=ttk.Label(bar); self.info.pack(side='left',padx=10)
        controls=ttk.Frame(root); controls.pack(fill='x',padx=8)
        for label,fn in [('Replay window',self.play_window),('Replay item',self.play_item),('Pause / play',lambda:self.player.set('pause',not self.player.get('pause'))),('Context +',lambda:self.change_context(1)),('Context −',lambda:self.change_context(-1))]:
            ttk.Button(controls,text=label,style='Review.TButton',command=lambda f=fn:self.guard(f)).grid(row=0 if label in ('Replay window','Replay item','Pause / play') else 1,column={'Replay window':0,'Replay item':1,'Pause / play':2,'Context +':0,'Context −':1}[label],sticky='ew',padx=4,pady=4)
        opts=ttk.Frame(root); opts.pack(fill='x',padx=8,pady=6)
        self.track=tk.StringVar(value='original')
        self.trackbox=ttk.Combobox(opts,textvariable=self.track,state='readonly',width=25); self.trackbox.grid(row=0,column=0,columnspan=6,sticky='w',padx=4,pady=4); self.trackbox.bind('<<ComboboxSelected>>',lambda e:self.guard(self.select_track))
        for col,(label,prop,values,default) in enumerate( [('Volume','volume',[0,25,50,75,100,125],75),('Speed','speed',[.5,.75,1,1.25,1.5],1),('Subtitle size','sub-scale',[.75,1,1.25,1.5,2,3],1)]):
            ttk.Label(opts,text=label).grid(row=1,column=col*2,padx=4,pady=4)
            var=tk.StringVar(value=str(settings.get(prop,default)))
            cb=ttk.Combobox(opts,textvariable=var,values=values,width=6,state='readonly'); cb.grid(row=1,column=col*2+1,padx=4,pady=4); cb.bind('<<ComboboxSelected>>',lambda e,p=prop,v=var:self.guard(lambda:self.player.set(p,float(v.get()))))
            self.player.set(prop,float(var.get()))
        frame=ttk.Frame(root); frame.pack(side='top',fill='both',expand=True,padx=8,pady=6)
        self.text=tk.Text(frame,wrap='word',font=('TkDefaultFont',12),state='disabled'); self.text.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(frame,command=self.text.yview); scroll.pack(side='right',fill='y'); self.text.configure(yscrollcommand=scroll.set)
        ttk.Label(root,text='Correction (only used by Correct):').pack(anchor='w',padx=8)
        self.correction=tk.Text(root,height=3,wrap='word'); self.correction.pack(fill='x',padx=8)
        ttk.Label(root,text='Optional notes:').pack(anchor='w',padx=8)
        self.notes=ttk.Entry(root); self.notes.pack(fill='x',padx=8)
        buttons=ttk.Frame(root); buttons.pack(fill='x',padx=8,pady=8,before=frame)
        for i,(label,status) in enumerate([('Accept','accepted'),('Correct','corrected'),('Reject','rejected'),('Defer','deferred'),('Unresolvable','unresolvable')]):
            ttk.Button(buttons,text=label,style='Review.TButton',command=lambda s=status:self.guard(lambda:self.decide(s))).grid(row=i//3,column=i%3,sticky='ew',padx=4,pady=4)
        frame.pack_forget()
        frame.pack(fill='both',expand=True,padx=8,pady=6)
        self.refresh()
        root.after(500,self.restore_video)

    def guard(self,fn):
        try: fn()
        except Exception as e: messagebox.showerror('NUTCRACKER',str(e),parent=self.root)

    def restore_video(self):
        wid,_=video_window(self.player.process.pid)
        if wid and 'video' in self.settings:
            w,h,x,y=safe_geometry(self.settings['video'])
            subprocess.run(['wmctrl','-ir',wid,'-e',f'0,{x},{y},{w},{h}'],check=False)
            if self.settings.get('video_maximized'): subprocess.run(['wmctrl','-ir',wid,'-b','add,maximized_vert,maximized_horz'],check=False)
        if self.settings.get('console_maximized'): self.root.attributes('-zoomed',True)

    def refresh(self):
        self.rows=self.db.execute('''SELECT e.*,w.start AS ws,w.end AS we,w.window_id FROM evidence e JOIN decisions d ON d.evidence_identity=e.identity JOIN window_evidence a ON a.evidence_identity=e.identity JOIN windows w ON w.tier=a.tier AND w.window_id=a.window_id WHERE a.tier=? AND a.relationship='contained' AND d.status='pending' ORDER BY w.start,e.start,e.source_id''',(self.tier.get(),)).fetchall()
        self.index=0; self.show()

    def keyboard_move(self,delta):
        if isinstance(self.root.focus_get(),(tk.Text,tk.Entry,ttk.Entry,ttk.Combobox)):
            return
        self.move(delta)
        return 'break'

    def move(self,delta):
        if self.rows: self.index=max(0,min(len(self.rows)-1,self.index+delta)); self.guard(self.show)

    def show(self):
        self.prev_button.configure(state='normal' if self.rows and self.index>0 else 'disabled')
        self.next_button.configure(state='normal' if self.index+1<len(self.rows) else 'disabled')
        self.player.set('pause',True)
        self.correction.delete('1.0','end'); self.notes.delete(0,'end')
        self.text.configure(state='normal'); self.text.delete('1.0','end')
        if not self.rows:
            self.info.configure(text='No pending evidence in this tier'); self.text.insert('end','Select another tier or close.'); self.text.configure(state='disabled'); return
        r=self.rows[self.index]; p=json.loads(r['payload']); self.payload=p
        self.info.configure(text=f"{r['window_id']} | {r['source_id']} | {self.index+1}/{len(self.rows)} pending")
        self.text.insert('end',f"{r['kind'].upper()}  {timestamp(r['start'])} – {timestamp(r['end'])} ({r['start']:.3f} – {r['end']:.3f}s)\n\n")
        for i,h in enumerate(p.get('hypotheses',[]),1):
            self.text.insert('end',f"Hypothesis {i}: {' '.join(h['normalized_words']) or '[no lexical words]'}\nSupport: {h.get('supporting_passes')}\n\n")
        self.text.insert('end','Full local evidence:\n'+json.dumps(p,ensure_ascii=False,indent=2)); self.text.configure(state='disabled')
        self.trackbox.configure(values=['none','original','recovered']+[f'Hypothesis {i}' for i in range(1,len(p.get('hypotheses',[]))+1)])
        self.track.set('original'); self.select_track(); self.player.set_window(r['ws'],min(r['we'],self.player.duration))

    def select_track(self):
        label=self.track.get()
        self.player.select_subtitles(None)
        if self.preview:
            self.player.remove_subtitles(self.preview); self.preview=None
        if label.startswith('Hypothesis ') and self.rows:
            r=self.rows[self.index]; h=self.payload['hypotheses'][int(label.split()[-1])-1]; text=' '.join(h['normalized_words'])
            if text:
                # Display-only context, not a proposed caption timing.
                self.player.add_preview('preview',[(max(r['ws'],r['start']-.5),min(r['we'],self.player.duration,max(r['end'],r['start']+1.5)),text)])
                self.preview='preview'; self.player.select_subtitles('preview')
        elif label!='none': self.player.select_subtitles(label)

    def play_window(self):
        if self.rows:
            r=self.rows[self.index]; self.player.set_window(r['ws'],min(r['we'],self.player.duration)); self.player.replay()

    def play_item(self):
        if self.rows:
            r=self.rows[self.index]; self.player.set_window(max(0,r['start']-self.context),min(self.player.duration,r['end']+self.context)); self.player.replay()

    def change_context(self,delta):
        self.context=max(.25,self.context+delta*.5); self.play_item()

    def decide(self,status):
        if not self.rows:return
        r=self.rows[self.index]; hypothesis=None; correction=None
        if status=='accepted' and r['kind']=='magpie':
            if not self.track.get().startswith('Hypothesis '): raise ValueError('Select a hypothesis to accept.')
            hypothesis=int(self.track.get().split()[-1])
        if status=='corrected': correction=self.correction.get('1.0','end').strip()
        prompt={'accepted':'Confirm selected lexical hypothesis' if r['kind']=='magpie' else 'Confirm speech missing from current recognition coverage','rejected':'Reject evidence as a basis for correction','corrected':'Record your corrected dialogue','deferred':'Defer for later review','unresolvable':'Mark as unresolvable'}[status]
        if not messagebox.askyesno('Confirm decision',f"{r['source_id']}: {prompt}?",parent=self.root):return
        nc.command_decide(SimpleNamespace(database=self.args.database,evidence_id=r['source_id'],status=status,hypothesis=hypothesis,correction=correction,notes=self.notes.get().strip() or None))
        self.saved+=1; old=self.index; self.refresh(); self.index=min(old,max(0,len(self.rows)-1)); self.show()

    def close(self):
        try:
            self.root.update_idletasks(); s=dict(self.settings)
            s['console']=[self.root.winfo_width(),self.root.winfo_height(),self.root.winfo_x(),self.root.winfo_y()]; s['console_maximized']=bool(self.root.attributes('-zoomed')); s['tier']=self.tier.get()
            wid,rect=video_window(self.player.process.pid)
            if rect:s['video']=rect
            if wid:
                state=subprocess.check_output(['xprop','-id',wid,'_NET_WM_STATE'],text=True); s['video_maximized']='MAXIMIZED_VERT' in state and 'MAXIMIZED_HORZ' in state
            for prop in ('volume','speed','sub-scale'):s[prop]=self.player.get(prop)
            tmp=self.args.settings.with_suffix('.tmp'); tmp.write_text(json.dumps(s,indent=2)); os.replace(tmp,self.args.settings)
        except Exception as e: messagebox.showwarning('Settings not fully saved',str(e),parent=self.root)
        finally:
            print(f'Decisions committed: {self.saved}; replay commands: {self.player.replays}; elapsed session: {time.monotonic()-self.started:.3f}s'); self.root.destroy()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('database','video','original','recovered'):p.add_argument(name,type=Path)
    p.add_argument('--tier',choices=nc.TIERS); p.add_argument('--settings',type=Path,default=Path('nutcracker_settings.json')); a=p.parse_args()
    settings=json.loads(a.settings.read_text()) if a.settings.exists() else {}
    db=nc.connect(a.database)
    try:
        nc.audit_database(db)
        with Player(a.video) as player:
            player.add_subtitles('original',a.original); player.add_subtitles('recovered',a.recovered)
            root=tk.Tk(); Review(root,a,player,db,settings); root.mainloop()
    finally:db.close()

if __name__=='__main__':main()
