import os
import json
import uuid
import asyncio
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
import yt_dlp

app = FastAPI()

# Configuración de CORS para que el navegador no bloquee las peticiones
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CACHE_DIR = "cache_videos"
DATA_FILE = "data.json"
os.makedirs(CACHE_DIR, exist_ok=True)

# DICCIONARIO GLOBAL: Aquí se guarda el % de descarga para el Dashboard
download_progress = {}

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

# --- RUTAS DE INTERFAZ ---

@app.get("/", response_class=HTMLResponse)
def read_index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Error: No se encontró index.html en la carpeta v6</h1>"

# --- RUTAS DE SECCIONES (CRUD) ---

@app.get("/api/data")
def get_data():
    return load_db()

@app.post("/api/sections")
def add_section(section: dict):
    db = load_db()
    section["id"] = str(uuid.uuid4())
    db["sections"].append(section)
    save_db(db)
    return section

@app.put("/api/sections/{section_id}")
def update_section(section_id: str, section_data: dict):
    db = load_db()
    for s in db["sections"]:
        if s["id"] == section_id:
            s.update(section_data)
            save_db(db)
            return s
    raise HTTPException(status_code=404, detail="Sección no encontrada")

@app.delete("/api/sections/{section_id}")
def delete_section(section_id: str):
    db = load_db()
    db["sections"] = [s for s in db["sections"] if s["id"] != section_id]
    db["videos"] = [v for v in db["videos"] if v.get("sectionId") != section_id]
    save_db(db)
    return {"status": "ok"}

# --- RUTAS DE VIDEOS Y CACHÉ ---

@app.post("/api/videos")
def add_video(video: dict):
    db = load_db()
    video["id"] = str(uuid.uuid4())
    video["cacheStatus"] = "none"
    db["videos"].append(video)
    save_db(db)
    return video

@app.delete("/api/videos/{video_id}")
def delete_video(video_id: str):
    db = load_db()
    db["videos"] = [v for v in db["videos"] if v["id"] != video_id]
    save_db(db)
    video_path = f"{CACHE_DIR}/{video_id}.mp4"
    if os.path.exists(video_path):
        os.remove(video_path)
    return {"status": "ok"}

@app.get("/api/status/{video_id}")
def get_status(video_id: str):
    # Esta ruta la consulta el Dashboard cada segundo
    return download_progress.get(video_id, {"status": "none", "progress": 0})

@app.post("/api/cache/{video_id}")
def start_cache(video_id: str, background_tasks: BackgroundTasks):
    db = load_db()
    video = next((v for v in db["videos"] if v["id"] == video_id), None)
    if video:
        # Iniciamos descarga en segundo plano para no bloquear el Dashboard
        background_tasks.add_task(background_download, video_id, video["url"])
        return {"status": "downloading"}
    raise HTTPException(status_code=404, detail="Video no encontrado")

# --- LÓGICA DE DESCARGA (yt-dlp + FFmpeg) ---

def background_download(video_id, url):
    def progress_hook(d):
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%').replace('%','').strip()
            try:
                # Actualizamos el diccionario global con el número real
                download_progress[video_id] = {"status": "downloading", "progress": float(p)}
            except: pass
        if d['status'] == 'finished':
            download_progress[video_id] = {"status": "processing", "progress": 100}

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{CACHE_DIR}/{video_id}.mp4',
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'progress_hooks': [progress_hook],
        # Buscamos ffmpeg.exe en la misma carpeta del script
        'ffmpeg_location': os.path.abspath('.') 
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([url])
            # Marcamos como completado en la base de datos
            db = load_db()
            for v in db["videos"]:
                if v["id"] == video_id:
                    v["cacheStatus"] = "cached"
            save_db(db)
            download_progress[video_id] = {"status": "done", "progress": 100}
        except Exception as e:
            print(f"Error en descarga: {e}")
            download_progress[video_id] = {"status": "error", "progress": 0}

@app.get("/cache/{video_id}.mp4")
def serve_video(video_id: str):
    path = os.path.join(CACHE_DIR, f"{video_id}.mp4")
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404)

# Rutas de diagnóstico para evitar errores 404 en el panel
@app.get("/api/ping")
def ping(): return {"status": "ok"}
@app.get("/api/downloads")
def get_downloads(): return download_progress

if __name__ == "__main__":
    import uvicorn
    # Iniciamos el servidor en el puerto 3000
    uvicorn.run(app, host="0.0.0.0", port=3000)