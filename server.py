import os
import json
import uuid
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
import yt_dlp

# --- CONFIGURACIÓN DE RUTAS Y FFMPEG ---
# Detectamos si estamos en Render (Linux) o local (Windows)
if os.path.exists("./ffmpeg/ffmpeg"):
    FFMPEG_PATH = "./ffmpeg/ffmpeg" # Render
else:
    FFMPEG_PATH = "./ffmpeg.exe"    # Local

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CACHE_DIR = "cache_videos"
DATA_FILE = "data.json"
os.makedirs(CACHE_DIR, exist_ok=True)

download_progress = {}

# --- UTILIDADES DE BASE DE DATOS ---
def load_db():
    if not os.path.exists(DATA_FILE):
        return {"sections": [], "videos": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return {"sections": [], "videos": []}

def save_db(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# --- RUTAS DE INTERFAZ Y API ---
@app.get("/", response_class=HTMLResponse)
def read_index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Error: No se encontró index.html</h1>"

@app.get("/api/data")
def get_data(): return load_db()

@app.post("/api/sections")
def add_section(section: dict):
    db = load_db()
    section["id"] = str(uuid.uuid4())
    db["sections"].append(section)
    save_db(db)
    return section

@app.delete("/api/sections/{section_id}")
def delete_section(section_id: str):
    db = load_db()
    db["sections"] = [s for s in db["sections"] if s["id"] != section_id]
    db["videos"] = [v for v in db["videos"] if v.get("sectionId") != section_id]
    save_db(db)
    return {"status": "ok"}

@app.post("/api/videos")
def add_video(video: dict):
    db = load_db()
    video["id"] = str(uuid.uuid4())
    video["cacheStatus"] = "none"
    db["videos"].append(video)
    save_db(db)
    return video

@app.get("/api/status/{video_id}")
def get_status(video_id: str):
    return download_progress.get(video_id, {"status": "none", "progress": 0})

@app.post("/api/cache/{video_id}")
def start_cache(video_id: str, background_tasks: BackgroundTasks):
    db = load_db()
    video = next((v for v in db["videos"] if v["id"] == video_id), None)
    if video:
        background_tasks.add_task(background_download, video_id, video["url"])
        return {"status": "downloading"}
    raise HTTPException(status_code=404)

# --- LÓGICA DE DESCARGA (CORREGIDA) ---
def background_download(video_id, url):
    def progress_hook(d):
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%').replace('%','').strip()
            try:
                download_progress[video_id] = {"status": "downloading", "progress": float(p)}
            except: pass
        if d['status'] == 'finished':
            download_progress[video_id] = {"status": "processing", "progress": 100}

    # Aquí usamos la variable FFMPEG_PATH que definimos arriba
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{CACHE_DIR}/{video_id}.mp4',
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'progress_hooks': [progress_hook],
        'ffmpeg_location': FFMPEG_PATH, # <--- USAR LA VARIABLE GLOBAL
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([url])
            db = load_db()
            for v in db["videos"]:
                if v["id"] == video_id:
                    v["cacheStatus"] = "cached"
            save_db(db)
            download_progress[video_id] = {"status": "done", "progress": 100}
        except Exception as e:
            print(f"Error: {e}")
            download_progress[video_id] = {"status": "error", "progress": 0}

@app.get("/cache/{video_id}.mp4")
def serve_video(video_id: str):
    path = os.path.join(CACHE_DIR, f"{video_id}.mp4")
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404)

# Endpoint para servir archivos locales (C:\...)
@app.get("/localfile")
async def serve_local_file(path: str):
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404)

if __name__ == "__main__":
    import uvicorn
    # En Render, la variable de entorno PORT es asignada automáticamente
    port = int(os.environ.get("PORT", 3000))
    uvicorn.run(app, host="0.0.0.0", port=port)
