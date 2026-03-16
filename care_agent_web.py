#!/usr/bin/env python3
"""
Care Agent v3 — A warm, intelligent caregiver companion.

AI Providers: Ollama (local) | OpenRouter (cloud) | Anthropic (cloud)
TTS Engines:  edge-tts (neural) | Piper (offline) | espeak-ng (fallback)

Usage:
    python3 care_agent_web.py --port 8080 --no-open
"""

import json,os,sys,time,math,wave,struct,shutil,tempfile,base64
import subprocess,datetime,threading,random,argparse,webbrowser,re
from pathlib import Path
from flask import Flask,request,jsonify,send_file,send_from_directory

# ━━━ Paths ━━━
BD = Path.home()/".care-agent"
CF = BD/"config.json"
SF = BD/"schedule.json"
LF = BD/"care_log.json"
MF = BD/"memory.json"
EF = BD/"events.json"    # calendar events
PF = BD/"profile.json"   # profile data
UF = BD/"uploads"        # profile photos etc

TONES = {
    "meal":       {"freq":523,"pattern":"long","repeats":2,"icon":"\U0001f37d\ufe0f","label":"Meal","color":"#d97706"},
    "bathroom":   {"freq":659,"pattern":"short","repeats":3,"icon":"\U0001f6bb","label":"Bathroom","color":"#2563eb"},
    "medication": {"freq":784,"pattern":"urgent","repeats":4,"icon":"\U0001f48a","label":"Medication","color":"#dc2626"},
    "activity":   {"freq":440,"pattern":"gentle","repeats":1,"icon":"\U0001f3af","label":"Activity","color":"#059669"},
    "sleep":      {"freq":349,"pattern":"gentle","repeats":1,"icon":"\U0001f634","label":"Sleep","color":"#4f46e5"},
    "hydration":  {"freq":587,"pattern":"short","repeats":2,"icon":"\U0001f4a7","label":"Hydration","color":"#0891b2"},
    "custom":     {"freq":698,"pattern":"long","repeats":2,"icon":"\U0001f4cb","label":"Task","color":"#7c3aed"},
    "appointment":{"freq":550,"pattern":"long","repeats":3,"icon":"\U0001f4c5","label":"Appointment","color":"#be185d"},
    "checkin":    {"freq":466,"pattern":"gentle","repeats":2,"icon":"\U0001f4ac","label":"Check-in","color":"#db2777"},
}
RLEAD=[10,5,0]

DEFAULT_SCHEDULE={"name":"Care Recipient","tasks":[
    {"time":"07:00","category":"bathroom","title":"Morning diaper / bathroom","steps":["Check diaper / assist to bathroom","Clean and change if needed","Wash hands","Apply barrier cream if needed"]},
    {"time":"07:30","category":"medication","title":"Morning medication","steps":["Prepare prescribed medication","Give with water/food as directed","Log that medication was given"]},
    {"time":"08:00","category":"meal","title":"Breakfast","steps":["Prepare balanced breakfast","Assist with eating if needed","Offer water/juice","Clean up"]},
    {"time":"09:30","category":"bathroom","title":"Mid-morning bathroom check","steps":["Check diaper / offer bathroom","Change if needed"]},
    {"time":"10:00","category":"hydration","title":"Hydration check","steps":["Offer water or preferred drink","Ensure at least 4 oz consumed"]},
    {"time":"10:30","category":"activity","title":"Morning activity","steps":["Engage in preferred activity","Encourage movement and interaction"]},
    {"time":"12:00","category":"bathroom","title":"Pre-lunch bathroom","steps":["Check diaper / assist to bathroom","Wash hands"]},
    {"time":"12:15","category":"meal","title":"Lunch","steps":["Prepare lunch","Assist with eating if needed","Offer drink","Clean up"]},
    {"time":"13:00","category":"medication","title":"Afternoon medication (if applicable)","steps":["Check if afternoon dose is scheduled","Administer if needed"]},
    {"time":"14:00","category":"bathroom","title":"Afternoon bathroom check","steps":["Check diaper / offer bathroom","Change if needed"]},
    {"time":"14:30","category":"hydration","title":"Afternoon hydration","steps":["Offer water or preferred drink"]},
    {"time":"15:00","category":"activity","title":"Afternoon activity / therapy","steps":["Engage in scheduled therapy or activity","Take notes on progress if applicable"]},
    {"time":"16:30","category":"bathroom","title":"Pre-dinner bathroom check","steps":["Check diaper / offer bathroom"]},
    {"time":"17:00","category":"meal","title":"Dinner","steps":["Prepare dinner","Assist with eating","Offer drink","Clean up"]},
    {"time":"18:00","category":"medication","title":"Evening medication (if applicable)","steps":["Check if evening dose is scheduled","Administer if needed"]},
    {"time":"19:00","category":"bathroom","title":"Evening bathroom / diaper change","steps":["Full diaper change or bathroom assist","Evening hygiene routine","Apply barrier cream"]},
    {"time":"19:30","category":"activity","title":"Wind-down activity","steps":["Calm activity (reading, gentle music, etc.)","Begin bedtime transition"]},
    {"time":"20:00","category":"sleep","title":"Bedtime routine","steps":["Change into pajamas","Brush teeth","Final bathroom check","Settle into bed","Goodnight!"]},
    {"time":"22:00","category":"bathroom","title":"Late-night diaper check","steps":["Check diaper without fully waking if possible","Change if needed"]},
],"checkin_interval_minutes":90}

APP_VERSION = "3.3.0"
UPDATE_CHECK_URL = "https://raw.githubusercontent.com/Cl4pp/care-agent/main"  # Set to raw GitHub URL, e.g. "https://raw.githubusercontent.com/user/care-agent/main"

DEFAULT_CONFIG={
    "caregiver_name":"","recipient_name":"Care Recipient",
    "theme":"auto","accent_color":"#6366f1",
    "ai_provider":"ollama","ollama_model":"llama3.2","ollama_url":"http://localhost:11434",
    "openrouter_key":"","openrouter_model":"meta-llama/llama-3.1-8b-instruct:free",
    "anthropic_key":"",
    "tts_engine":"auto",
    "daily_affirmation":True,
    "greeting_message":"",
    "auto_read_chat":True,
    "update_url":"",
}

# ━━━ Data layer ━━━
def ensure_dirs():
    for d in [BD, BD/"piper-voices", UF]: d.mkdir(parents=True, exist_ok=True)

def ldj(p, dflt=None):
    if dflt is None: dflt={}
    try:
        if p.exists():
            with open(p) as f: return json.load(f)
    except: pass
    return dflt

def svj(p, d):
    with open(p,"w") as f: json.dump(d,f,indent=2,default=str)

def gcfg():
    c=ldj(CF,dict(DEFAULT_CONFIG))
    for k,v in DEFAULT_CONFIG.items():
        if k not in c: c[k]=v
    return c

def scfg(c): svj(CF,c)

def gsched():
    d=ldj(SF)
    if not d or "tasks" not in d: svj(SF,DEFAULT_SCHEDULE); return dict(DEFAULT_SCHEDULE)
    return d

def ssched(d): svj(SF,d)

def gmem():
    return ldj(MF,{"notes":[],"preferences":{}})

def smem(m): svj(MF,m)

def add_mem(note):
    m=gmem(); m["notes"].append({"text":note,"time":datetime.datetime.now().isoformat()})
    if len(m["notes"])>300: m["notes"]=m["notes"][-300:]
    smem(m)

def gevents():
    return ldj(EF,{"events":[]}).get("events",[])

def sevents(evts):
    svj(EF,{"events":evts})

def gprofile():
    return ldj(PF,{"photo_path":"","bio":"","birthday":"","favorites":"","medical_notes":""})

def sprofile(p): svj(PF,p)

def fmt12(t24):
    """Convert HH:MM to 12h format."""
    try:
        h,m=map(int,t24.split(":"))
        ap="AM" if h<12 else "PM"
        h12=h%12 or 12
        return f"{h12}:{m:02d} {ap}"
    except: return t24

def today_tasks(sched):
    ts=datetime.date.today().isoformat()
    log=ldj(LF,{})
    tl=log.get(ts,{})
    tasks=[]
    for i,task in enumerate(sched.get("tasks",[])):
        t=dict(task); t["id"]=f"task_{i}"; t["index"]=i
        t["done"]=tl.get(t["id"],{}).get("done",False)
        t["done_at"]=tl.get(t["id"],{}).get("done_at")
        t["skipped"]=tl.get(t["id"],{}).get("skipped",False)
        t["notes"]=tl.get(t["id"],{}).get("notes","")
        pr=TONES.get(t.get("category","custom"),TONES["custom"])
        t["icon"]=pr["icon"]; t["color"]=pr["color"]; t["category_label"]=pr["label"]
        t["time12"]=fmt12(t["time"])
        tasks.append(t)
    tasks.sort(key=lambda x:x["time"])
    return tasks

def mark(tid, done=True, skipped=False, notes=""):
    ts=datetime.date.today().isoformat(); log=ldj(LF,{})
    if ts not in log: log[ts]={}
    log[ts][tid]={"done":done,"skipped":skipped,"done_at":datetime.datetime.now().isoformat(),"notes":notes}
    svj(LF,log)


# ━━━ Audio ━━━
def _genwav(freq,ms,vol=0.6):
    sr=44100;n=int(sr*ms/1000);fade=min(500,n//4);samps=[]
    for i in range(n):
        v=vol*math.sin(2*math.pi*freq*i/sr)
        if i<fade:v*=i/fade
        elif i>n-fade:v*=(n-i)/fade
        samps.append(int(v*32767))
    buf=struct.pack(f"<{len(samps)}h",*samps)
    with tempfile.NamedTemporaryFile(suffix=".wav",delete=False) as f:
        with wave.open(f,'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(sr);w.writeframes(buf)
        return f.name

def _playf(path):
    for p in["paplay","aplay","ffplay -nodisp -autoexit"]:
        try: subprocess.run(p.split()+[path],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10);return
        except: continue

def play_tone(cat):
    pr=TONES.get(cat,TONES["custom"])
    pats={"long":[500],"short":[150,100,150],"urgent":[200,80,200,80,400],"gentle":[300]}
    for _ in range(pr["repeats"]):
        for d in pats.get(pr["pattern"],[300]):
            w=_genwav(pr["freq"],d);_playf(w)
            try:os.unlink(w)
            except:pass
            time.sleep(0.08)
        time.sleep(0.25)


# ━━━ TTS: edge-tts → Piper → espeak ━━━
class TTS:
    def __init__(self,cfg):
        self.engine=None; self.engine_name="none"
        pref=cfg.get("tts_engine","auto")
        # Try edge-tts (Microsoft neural voices, pip install edge-tts)
        if pref in("auto","edge-tts"):
            try:
                import importlib
                if importlib.util.find_spec("edge_tts"):
                    self.engine=("edge-tts",); self.engine_name="edge-tts (neural)"; return
            except: pass
        # Try Piper
        if pref in("auto","piper"):
            pb=shutil.which("piper"); vd=BD/"piper-voices"; model=None
            if vd.exists():
                for f in vd.glob("*.onnx"): model=str(f); break
            if pb and model:
                self.engine=("piper",pb,model); self.engine_name="piper"; return
        # Try espeak
        if pref in("auto","espeak"):
            for cmd in["espeak-ng","espeak"]:
                if shutil.which(cmd):
                    self.engine=("espeak",cmd); self.engine_name=cmd; return

    @property
    def available(self): return self.engine is not None

    def speak(self,text):
        if not self.engine:return
        threading.Thread(target=self._do,args=(text,),daemon=True).start()

    def _do(self,text):
        try:
            if self.engine[0]=="edge-tts":
                import asyncio, edge_tts
                async def _run():
                    c=edge_tts.Communicate(text,"en-US-JennyNeural")
                    with tempfile.NamedTemporaryFile(suffix=".mp3",delete=False) as f:
                        out=f.name
                    await c.save(out)
                    _playf(out)
                    try:os.unlink(out)
                    except:pass
                asyncio.run(_run())
            elif self.engine[0]=="piper":
                with tempfile.NamedTemporaryFile(suffix=".wav",delete=False) as f: out=f.name
                subprocess.run([self.engine[1],"--model",self.engine[2],"--output_file",out],
                               input=text.encode(),capture_output=True,timeout=30)
                if os.path.getsize(out)>0:_playf(out)
                try:os.unlink(out)
                except:pass
            elif self.engine[0]=="espeak":
                subprocess.run([self.engine[1],text],capture_output=True,timeout=15)
        except Exception as e: print(f"[TTS err] {e}")

    def speak_reminder(self,task,lead):
        t=task["title"]
        if lead==0: self.speak(f"Time for: {t}.")
        elif lead==5: self.speak(f"{t} in 5 minutes.")
        else: self.speak(f"{t} coming up in {lead} minutes.")


# ━━━ AI Chat with tools ━━━
SYS_PROMPT="""You are a kind, practical care assistant. The caregiver has ADHD — be concise, warm, action-focused. 1-4 sentences.

You can MODIFY the schedule by including JSON blocks. Use this exact format in your response:

To add a task:
```json
{"action":"add_task","time":"HH:MM","title":"Task name","category":"meal|bathroom|medication|activity|sleep|hydration|custom|appointment","steps":["step1"]}
```

To remove a task (by partial title match):
```json
{"action":"remove_task","title_match":"partial title"}
```

To save a memory note (medications, preferences, important info that should persist):
```json
{"action":"save_memory","note":"What to remember forever"}
```

To add a calendar event:
```json
{"action":"add_event","date":"YYYY-MM-DD","time":"HH:MM","title":"Event name","category":"appointment"}
```

Always confirm what you did in plain language. Be encouraging."""

def build_ctx(sched,cfg):
    now=datetime.datetime.now()
    tasks=today_tasks(sched); mem=gmem(); events=gevents()
    lines=[f"Time: {now.strftime('%I:%M %p, %A %B %d')}",
           f"Caregiver: {cfg.get('caregiver_name','(not set)')}",
           f"Recipient: {cfg.get('recipient_name','Care Recipient')}","","Schedule:"]
    for t in tasks:
        s="DONE" if t["done"] else("SKIP" if t["skipped"] else("OVERDUE" if t["time"]<=now.strftime("%H:%M") else "pending"))
        lines.append(f"  [{s}] {t['time12']} — {t['title']} ({t['category']})")
    if mem.get("notes"):
        lines.append("\nMemory:")
        for n in mem["notes"][-20:]: lines.append(f"  - {n['text']}")
    upcoming_events=[e for e in events if e.get("date","")>=now.strftime("%Y-%m-%d")][:5]
    if upcoming_events:
        lines.append("\nUpcoming events:")
        for e in upcoming_events: lines.append(f"  - {e['date']} {e.get('time','')} — {e['title']}")
    return "\n".join(lines)

def process_actions(text):
    actions=[]
    for m in re.findall(r'```json\s*(\{[^`]+\})\s*```',text,re.DOTALL):
        try:
            a=json.loads(m); act=a.get("action")
            if act=="add_task":
                s=gsched()
                s["tasks"].append({"time":a["time"],"title":a["title"],"category":a.get("category","custom"),"steps":a.get("steps",[])})
                s["tasks"].sort(key=lambda x:x["time"]); ssched(s)
                actions.append(f"Added: {fmt12(a['time'])} — {a['title']}")
            elif act=="remove_task":
                s=gsched(); mt=a["title_match"].lower(); before=len(s["tasks"])
                s["tasks"]=[t for t in s["tasks"] if mt not in t["title"].lower()]
                ssched(s); actions.append(f"Removed {before-len(s['tasks'])} task(s)")
            elif act=="save_memory":
                add_mem(a["note"]); actions.append(f"Remembered: {a['note']}")
            elif act=="add_event":
                evts=gevents()
                evts.append({"date":a["date"],"time":a.get("time",""),"title":a["title"],"category":a.get("category","appointment")})
                evts.sort(key=lambda x:x.get("date","")+x.get("time","")); sevents(evts)
                actions.append(f"Event added: {a['date']} — {a['title']}")
        except: pass
    clean=re.sub(r'```json\s*\{[^`]+\}\s*```','',text,flags=re.DOTALL).strip()
    return clean,actions

def _ollama(msg,ctx,cfg):
    if cfg.get("ai_provider")not in("ollama",): return ""
    try:
        import httpx
        r=httpx.post(cfg.get("ollama_url","http://localhost:11434")+"/api/chat",json={
            "model":cfg.get("ollama_model","llama3.2"),"stream":False,
            "messages":[{"role":"system","content":SYS_PROMPT+"\n\n"+ctx},{"role":"user","content":msg}],
            "options":{"num_predict":600}
        },timeout=120)
        if r.status_code==200: return r.json().get("message",{}).get("content","")
    except Exception as e: return f"[Ollama error: {e}]"
    return ""

def _openrouter(msg,ctx,cfg):
    if cfg.get("ai_provider")!="openrouter": return ""
    key=cfg.get("openrouter_key","")
    if not key: return ""
    try:
        import httpx
        r=httpx.post("https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
            json={"model":cfg.get("openrouter_model","meta-llama/llama-3.1-8b-instruct:free"),
                  "messages":[{"role":"system","content":SYS_PROMPT+"\n\n"+ctx},
                              {"role":"user","content":msg}],
                  "max_tokens":600},
            timeout=60)
        if r.status_code==200:
            return r.json().get("choices",[{}])[0].get("message",{}).get("content","")
        else: return f"[OpenRouter {r.status_code}: {r.text[:200]}]"
    except Exception as e: return f"[OpenRouter error: {e}]"

def _anthropic(msg,ctx,cfg):
    if cfg.get("ai_provider")!="anthropic": return ""
    key=cfg.get("anthropic_key","") or os.environ.get("ANTHROPIC_API_KEY","")
    if not key: return ""
    try:
        import anthropic
        c=anthropic.Anthropic(api_key=key)
        r=c.messages.create(model="claude-sonnet-4-20250514",max_tokens=600,
            system=SYS_PROMPT+"\n\n"+ctx,messages=[{"role":"user","content":msg}])
        return r.content[0].text
    except Exception as e: return f"[Anthropic error: {e}]"

def ai_chat(msg,cfg):
    s=gsched(); ctx=build_ctx(s,cfg)
    prov=cfg.get("ai_provider","ollama")
    resp=""
    if prov=="ollama": resp=_ollama(msg,ctx,cfg)
    elif prov=="openrouter": resp=_openrouter(msg,ctx,cfg)
    elif prov=="anthropic": resp=_anthropic(msg,ctx,cfg)
    if not resp:
        # Fallback chain
        for fn in[_ollama,_openrouter,_anthropic]:
            resp=fn(msg,ctx,cfg)
            if resp: break
    if not resp:
        return {"response":"No AI available. Configure a provider in Settings (Ollama, OpenRouter, or Anthropic).","actions":[]}
    clean,actions=process_actions(resp)
    return {"response":clean,"actions":actions}


# ━━━ Reminders ━━━
class Reminders:
    def __init__(self,tts):
        self.tts=tts;self.fired=set();self.last_ci=time.time();self.pending=[];self._lk=threading.Lock()
    def get(self):
        with self._lk: a=list(self.pending);self.pending.clear();return a
    def check(self):
        s=gsched();now=datetime.datetime.now();ts=datetime.date.today().isoformat()
        tasks=today_tasks(s)
        for t in tasks:
            if t["done"]or t["skipped"]:continue
            try:tt=datetime.datetime.strptime(t["time"],"%H:%M").replace(year=now.year,month=now.month,day=now.day)
            except:continue
            for ld in RLEAD:
                rt=tt-datetime.timedelta(minutes=ld);k=f"{t['id']}_{ld}_{ts}"
                if k not in self.fired:
                    d=(now-rt).total_seconds()
                    if 0<=d<30:
                        self.fired.add(k)
                        lb=f"NOW: {t['title']}" if ld==0 else f"In {ld} min: {t['title']}"
                        with self._lk: self.pending.append({"label":lb,"category":t.get("category","custom")})
                        threading.Thread(target=self._fire,args=(t,ld),daemon=True).start()
        iv=s.get("checkin_interval_minutes",90)
        if time.time()-self.last_ci>iv*60:
            self.last_ci=time.time()
            od=sum(1 for t in tasks if not t["done"]and not t["skipped"]and t["time"]<=now.strftime("%H:%M"))
            if od:
                with self._lk:self.pending.append({"label":f"{od} overdue task(s)","category":"checkin"})
                threading.Thread(target=play_tone,args=("checkin",),daemon=True).start()
        if now.hour==0 and now.minute==0:self.fired.clear()
    def _fire(self,t,ld):
        play_tone(t.get("category","custom"))
        if self.tts.available:self.tts.speak_reminder(t,ld)
    def loop(self):
        while True:
            try:self.check()
            except Exception as e:print(f"[Rem err]{e}")
            time.sleep(15)


# ━━━ Flask ━━━
app=Flask(__name__)
tts=None; rem=None

@app.route("/")
def index():
    return send_from_directory(str(BD),"index.html") if (BD/"index.html").exists() else built_in_html()

@app.route("/uploads/<path:fn>")
def uploads(fn):
    return send_from_directory(str(UF),fn)

@app.route("/api/tasks")
def api_tasks():
    return jsonify({"tasks":today_tasks(gsched())})

@app.route("/api/task/done",methods=["POST"])
def api_done():mark(request.json["task_id"],done=True);return jsonify({"ok":1})

@app.route("/api/task/skip",methods=["POST"])
def api_skip():mark(request.json["task_id"],done=False,skipped=True);return jsonify({"ok":1})

@app.route("/api/task/undo",methods=["POST"])
def api_undo():
    d=request.json;ts=datetime.date.today().isoformat();log=ldj(LF,{})
    if ts in log and d["task_id"]in log[ts]:del log[ts][d["task_id"]];svj(LF,log)
    return jsonify({"ok":1})

@app.route("/api/task/note",methods=["POST"])
def api_note():
    d=request.json;ts=datetime.date.today().isoformat();log=ldj(LF,{})
    if ts not in log:log[ts]={}
    if d["task_id"]in log[ts]:log[ts][d["task_id"]]["notes"]=d["notes"]
    else:log[ts][d["task_id"]]={"done":False,"skipped":False,"done_at":datetime.datetime.now().isoformat(),"notes":d["notes"]}
    svj(LF,log);return jsonify({"ok":1})

@app.route("/api/task/add",methods=["POST"])
def api_add():
    d=request.json;s=gsched()
    s["tasks"].append({"time":d["time"],"title":d["title"],"category":d.get("category","custom"),"steps":d.get("steps",[])})
    s["tasks"].sort(key=lambda x:x["time"]);ssched(s);return jsonify({"ok":1})

@app.route("/api/task/remove",methods=["POST"])
def api_remove():
    d=request.json;s=gsched();idx=d.get("index",-1)
    if 0<=idx<len(s["tasks"]):s["tasks"].pop(idx);ssched(s)
    return jsonify({"ok":1})

@app.route("/api/chat",methods=["POST"])
def api_chat_route():
    return jsonify(ai_chat(request.json["message"],gcfg()))

@app.route("/api/alerts")
def api_alerts():
    return jsonify({"alerts":rem.get()if rem else[]})

@app.route("/api/log")
def api_log():
    log=ldj(LF,{});today=datetime.date.today();result={}
    for i in range(30):
        d=(today-datetime.timedelta(days=i)).isoformat()
        if d in log:result[d]=log[d]
    return jsonify({"log":result})

@app.route("/api/events")
def api_events():
    return jsonify({"events":gevents()})

@app.route("/api/events/add",methods=["POST"])
def api_add_event():
    d=request.json;evts=gevents()
    evts.append({"date":d["date"],"time":d.get("time",""),"title":d["title"],"category":d.get("category","appointment"),"notes":d.get("notes","")})
    evts.sort(key=lambda x:x.get("date","")+x.get("time",""));sevents(evts);return jsonify({"ok":1})

@app.route("/api/events/remove",methods=["POST"])
def api_remove_event():
    d=request.json;evts=gevents();idx=d.get("index",-1)
    if 0<=idx<len(evts):evts.pop(idx);sevents(evts)
    return jsonify({"ok":1})

@app.route("/api/profile")
def api_profile():
    return jsonify(gprofile())

@app.route("/api/profile/update",methods=["POST"])
def api_update_profile():
    p=gprofile();d=request.json
    for k in["bio","birthday","favorites","medical_notes"]:
        if k in d:p[k]=d[k]
    sprofile(p);return jsonify(p)

@app.route("/api/profile/photo",methods=["POST"])
def api_upload_photo():
    if "photo" not in request.files: return jsonify({"error":"no file"}),400
    f=request.files["photo"]
    ext=f.filename.rsplit(".",1)[-1].lower() if "." in f.filename else "jpg"
    fn=f"profile.{ext}"; f.save(str(UF/fn))
    p=gprofile();p["photo_path"]=fn;sprofile(p)
    return jsonify({"ok":1,"path":fn})

@app.route("/api/config")
def api_config():
    return jsonify(gcfg())

@app.route("/api/config/save",methods=["POST"])
def api_save_config():
    d=request.json;c=gcfg()
    for k in DEFAULT_CONFIG:
        if k in d:c[k]=d[k]
    scfg(c);return jsonify(c)

@app.route("/api/status")
def api_status():
    cfg=gcfg();has_ollama=False
    try:
        import httpx
        r=httpx.get(cfg.get("ollama_url","http://localhost:11434")+"/api/tags",timeout=2)
        has_ollama=r.status_code==200
    except:pass
    return jsonify({"integrations":{
        "Ollama (local AI)":has_ollama,
        "OpenRouter API":bool(cfg.get("openrouter_key")),
        "Anthropic API":bool(cfg.get("anthropic_key")or os.environ.get("ANTHROPIC_API_KEY")),
        "TTS":tts.available if tts else False,
    },"tts_engine":tts.engine_name if tts else "none","ai_provider":cfg.get("ai_provider","ollama")})

@app.route("/api/test-tts",methods=["POST"])
def api_test_tts():
    if tts and tts.available:tts.speak("Care Agent is ready to help.");return jsonify({"ok":1})
    return jsonify({"ok":0})

@app.route("/api/speak",methods=["POST"])
def api_speak():
    """Speak arbitrary text through TTS (used for reading chat messages aloud)."""
    if tts and tts.available:
        text=request.json.get("text","")
        if text: tts.speak(text)
        return jsonify({"ok":1})
    return jsonify({"ok":0})

@app.route("/api/version")
def api_version():
    return jsonify({"version":APP_VERSION})

@app.route("/api/update/check",methods=["POST"])
def api_update_check():
    """Check for updates from a remote URL."""
    cfg=gcfg()
    url=cfg.get("update_url","") or UPDATE_CHECK_URL
    if not url:
        return jsonify({"available":False,"message":"No update URL configured. Set it in Settings."})
    try:
        import httpx
        # Fetch remote version file
        r=httpx.get(url.rstrip("/")+"/version.json",timeout=10)
        if r.status_code==200:
            remote=r.json()
            remote_ver=remote.get("version","0.0.0")
            if remote_ver>APP_VERSION:
                return jsonify({"available":True,"current":APP_VERSION,
                                "latest":remote_ver,"message":remote.get("changelog","New version available."),
                                "files":remote.get("files",["care_agent_web.py","care_agent_ui.html"])})
            return jsonify({"available":False,"current":APP_VERSION,"latest":remote_ver,
                            "message":"You're up to date!"})
        return jsonify({"available":False,"message":f"Could not reach update server (HTTP {r.status_code})"})
    except Exception as e:
        return jsonify({"available":False,"message":f"Update check failed: {e}"})

@app.route("/api/update/apply",methods=["POST"])
def api_update_apply():
    """Download and apply an update, then AUTO-RESTART the server."""
    cfg=gcfg()
    url=cfg.get("update_url","") or UPDATE_CHECK_URL
    if not url:
        return jsonify({"ok":0,"message":"No update URL configured."})
    try:
        import httpx
        app_dir=Path(__file__).parent
        files_to_update=request.json.get("files",["care_agent_web.py","care_agent_ui.html"])
        updated=[]
        for fn in files_to_update:
            r=httpx.get(url.rstrip("/")+"/"+fn,timeout=30)
            if r.status_code==200:
                target=app_dir/fn
                if target.exists():
                    backup=app_dir/(fn+".bak")
                    shutil.copy2(str(target),str(backup))
                with open(str(target),"w",encoding="utf-8") as f:
                    f.write(r.text)
                updated.append(fn)
        
        if updated:
            message = f"Updated {', '.join(updated)}. Server restarting in 3 seconds..."
            threading.Thread(target=lambda: (time.sleep(3), os.execv(sys.executable, [sys.executable] + sys.argv)), daemon=True).start()
            return jsonify({"ok":1,"updated":updated,"message":message})
        return jsonify({"ok":0,"message":"No files were updated."})
    except Exception as e:
        return jsonify({"ok":0,"message":f"Update failed: {e}"})

@app.route("/api/memory")
def api_memory():
    return jsonify(gmem())

@app.route("/api/affirmation")
def api_affirmation():
    affs=["You're doing an amazing job.","Every small act of care matters deeply.",
          "Take a breath. You've got this.","Your dedication makes a real difference.",
          "Remember to take care of yourself too.","One task at a time. You're enough.",
          "The love you give comes back tenfold.","Progress, not perfection.",
          "You are exactly the caregiver they need.","Today is a new opportunity to shine."]
    return jsonify({"text":random.choice(affs)})


# ━━━ Built-in HTML ━━━
def built_in_html():
    """Serve the HTML from the separate file or fall back to a redirect."""
    html_path = Path(__file__).parent / "care_agent_ui.html"
    if html_path.exists():
        return send_file(str(html_path))
    return "<h1>UI file not found</h1><p>Place care_agent_ui.html next to care_agent_web.py</p>", 404


# ━━━ Main ━━━
def main():
    global tts,rem
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=5000)
    parser.add_argument("--host",default="0.0.0.0")
    parser.add_argument("--no-open",action="store_true")
    args=parser.parse_args()

    ensure_dirs(); cfg=gcfg(); scfg(cfg); gsched()

    tts=TTS(cfg)
    print(f"TTS: {tts.engine_name} ({'ok' if tts.available else 'unavailable'})")
    if not tts.available:
        print("  For best voice: pip install edge-tts")
        print("  Quick fallback: sudo dnf install espeak-ng")

    rem=Reminders(tts)
    threading.Thread(target=rem.loop,daemon=True).start()
    print("Reminders: running")

    if not args.no_open:
        threading.Timer(1.5,lambda:webbrowser.open(f"http://localhost:{args.port}")).start()

    print(f"\n\u2764\ufe0f  Care Agent v3 at http://0.0.0.0:{args.port}\n")
    app.run(host=args.host,port=args.port,debug=False,use_reloader=False)

if __name__=="__main__": main()
