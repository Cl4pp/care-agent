#!/usr/bin/env python3
"""
Care Agent v4.0 -- Standalone Desktop Edition
Runs as a native desktop app (pywebview) or web server (Flask).

Desktop mode:  python3 care_agent_web.py
Server mode:   python3 care_agent_web.py --server --port 8080 --no-open
"""

import json, os, sys, time, math, wave, struct, shutil, tempfile, base64
import subprocess, datetime, threading, random, argparse, webbrowser, re
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory

# --- Optional enhanced dependencies (graceful fallback if not installed) ---
try:
    from pydantic import BaseModel, Field
    from typing import List, Optional
    PYDANTIC_OK = True
except ImportError:
    PYDANTIC_OK = False

try:
    import instructor
    INSTRUCTOR_OK = True
except ImportError:
    INSTRUCTOR_OK = False

try:
    import chromadb
    CHROMA_OK = True
except ImportError:
    CHROMA_OK = False

try:
    from faster_whisper import WhisperModel
    _whisper_model = None
    WHISPER_OK = True
except ImportError:
    WHISPER_OK = False
    _whisper_model = None

# --- Resolve bundled file paths (works with PyInstaller and normal Python) ---
if getattr(sys, 'frozen', False):
    # Running as PyInstaller bundle
    BUNDLE_DIR = Path(sys._MEIPASS)
    APP_DIR = Path(sys.executable).parent
else:
    # Running as normal Python script
    BUNDLE_DIR = Path(__file__).parent
    APP_DIR = Path(__file__).parent

# --- Paths ---
BD = Path.home() / ".care-agent"
CF = BD / "config.json"
SF = BD / "schedule.json"
LF = BD / "care_log.json"
MF = BD / "memory.json"
EF = BD / "events.json"
PF = BD / "profile.json"
UF = BD / "uploads"

TONES = {
    "meal":        {"freq": 523, "pattern": "long",   "repeats": 2, "icon": "\U0001f37d\ufe0f", "label": "Meal",        "color": "#d97706"},
    "bathroom":    {"freq": 659, "pattern": "short",  "repeats": 3, "icon": "\U0001f6bb",        "label": "Bathroom",    "color": "#2563eb"},
    "medication":  {"freq": 784, "pattern": "urgent", "repeats": 4, "icon": "\U0001f48a",        "label": "Medication",  "color": "#dc2626"},
    "activity":    {"freq": 440, "pattern": "gentle", "repeats": 1, "icon": "\U0001f3af",        "label": "Activity",    "color": "#059669"},
    "sleep":       {"freq": 349, "pattern": "gentle", "repeats": 1, "icon": "\U0001f634",        "label": "Sleep",       "color": "#4f46e5"},
    "hydration":   {"freq": 587, "pattern": "short",  "repeats": 2, "icon": "\U0001f4a7",        "label": "Hydration",   "color": "#0891b2"},
    "custom":      {"freq": 698, "pattern": "long",   "repeats": 2, "icon": "\U0001f4cb",        "label": "Task",        "color": "#7c3aed"},
    "appointment": {"freq": 550, "pattern": "long",   "repeats": 3, "icon": "\U0001f4c5",        "label": "Appointment", "color": "#be185d"},
    "checkin":     {"freq": 466, "pattern": "gentle", "repeats": 2, "icon": "\U0001f4ac",        "label": "Check-in",    "color": "#db2777"},
}
RLEAD = [10, 5, 0]

DEFAULT_SCHEDULE = {"name": "Care Recipient", "tasks": [
    {"time": "07:00", "category": "bathroom",   "title": "Morning diaper / bathroom",          "steps": ["Check diaper / assist to bathroom", "Clean and change if needed", "Wash hands", "Apply barrier cream if needed"]},
    {"time": "07:30", "category": "medication", "title": "Morning medication",                  "steps": ["Prepare prescribed medication", "Give with water/food as directed", "Log that medication was given"]},
    {"time": "08:00", "category": "meal",       "title": "Breakfast",                           "steps": ["Prepare balanced breakfast", "Assist with eating if needed", "Offer water/juice", "Clean up"]},
    {"time": "09:30", "category": "bathroom",   "title": "Mid-morning bathroom check",          "steps": ["Check diaper / offer bathroom", "Change if needed"]},
    {"time": "10:00", "category": "hydration",  "title": "Hydration check",                    "steps": ["Offer water or preferred drink", "Ensure at least 4 oz consumed"]},
    {"time": "10:30", "category": "activity",   "title": "Morning activity",                    "steps": ["Engage in preferred activity", "Encourage movement and interaction"]},
    {"time": "12:00", "category": "bathroom",   "title": "Pre-lunch bathroom",                  "steps": ["Check diaper / assist to bathroom", "Wash hands"]},
    {"time": "12:15", "category": "meal",       "title": "Lunch",                               "steps": ["Prepare lunch", "Assist with eating if needed", "Offer drink", "Clean up"]},
    {"time": "13:00", "category": "medication", "title": "Afternoon medication (if applicable)","steps": ["Check if afternoon dose is scheduled", "Administer if needed"]},
    {"time": "14:00", "category": "bathroom",   "title": "Afternoon bathroom check",            "steps": ["Check diaper / offer bathroom", "Change if needed"]},
    {"time": "14:30", "category": "hydration",  "title": "Afternoon hydration",                "steps": ["Offer water or preferred drink"]},
    {"time": "15:00", "category": "activity",   "title": "Afternoon activity / therapy",        "steps": ["Engage in scheduled therapy or activity", "Take notes on progress if applicable"]},
    {"time": "16:30", "category": "bathroom",   "title": "Pre-dinner bathroom check",           "steps": ["Check diaper / offer bathroom"]},
    {"time": "17:00", "category": "meal",       "title": "Dinner",                              "steps": ["Prepare dinner", "Assist with eating", "Offer drink", "Clean up"]},
    {"time": "18:00", "category": "medication", "title": "Evening medication (if applicable)",  "steps": ["Check if evening dose is scheduled", "Administer if needed"]},
    {"time": "19:00", "category": "bathroom",   "title": "Evening bathroom / diaper change",    "steps": ["Full diaper change or bathroom assist", "Evening hygiene routine", "Apply barrier cream"]},
    {"time": "19:30", "category": "activity",   "title": "Wind-down activity",                  "steps": ["Calm activity (reading, gentle music, etc.)", "Begin bedtime transition"]},
    {"time": "20:00", "category": "sleep",      "title": "Bedtime routine",                     "steps": ["Change into pajamas", "Brush teeth", "Final bathroom check", "Settle into bed", "Goodnight!"]},
    {"time": "22:00", "category": "bathroom",   "title": "Late-night diaper check",             "steps": ["Check diaper without fully waking if possible", "Change if needed"]},
], "checkin_interval_minutes": 90}

APP_VERSION = "4.0.0"
UPDATE_CHECK_URL = "https://raw.githubusercontent.com/Cl4pp/care-agent/main"

DEFAULT_CONFIG = {
    "caregiver_name": "", "recipient_name": "Care Recipient",
    "theme": "auto", "accent_color": "#6366f1",
    "ai_provider": "ollama", "ollama_model": "llama3.2", "ollama_url": "http://localhost:11434",
    "openrouter_key": "", "openrouter_model": "meta-llama/llama-3.1-8b-instruct:free",
    "anthropic_key": "",
    "tts_engine": "auto",
    "daily_affirmation": True,
    "greeting_message": "",
    "auto_read_chat": True,
    "update_url": UPDATE_CHECK_URL,
}

# --- Data layer ---
def ensure_dirs():
    for d in [BD, BD / "piper-voices", UF]:
        d.mkdir(parents=True, exist_ok=True)

def ldj(p, dflt=None):
    if dflt is None:
        dflt = {}
    try:
        if p.exists():
            with open(p) as f:
                return json.load(f)
    except Exception:
        pass
    return dflt

def svj(p, d):
    with open(p, "w") as f:
        json.dump(d, f, indent=2, default=str)

def gcfg():
    c = ldj(CF, dict(DEFAULT_CONFIG))
    for k, v in DEFAULT_CONFIG.items():
        if k not in c:
            c[k] = v
    return c

def scfg(c):
    svj(CF, c)

def gsched():
    d = ldj(SF)
    if not d or "tasks" not in d:
        svj(SF, DEFAULT_SCHEDULE)
        return dict(DEFAULT_SCHEDULE)
    return d

def ssched(d):
    svj(SF, d)

def gmem():
    return ldj(MF, {"notes": [], "preferences": {}})

def smem(m):
    svj(MF, m)

def add_mem(note):
    m = gmem()
    m["notes"].append({"text": note, "time": datetime.datetime.now().isoformat()})
    if len(m["notes"]) > 300:
        m["notes"] = m["notes"][-300:]
    smem(m)
    # Also persist to ChromaDB for semantic search
    chroma_add(note, {"source": "memory"})

# --- ChromaDB Semantic Memory ---
_chroma_col = None
_chroma_lock = threading.Lock()

def _init_chroma():
    global _chroma_col
    if not CHROMA_OK:
        return False
    try:
        chroma_dir = str(BD / "chroma")
        client = chromadb.PersistentClient(path=chroma_dir)
        _chroma_col = client.get_or_create_collection(
            name="care_memory",
            metadata={"hnsw:space": "cosine"}
        )
        print("[ChromaDB] Semantic memory ready (", _chroma_col.count(), "entries)")
        return True
    except Exception as e:
        print(f"[ChromaDB init error] {e}")
        return False

def chroma_add(text, metadata=None):
    global _chroma_col
    if not CHROMA_OK:
        return
    with _chroma_lock:
        try:
            if _chroma_col is None:
                _init_chroma()
            if _chroma_col is None:
                return
            import uuid
            meta = dict(metadata or {})
            meta["timestamp"] = datetime.datetime.now().isoformat()
            _chroma_col.add(documents=[text], ids=[str(uuid.uuid4())], metadatas=[meta])
        except Exception as e:
            print(f"[ChromaDB add error] {e}")

def chroma_search(query, n=5):
    global _chroma_col
    if not CHROMA_OK:
        return []
    with _chroma_lock:
        try:
            if _chroma_col is None:
                _init_chroma()
            if _chroma_col is None:
                return []
            count = _chroma_col.count()
            if count == 0:
                return []
            results = _chroma_col.query(
                query_texts=[query],
                n_results=min(n, count)
            )
            return results.get("documents", [[]])[0]
        except Exception as e:
            print(f"[ChromaDB search error] {e}")
            return []


def gevents():

    return ldj(EF, {"events": []}).get("events", [])

def sevents(evts):
    svj(EF, {"events": evts})

def gprofile():
    return ldj(PF, {"photo_path": "", "bio": "", "birthday": "", "favorites": "", "medical_notes": "", "recipient_name": ""})

def sprofile(p):
    svj(PF, p)

def fmt12(t24):
    try:
        h, m = map(int, t24.split(":"))
        ap = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {ap}"
    except Exception:
        return t24

def today_tasks(sched):
    ts = datetime.date.today().isoformat()
    log = ldj(LF, {})
    tl = log.get(ts, {})
    tasks = []
    for i, task in enumerate(sched.get("tasks", [])):
        t = dict(task)
        t["id"] = f"task_{i}"
        t["index"] = i
        t["done"] = tl.get(t["id"], {}).get("done", False)
        t["done_at"] = tl.get(t["id"], {}).get("done_at")
        t["skipped"] = tl.get(t["id"], {}).get("skipped", False)
        t["notes"] = tl.get(t["id"], {}).get("notes", "")
        pr = TONES.get(t.get("category", "custom"), TONES["custom"])
        t["icon"] = pr["icon"]
        t["color"] = pr["color"]
        t["category_label"] = pr["label"]
        t["time12"] = fmt12(t["time"])
        tasks.append(t)
    tasks.sort(key=lambda x: x["time"])
    return tasks

def mark(tid, done=True, skipped=False, notes=""):
    ts = datetime.date.today().isoformat()
    log = ldj(LF, {})
    if ts not in log:
        log[ts] = {}
    log[ts][tid] = {"done": done, "skipped": skipped, "done_at": datetime.datetime.now().isoformat(), "notes": notes}
    svj(LF, log)


# --- Audio ---
def _genwav(freq, ms, vol=0.6):
    sr = 44100
    n = int(sr * ms / 1000)
    fade = min(500, n // 4)
    samps = []
    for i in range(n):
        v = vol * math.sin(2 * math.pi * freq * i / sr)
        if i < fade:
            v *= i / fade
        elif i > n - fade:
            v *= (n - i) / fade
        samps.append(int(v * 32767))
    buf = struct.pack(f"<{len(samps)}h", *samps)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        with wave.open(f, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(buf)
        return f.name

def _playf(path):
    """Play audio file cross-platform: Windows + Linux."""
    if sys.platform == "win32":
        ext = Path(path).suffix.lower()
        try:
            if ext == ".wav":
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME)
                return
            else:
                # Use PowerShell to play MP3/other formats on Windows
                ps_cmd = (
                    f"(New-Object Media.SoundPlayer).SoundLocation = '{path}'; "
                    if ext == ".wav" else
                    f"Add-Type -AssemblyName presentationCore; "
                    f"$player = New-Object System.Windows.Media.MediaPlayer; "
                    f"$player.Open([System.Uri]'{path}'); "
                    f"$player.Play(); "
                    f"Start-Sleep -s 5; "
                    f"$player.Stop()"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15
                )
                return
        except Exception as e:
            print(f"[TTS win playback error] {e}")
            try:
                os.startfile(path)  # last resort: open with default player
                time.sleep(3)
            except Exception:
                pass
        return
    # Linux fallback
    for p in ["paplay", "aplay", "ffplay -nodisp -autoexit"]:
        try:
            subprocess.run(p.split() + [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            return
        except Exception:
            continue

def play_tone(cat):
    pr = TONES.get(cat, TONES["custom"])
    pats = {"long": [500], "short": [150, 100, 150], "urgent": [200, 80, 200, 80, 400], "gentle": [300]}
    for _ in range(pr["repeats"]):
        for d in pats.get(pr["pattern"], [300]):
            w = _genwav(pr["freq"], d)
            _playf(w)
            try:
                os.unlink(w)
            except Exception:
                pass
            time.sleep(0.08)
        time.sleep(0.25)


# --- TTS: edge-tts -> Piper -> espeak ---
class TTS:
    def __init__(self, cfg):
        self.engine = None
        self.engine_name = "none"
        pref = cfg.get("tts_engine", "auto")
        if pref in ("auto", "edge-tts"):
            try:
                import importlib
                if importlib.util.find_spec("edge_tts"):
                    self.engine = ("edge-tts",)
                    self.engine_name = "edge-tts (neural)"
                    return
            except Exception:
                pass
        if pref in ("auto", "piper"):
            pb = shutil.which("piper")
            vd = BD / "piper-voices"
            model = None
            if vd.exists():
                for f in vd.glob("*.onnx"):
                    model = str(f)
                    break
            if pb and model:
                self.engine = ("piper", pb, model)
                self.engine_name = "piper"
                return
        if pref in ("auto", "espeak"):
            for cmd in ["espeak-ng", "espeak"]:
                if shutil.which(cmd):
                    self.engine = ("espeak", cmd)
                    self.engine_name = cmd
                    return

    @property
    def available(self):
        return self.engine is not None

    def speak(self, text):
        if not self.engine:
            return
        threading.Thread(target=self._do, args=(text,), daemon=True).start()

    def _do(self, text):
        try:
            if self.engine[0] == "edge-tts":
                import asyncio
                import edge_tts
                async def _run():
                    c = edge_tts.Communicate(text, "en-US-JennyNeural")
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                        out = f.name
                    await c.save(out)
                    _playf(out)
                    try:
                        os.unlink(out)
                    except Exception:
                        pass
                asyncio.run(_run())
            elif self.engine[0] == "piper":
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    out = f.name
                subprocess.run(
                    [self.engine[1], "--model", self.engine[2], "--output_file", out],
                    input=text.encode(), capture_output=True, timeout=30
                )
                if os.path.getsize(out) > 0:
                    _playf(out)
                try:
                    os.unlink(out)
                except Exception:
                    pass
            elif self.engine[0] == "espeak":
                subprocess.run([self.engine[1], text], capture_output=True, timeout=15)
        except Exception as e:
            print(f"[TTS err] {e}")

    def speak_reminder(self, task, lead):
        t = task["title"]
        if lead == 0:
            self.speak(f"Time for: {t}.")
        elif lead == 5:
            self.speak(f"{t} in 5 minutes.")
        else:
            self.speak(f"{t} coming up in {lead} minutes.")


# --- Reminders ---
class Reminders:
    def __init__(self, tts):
        self.tts = tts
        self.fired = set()
        self.last_ci = time.time()
        self.pending = []
        self._lk = threading.Lock()

    def get(self):
        with self._lk:
            a = list(self.pending)
            self.pending.clear()
            return a

    def check(self):
        s = gsched()
        now = datetime.datetime.now()
        ts = datetime.date.today().isoformat()
        tasks = today_tasks(s)
        for t in tasks:
            if t["done"] or t["skipped"]:
                continue
            try:
                tt = datetime.datetime.strptime(t["time"], "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )
            except Exception:
                continue
            for ld in RLEAD:
                rt = tt - datetime.timedelta(minutes=ld)
                k = f"{t['id']}_{ld}_{ts}"
                if k not in self.fired:
                    d = (now - rt).total_seconds()
                    if 0 <= d < 30:
                        self.fired.add(k)
                        lb = f"NOW: {t['title']}" if ld == 0 else f"In {ld} min: {t['title']}"
                        with self._lk:
                            self.pending.append({"label": lb, "category": t.get("category", "custom")})
                        threading.Thread(target=self._fire, args=(t, ld), daemon=True).start()
        iv = s.get("checkin_interval_minutes", 90)
        if time.time() - self.last_ci > iv * 60:
            self.last_ci = time.time()
            od = sum(1 for t in tasks if not t["done"] and not t["skipped"] and t["time"] <= now.strftime("%H:%M"))
            if od:
                with self._lk:
                    self.pending.append({"label": f"{od} overdue task(s)", "category": "checkin"})
                threading.Thread(target=play_tone, args=("checkin",), daemon=True).start()
        if now.hour == 0 and now.minute == 0:
            self.fired.clear()

    def _fire(self, t, ld):
        play_tone(t.get("category", "custom"))
        if self.tts.available:
            self.tts.speak_reminder(t, ld)

    def loop(self):
        while True:
            try:
                self.check()
            except Exception as e:
                print(f"[Rem err] {e}")
            time.sleep(15)


# --- Pydantic Models for Structured AI Output ---
if PYDANTIC_OK:
    class CareTask(BaseModel):
        time: str
        title: str
        category: str = "custom"
        steps: List[str] = Field(default_factory=list)

    class CareSchedule(BaseModel):
        tasks: List[CareTask]
        notes: Optional[str] = None

    class AIResponse(BaseModel):
        message: str
        action: Optional[str] = None
        task_time: Optional[str] = None
        task_title: Optional[str] = None
        task_category: Optional[str] = None
        task_steps: Optional[List[str]] = None
        title_match: Optional[str] = None
        memory_note: Optional[str] = None
        event_date: Optional[str] = None
        event_time_val: Optional[str] = None
        event_title: Optional[str] = None


# --- AI Chat with tools ---

SYS_PROMPT = """You are a kind, practical care assistant. The caregiver has ADHD -- be concise, warm, action-focused. 1-4 sentences.

You can MODIFY the schedule by including JSON blocks. Use this exact format in your response:

To add a task:
```json
{"action":"add_task","time":"HH:MM","title":"Task name","category":"meal|bathroom|medication|activity|sleep|hydration|custom|appointment","steps":["step1"]}
```
To remove a task (by partial title match):
```json
{"action":"remove_task","title_match":"partial title"}
```
To save a memory note:
```json
{"action":"save_memory","note":"What to remember forever"}
```
To add a calendar event:
```json
{"action":"add_event","date":"YYYY-MM-DD","time":"HH:MM","title":"Event name","category":"appointment"}
```
Always confirm what you did in plain language. Be encouraging."""

def build_ctx(sched, cfg):
    now = datetime.datetime.now()
    tasks = today_tasks(sched)
    mem = gmem()
    events = gevents()
    prof = gprofile()
    lines = [
        f"Time: {now.strftime('%I:%M %p, %A %B %d')}",
        f"Caregiver: {cfg.get('caregiver_name', '(not set)')}",
        f"Recipient: {prof.get('recipient_name', 'Care Recipient')}",
        "",
        "Schedule:",
    ]
    for t in tasks:
        s = "DONE" if t["done"] else ("SKIP" if t["skipped"] else ("OVERDUE" if t["time"] <= now.strftime("%H:%M") else "pending"))
        lines.append(f"  [{s}] {t['time12']} -- {t['title']} ({t['category']})")
    # Use ChromaDB semantic search if available, else fall back to recent JSON notes
    now_context = f"{now.strftime('%A')} {now.strftime('%I:%M %p')} care schedule"
    chroma_results = chroma_search(now_context, n=8)
    if chroma_results:
        lines.append("\nRelevant memories (semantic):")
        for doc in chroma_results:
            lines.append(f"  - {doc}")
    elif mem.get("notes"):
        lines.append("\nMemory:")
        for n in mem["notes"][-20:]:
            lines.append(f"  - {n['text']}")
    upcoming_events = [e for e in events if e.get("date", "") >= now.strftime("%Y-%m-%d")][:5]
    if upcoming_events:
        lines.append("\nUpcoming events:")
        for e in upcoming_events:
            lines.append(f"  - {e['date']} {e.get('time', '')} -- {e['title']}")
    return "\n".join(lines)

def process_actions(text):
    actions = []
    for m in re.findall(r'```json\s*(\{[^`]+\})\s*```', text, re.DOTALL):
        try:
            a = json.loads(m)
            act = a.get("action")
            if act == "add_task":
                s = gsched()
                s["tasks"].append({"time": a["time"], "title": a["title"], "category": a.get("category", "custom"), "steps": a.get("steps", [])})
                s["tasks"].sort(key=lambda x: x["time"])
                ssched(s)
                actions.append(f"Added: {fmt12(a['time'])} -- {a['title']}")
            elif act == "remove_task":
                s = gsched()
                mt = a["title_match"].lower()
                before = len(s["tasks"])
                s["tasks"] = [t for t in s["tasks"] if mt not in t["title"].lower()]
                ssched(s)
                actions.append(f"Removed {before - len(s['tasks'])} task(s)")
            elif act == "save_memory":
                add_mem(a["note"])
                actions.append(f"Remembered: {a['note']}")
            elif act == "add_event":
                evts = gevents()
                evts.append({"date": a["date"], "time": a.get("time", ""), "title": a["title"], "category": a.get("category", "appointment")})
                evts.sort(key=lambda x: x.get("date", "") + x.get("time", ""))
                sevents(evts)
                actions.append(f"Event added: {a['date']} -- {a['title']}")
        except Exception:
            pass
    clean = re.sub(r'```json\s*\{[^`]+\}\s*```', '', text, flags=re.DOTALL).strip()
    return clean, actions

def _ollama(msg, ctx, cfg):
    if cfg.get("ai_provider") != "ollama":
        return ""
    try:
        import httpx
        r = httpx.post(
            cfg.get("ollama_url", "http://localhost:11434") + "/api/chat",
            json={
                "model": cfg.get("ollama_model", "llama3.2"),
                "stream": False,
                "messages": [{"role": "system", "content": SYS_PROMPT + "\n\n" + ctx}, {"role": "user", "content": msg}],
                "options": {"num_predict": 600},
            },
            timeout=120,
        )
        if r.status_code == 200:
            return r.json().get("message", {}).get("content", "")
    except Exception as e:
        return f"[Ollama error: {e}]"
    return ""

def _openrouter(msg, ctx, cfg):
    if cfg.get("ai_provider") != "openrouter":
        return ""
    key = cfg.get("openrouter_key", "")
    if not key:
        return ""
    try:
        import httpx
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": cfg.get("openrouter_model", "meta-llama/llama-3.1-8b-instruct:free"),
                "messages": [{"role": "system", "content": SYS_PROMPT + "\n\n" + ctx}, {"role": "user", "content": msg}],
                "max_tokens": 600,
            },
            timeout=60,
        )
        if r.status_code == 200:
            return r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        else:
            return f"[OpenRouter {r.status_code}: {r.text[:200]}]"
    except Exception as e:
        return f"[OpenRouter error: {e}]"

def _anthropic_ai(msg, ctx, cfg):
    if cfg.get("ai_provider") != "anthropic":
        return ""
    key = cfg.get("anthropic_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return ""
    try:
        import anthropic
        c = anthropic.Anthropic(api_key=key)
        r = c.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=600,
            system=SYS_PROMPT + "\n\n" + ctx,
            messages=[{"role": "user", "content": msg}],
        )
        return r.content[0].text
    except Exception as e:
        return f"[Anthropic error: {e}]"

def ai_chat(msg, cfg):
    s = gsched()
    ctx = build_ctx(s, cfg)
    prov = cfg.get("ai_provider", "ollama")
    resp = ""
    if prov == "ollama":
        resp = _ollama(msg, ctx, cfg)
    elif prov == "openrouter":
        resp = _openrouter(msg, ctx, cfg)
    elif prov == "anthropic":
        resp = _anthropic_ai(msg, ctx, cfg)
    if not resp:
        for fn in [_ollama, _openrouter, _anthropic_ai]:
            resp = fn(msg, ctx, cfg)
            if resp:
                break
    if not resp:
        return {"response": "No AI available. Configure a provider in Settings (Ollama, OpenRouter, or Anthropic).", "actions": []}
    clean, actions = process_actions(resp)
    return {"response": clean, "actions": actions}


# --- faster-whisper Speech-to-Text ---
def _load_whisper():
    global _whisper_model
    if not WHISPER_OK or _whisper_model is not None:
        return _whisper_model
    try:
        model_dir = str(BD / "whisper-models")
        (BD / "whisper-models").mkdir(parents=True, exist_ok=True)
        print("[Whisper] Loading tiny model (first run downloads ~150MB)...")
        _whisper_model = WhisperModel("tiny", device="cpu", download_root=model_dir)
        print("[Whisper] Model ready")
        return _whisper_model
    except Exception as e:
        print(f"[Whisper load error] {e}")
        return None

def transcribe_audio(audio_bytes, ext="wav"):
    """Transcribe audio bytes using faster-whisper. Returns text or empty string."""
    if not WHISPER_OK:
        return ""
    model = _load_whisper()
    if model is None:
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        segments, _ = model.transcribe(tmp_path, beam_size=5, language="en")
        text = " ".join(s.text.strip() for s in segments).strip()
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return text
    except Exception as e:
        print(f"[Whisper transcribe error] {e}")
        return ""


# --- Structured AI with Instructor (enhanced onboarding) ---
def ai_onboard_structured(description, recipient_name, cfg):
    """Use instructor to generate a validated CareSchedule from plain text description."""
    if not PYDANTIC_OK or not INSTRUCTOR_OK:
        return None
    key = cfg.get("anthropic_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return None
    try:
        import anthropic as _anthropic
        client = instructor.from_anthropic(_anthropic.Anthropic(api_key=key))
        prompt = (
            f"Create a complete, realistic daily care schedule for {recipient_name}. "
            f"Caregiver description: {description}. "
            "Include all necessary daily care tasks: bathroom/hygiene checks (every 2-3 hours), "
            "meals (breakfast, lunch, dinner), medications (morning/evening), "
            "hydration checks, activities/therapy, and bedtime routine. "
            "Use 24-hour HH:MM time format. Be specific and realistic."
        )
        schedule = client.chat.completions.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=2000,
            response_model=CareSchedule,
            messages=[{"role": "user", "content": prompt}]
        )
        return schedule
    except Exception as e:
        print(f"[Instructor onboard error] {e}")
        return None


# --- Flask app ---

app = Flask(__name__, static_folder=None)
tts = None
rem = None


@app.route("/")
def index():
    return send_from_directory(str(BUNDLE_DIR), "care_agent_ui.html")

@app.route("/uploads/<path:fn>")
def uploads(fn):
    return send_from_directory(str(UF), fn)

@app.route("/manifest.json")
def manifest():
    return send_from_directory(str(BUNDLE_DIR), "manifest.json")

@app.route("/sw.js")
def sw():
    return send_from_directory(str(BUNDLE_DIR), "sw.js", mimetype="application/javascript")

@app.route("/icon-192.png")
def icon192():
    p = BUNDLE_DIR / "icon-192.png"
    if p.exists():
        return send_from_directory(str(BUNDLE_DIR), "icon-192.png")
    return "", 204

@app.route("/icon-512.png")
def icon512():
    p = BUNDLE_DIR / "icon-512.png"
    if p.exists():
        return send_from_directory(str(BUNDLE_DIR), "icon-512.png")
    return "", 204

@app.route("/api/tasks")
def api_tasks():
    return jsonify({"tasks": today_tasks(gsched())})

@app.route("/api/task/done", methods=["POST"])
def api_done():
    mark(request.json["task_id"], done=True)
    return jsonify({"ok": 1})

@app.route("/api/task/skip", methods=["POST"])
def api_skip():
    mark(request.json["task_id"], done=False, skipped=True)
    return jsonify({"ok": 1})

@app.route("/api/task/undo", methods=["POST"])
def api_undo():
    d = request.json
    ts = datetime.date.today().isoformat()
    log = ldj(LF, {})
    if ts in log and d["task_id"] in log[ts]:
        del log[ts][d["task_id"]]
        svj(LF, log)
    return jsonify({"ok": 1})

@app.route("/api/task/note", methods=["POST"])
def api_note():
    d = request.json
    ts = datetime.date.today().isoformat()
    log = ldj(LF, {})
    if ts not in log:
        log[ts] = {}
    if d["task_id"] in log[ts]:
        log[ts][d["task_id"]]["notes"] = d["notes"]
    else:
        log[ts][d["task_id"]] = {"done": False, "skipped": False, "done_at": datetime.datetime.now().isoformat(), "notes": d["notes"]}
    svj(LF, log)
    return jsonify({"ok": 1})

@app.route("/api/task/add", methods=["POST"])
def api_add():
    d = request.json
    s = gsched()
    s["tasks"].append({"time": d["time"], "title": d["title"], "category": d.get("category", "custom"), "steps": d.get("steps", [])})
    s["tasks"].sort(key=lambda x: x["time"])
    ssched(s)
    return jsonify({"ok": 1})

@app.route("/api/task/remove", methods=["POST"])
def api_remove():
    d = request.json
    s = gsched()
    idx = d.get("index", -1)
    if 0 <= idx < len(s["tasks"]):
        s["tasks"].pop(idx)
        ssched(s)
    return jsonify({"ok": 1})

@app.route("/api/chat", methods=["POST"])
def api_chat_route():
    return jsonify(ai_chat(request.json["message"], gcfg()))

@app.route("/api/alerts")
def api_alerts():
    return jsonify({"alerts": rem.get() if rem else []})

@app.route("/api/log")
def api_log():
    log = ldj(LF, {})
    today = datetime.date.today()
    result = {}
    for i in range(30):
        d = (today - datetime.timedelta(days=i)).isoformat()
        if d in log:
            result[d] = log[d]
    return jsonify({"log": result})

@app.route("/api/events")
def api_events():
    return jsonify({"events": gevents()})

@app.route("/api/events/add", methods=["POST"])
def api_add_event():
    d = request.json
    evts = gevents()
    evts.append({"date": d["date"], "time": d.get("time", ""), "title": d["title"], "category": d.get("category", "appointment"), "notes": d.get("notes", "")})
    evts.sort(key=lambda x: x.get("date", "") + x.get("time", ""))
    sevents(evts)
    return jsonify({"ok": 1})

@app.route("/api/events/remove", methods=["POST"])
def api_remove_event():
    d = request.json
    evts = gevents()
    idx = d.get("index", -1)
    if 0 <= idx < len(evts):
        evts.pop(idx)
        sevents(evts)
    return jsonify({"ok": 1})

@app.route("/api/profile")
def api_profile():
    return jsonify(gprofile())

@app.route("/api/profile/update", methods=["POST"])
def api_update_profile():
    p = gprofile()
    d = request.json
    for k in ["bio", "birthday", "favorites", "medical_notes", "recipient_name"]:
        if k in d:
            p[k] = d[k]
    sprofile(p)
    return jsonify(p)

@app.route("/api/profile/photo", methods=["POST"])
def api_upload_photo():
    if "photo" not in request.files:
        return jsonify({"error": "no file"}), 400
    f = request.files["photo"]
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "jpg"
    fn = f"profile.{ext}"
    f.save(str(UF / fn))
    p = gprofile()
    p["photo_path"] = fn
    sprofile(p)
    return jsonify({"ok": 1, "path": fn})

@app.route("/api/config")
def api_config():
    return jsonify(gcfg())

@app.route("/api/config/save", methods=["POST"])
def api_save_config():
    d = request.json
    c = gcfg()
    for k in DEFAULT_CONFIG:
        if k in d:
            c[k] = d[k]
    scfg(c)
    return jsonify(c)

@app.route("/api/status")
def api_status():
    cfg = gcfg()
    has_ollama = False
    try:
        import httpx
        r = httpx.get(cfg.get("ollama_url", "http://localhost:11434") + "/api/tags", timeout=2)
        has_ollama = r.status_code == 200
    except Exception:
        pass
    return jsonify({
        "integrations": {
            "Ollama (local AI)": has_ollama,
            "OpenRouter API": bool(cfg.get("openrouter_key")),
            "Anthropic API": bool(cfg.get("anthropic_key") or os.environ.get("ANTHROPIC_API_KEY")),
            "TTS": tts.available if tts else False,
        },
        "tts_engine": tts.engine_name if tts else "none",
        "ai_provider": cfg.get("ai_provider", "ollama"),
    })

@app.route("/api/test-tts", methods=["POST"])
def api_test_tts():
    if tts and tts.available:
        tts.speak("Care Agent is ready to help.")
        return jsonify({"ok": 1})
    return jsonify({"ok": 0})

@app.route("/api/speak", methods=["POST"])
def api_speak():
    if tts and tts.available:
        text = request.json.get("text", "")
        if text:
            tts.speak(text)
        return jsonify({"ok": 1})
    return jsonify({"ok": 0})

@app.route("/api/version")
def api_version():
    return jsonify({"version": APP_VERSION})

@app.route("/api/update/check", methods=["POST"])
def api_update_check():
    cfg = gcfg()
    url = cfg.get("update_url", "") or UPDATE_CHECK_URL
    if not url:
        return jsonify({"available": False, "message": "No update URL configured. Set it in Settings."})
    try:
        import httpx
        r = httpx.get(url.rstrip("/") + "/version.json", timeout=10)
        if r.status_code == 200:
            try:
                remote = r.json()
            except Exception:
                return jsonify({"available": False, "current": APP_VERSION, "message": "You have the latest version!"})
            remote_ver = remote.get("version", "0.0.0")
            if remote_ver > APP_VERSION:
                return jsonify({
                    "available": True,
                    "current": APP_VERSION,
                    "latest": remote_ver,
                    "message": remote.get("changelog", "New version available."),
                    "files": remote.get("files", ["care_agent_web.py", "care_agent_ui.html"]),
                })
            return jsonify({"available": False, "current": APP_VERSION, "latest": remote_ver, "message": "✅ You have the latest version!"})
        return jsonify({"available": False, "current": APP_VERSION, "message": "✅ You have the latest version!"})
    except Exception as e:
        return jsonify({"available": False, "current": APP_VERSION, "message": "✅ You have the latest version!"})

@app.route("/api/update/apply", methods=["POST"])
def api_update_apply():
    cfg = gcfg()
    url = cfg.get("update_url", "") or UPDATE_CHECK_URL
    if not url:
        return jsonify({"ok": 0, "message": "No update URL configured."})
    try:
        import httpx
        app_dir = Path(__file__).parent
        files_to_update = request.json.get("files", ["care_agent_web.py", "care_agent_ui.html"])
        updated = []
        for fn in files_to_update:
            r = httpx.get(url.rstrip("/") + "/" + fn, timeout=30)
            if r.status_code == 200:
                target = app_dir / fn
                if target.exists():
                    backup = app_dir / (fn + ".bak")
                    shutil.copy2(str(target), str(backup))
                with open(str(target), "w", encoding="utf-8") as f:
                    f.write(r.text)
                updated.append(fn)
        if updated:
            message = f"Updated {', '.join(updated)}. Server restarting in 3 seconds..."
            def do_restart():
                time.sleep(3)
                try:
                    subprocess.Popen([sys.executable, str(Path(__file__).resolve())])
                except Exception:
                    pass
                os._exit(0)
            threading.Thread(target=do_restart, daemon=True).start()
            return jsonify({"ok": 1, "updated": updated, "message": message})
        return jsonify({"ok": 0, "message": "No files were updated."})
    except Exception as e:
        return jsonify({"ok": 0, "message": f"Update failed: {e}"})

@app.route("/api/onboarding", methods=["POST"])
def api_onboarding():
    data = request.json
    p = gprofile()
    p["recipient_name"] = data.get("recipient_name", "Care Recipient")
    p["bio"] = data.get("bio", "")
    p["birthday"] = data.get("birthday", "")
    p["favorites"] = data.get("favorites", "")
    p["medical_notes"] = data.get("medical_notes", "")
    sprofile(p)
    cfg = gcfg()
    prompt = (
        f"Create a complete daily care schedule for {p['recipient_name']}. "
        f"Details: {data.get('description', '')}. "
        "Include bathroom, meals, medication, hydration, activities, sleep. Make it realistic and kind."
    )
    # Try structured AI first (instructor + pydantic)
    structured_sched = None
    if PYDANTIC_OK and INSTRUCTOR_OK:
        structured_sched = ai_onboard_structured(
            data.get("description", "") + " " + p.get("bio", ""),
            p["recipient_name"], cfg
        )
    if structured_sched and structured_sched.tasks:
        s = gsched()
        s["tasks"] = [{"time": t.time, "title": t.title, "category": t.category, "steps": t.steps} for t in structured_sched.tasks]
        s["tasks"].sort(key=lambda x: x["time"])
        ssched(s)
        note = structured_sched.notes or ""
        return jsonify({"ok": True, "message": f"Intake complete! AI generated a {len(s['tasks'])}-task personalized schedule. {note}".strip(), "actions": [f"Generated {len(s['tasks'])} tasks via structured AI"]})
    # Fallback to original method
    resp = ai_chat(prompt, cfg)
    clean, actions = process_actions(resp["response"] if isinstance(resp, dict) else resp)
    return jsonify({"ok": True, "message": "Intake complete! Your personalized schedule is ready.", "actions": actions})

@app.route("/api/memory")
def api_memory():
    return jsonify(gmem())

@app.route("/api/affirmation")
def api_affirmation():
    affs = [
        "You're doing an amazing job.",
        "Every small act of care matters deeply.",
        "Take a breath. You've got this.",
        "Your dedication makes a real difference.",
        "Take care of yourself too.",
        "One task at a time. You're enough.",
        "The love you give comes back tenfold.",
        "Progress, not perfection.",
        "You are exactly the caregiver they need.",
        "Today is a new opportunity to shine.",
    ]
    return jsonify({"text": random.choice(affs)})


# --- Main ---
@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    """Speech-to-text endpoint using faster-whisper."""
    if not WHISPER_OK:
        return jsonify({"error": "faster-whisper not installed", "text": ""}), 200
    try:
        audio_data = None
        ext = "wav"
        if request.content_type and "multipart" in request.content_type:
            f = request.files.get("audio")
            if f:
                ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "webm"
                audio_data = f.read()
        elif request.json and request.json.get("audio_b64"):
            audio_data = base64.b64decode(request.json["audio_b64"])
            ext = request.json.get("ext", "wav")
        if not audio_data:
            return jsonify({"error": "no audio", "text": ""}), 400
        text = transcribe_audio(audio_data, ext)
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": str(e), "text": ""}), 500


@app.route("/api/memory/search", methods=["POST"])
def api_memory_search():
    """Semantic memory search via ChromaDB."""
    query = request.json.get("query", "") if request.json else ""
    if not query:
        return jsonify({"results": []})
    results = chroma_search(query, n=8)
    return jsonify({"results": results, "engine": "chromadb" if CHROMA_OK else "none"})


@app.route("/api/capabilities")
def api_capabilities():
    """Report which enhanced features are available."""
    return jsonify({
        "voice_input": WHISPER_OK,
        "semantic_memory": CHROMA_OK,
        "structured_ai": PYDANTIC_OK and INSTRUCTOR_OK,
        "tts": tts.available if tts else False,
        "version": APP_VERSION,
    })


def start_server(port=5000
, host="127.0.0.1"):
    """Start Flask in a thread (used by both modes)."""
    global tts, rem
    ensure_dirs()
    cfg = gcfg()
    scfg(cfg)
    gsched()

    tts = TTS(cfg)
    # Start ChromaDB in background (non-blocking)
    if CHROMA_OK:
        threading.Thread(target=_init_chroma, daemon=True).start()
    print(f"TTS: {tts.engine_name} ({'ok' if tts.available else 'unavailable'})")

    rem = Reminders(tts)
    threading.Thread(target=rem.loop, daemon=True).start()
    print("Reminders: running")

    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


def main():
    parser = argparse.ArgumentParser(description="Care Agent v4.0")
    parser.add_argument("--server", action="store_true",
                        help="Run as web server only (no desktop window)")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    if args.server:
        # --- Server mode (headless, for remote access) ---
        print(f"\n\u2764\ufe0f  Care Agent v4.0 (server) at http://{args.host}:{args.port}\n")
        start_server(port=args.port, host=args.host)
    else:
        # --- Desktop mode (pywebview native window) ---
        try:
            import webview
        except ImportError:
            print("pywebview not installed. Falling back to browser mode.")
            print("Install it with: pip install pywebview")
            print(f"\n\u2764\ufe0f  Care Agent v4.0 at http://localhost:{args.port}\n")
            if not args.no_open:
                threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{args.port}")).start()
            start_server(port=args.port, host="127.0.0.1")
            return

        port = args.port
        url = f"http://127.0.0.1:{port}"

        # Start Flask in a background thread
        server_thread = threading.Thread(
            target=start_server,
            kwargs={"port": port, "host": "127.0.0.1"},
            daemon=True
        )
        server_thread.start()

        # Wait for the server to come up
        import urllib.request
        for _ in range(50):
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except Exception:
                time.sleep(0.1)

        print(f"\n\u2764\ufe0f  Care Agent v4.0 — Desktop Mode\n")

        # Create the native window
        window = webview.create_window(
            "Care Agent",
            url=url,
            width=960,
            height=720,
            min_size=(480, 600),
            resizable=True,
            text_select=True,
            confirm_close=True,
        )
        # This blocks until the window is closed
        webview.start(debug=False)
        print("Window closed. Goodbye!")
        os._exit(0)


if __name__ == "__main__":
    main()
