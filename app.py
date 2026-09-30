import json
import os
import re
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI

app = FastAPI(title="Reels Factory")

class AnalyzeRequest(BaseModel):
    url: str
    count: int = 10
    min_seconds: int = 25
    max_seconds: int = 90


def video_id(url: str) -> str:
    patterns = [r"youtu\.be/([\w-]{11})", r"[?&]v=([\w-]{11})", r"youtube\.com/shorts/([\w-]{11})"]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    raise ValueError("Не удалось определить YouTube video ID")


def ts(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds//60:02d}:{seconds%60:02d}"


def transcript_text(vid: str):
    api = YouTubeTranscriptApi()
    fetched = api.fetch(vid, languages=["ru", "en", "uk"])
    rows = []
    for x in fetched:
        rows.append({"start": float(x.start), "duration": float(x.duration), "text": x.text})
    compact = "\n".join(f"[{ts(x['start'])}] {x['text']}" for x in rows)
    return rows, compact


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse('''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Reels Factory</title><style>body{font-family:system-ui;background:#0d0f14;color:#eee;max-width:900px;margin:40px auto;padding:20px}h1{font-size:42px}input,button{font-size:18px;padding:14px;border-radius:10px;border:1px solid #333}input{width:70%;background:#151923;color:white}button{background:#eee;color:#111;cursor:pointer}.card{background:#151923;padding:18px;margin:14px 0;border-radius:14px}.score{font-size:24px;font-weight:700}small{color:#aaa}</style></head><body><h1>REELS FACTORY</h1><p>Вставьте YouTube-ссылку. AI найдёт лучшие самостоятельные фрагменты для Shorts/Reels.</p><input id="url" value="https://youtu.be/Gb0TQ7VeApY"><button onclick="go()">Найти моменты</button><p id="status"></p><div id="out"></div><script>async function go(){let s=document.getElementById('status'),o=document.getElementById('out');s.textContent='Получаю транскрипт и анализирую…';o.innerHTML='';try{let r=await fetch('/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:document.getElementById('url').value,count:10})});let d=await r.json();if(!r.ok)throw new Error(d.detail||'Ошибка');s.textContent='Готово: '+d.clips.length+' кандидатов';d.clips.forEach((x,i)=>o.innerHTML+=`<div class="card"><div class="score">#${i+1} · ${x.score||''}/100</div><h3>${x.title||x.hook}</h3><b>${x.start} → ${x.end}</b><p>${x.hook}</p><small>${x.reason||''}</small></div>`)}catch(e){s.textContent='Ошибка: '+e.message}}</script></body></html>''')


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    try:
        vid = video_id(req.url)
        _, transcript = transcript_text(vid)
    except Exception as e:
        raise HTTPException(400, f"Не удалось получить транскрипт: {e}")

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(500, "На сервере не задан OPENAI_API_KEY")
    client = OpenAI(api_key=key)
    prompt = f'''Ты редактор коротких вертикальных видео. Из транскрипта длинного YouTube-видео выбери {req.count} лучших самостоятельных фрагментов длиной примерно {req.min_seconds}-{req.max_seconds} секунд. Каждый фрагмент должен быть понятен без просмотра исходника. Цени сильное начало, законченную мысль, историю, удивление, полезность и эмоциональный поворот. Не выдумывай цитаты и таймкоды. Верни только JSON-массив объектов: start, end, hook, title, reason, score (0-100). start/end в MM:SS.\n\nТРАНСКРИПТ:\n{transcript}'''
    try:
        response = client.chat.completions.create(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), messages=[{"role":"user","content":prompt}], temperature=0.2)
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        clips = json.loads(raw)
    except Exception as e:
        raise HTTPException(500, f"AI-анализ не удался: {e}")
    return {"video_id": vid, "clips": clips}
