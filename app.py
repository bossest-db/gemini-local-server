import os
import time
import json
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from gemini_bridge import bridge
import archiver

app = FastAPI(
    title="Gemini Local API & Dashboard Server",
    description="Unofficial High-Performance Server & Archiver for Google Gemini Desktop",
    version="1.0.0"
)

# Enable CORS so any web client / local apps can connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_DIR = archiver.ARCHIVE_DIR
SERVER_PORT = int(os.environ.get("PORT", "10400"))

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Models
class ChatRequest(BaseModel):
    prompt: str
    new_chat: bool = False
    chat_id: Optional[str] = None
    stream: Optional[bool] = False
    model: Optional[str] = None

class SwitchChatRequest(BaseModel):
    chat_id: Optional[str] = None
    new_chat: bool = False

class SwitchModelRequest(BaseModel):
    model: str

# OpenAI compatible schemas
class OpenAIMessage(BaseModel):
    role: str
    content: str

class OpenAIChatRequest(BaseModel):
    model: Optional[str] = "gemini"
    messages: List[OpenAIMessage]
    stream: Optional[bool] = False


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Dashboard loading... please check back in a moment</h1>")
    return FileResponse(str(index_path))

@app.get("/api/status")
async def get_status():
    status = await bridge.get_status()
    status["archive_dir"] = str(ARCHIVE_DIR)
    status["current_model"] = await bridge.get_current_model()
    return status

@app.get("/api/model")
async def get_model():
    return {"current_model": await bridge.get_current_model()}

@app.post("/api/model/switch")
async def switch_model_endpoint(req: SwitchModelRequest):
    res = await bridge.switch_model(req.model)
    return res

@app.get("/api/chats/recent")
async def get_recent_chats():
    chats = await bridge.get_recent_chats()
    return {"chats": chats}

@app.get("/api/chats/archived")
async def get_archived_chats():
    chats = archiver.list_archived_chats()
    return {"chats": chats}

@app.get("/api/chats/archived/{folder_name}")
async def get_archived_chat_detail(folder_name: str):
    data = archiver.get_archived_chat(folder_name)
    if not data:
        raise HTTPException(status_code=404, detail="Archived chat not found")
    return data

@app.get("/archive/{folder_name}/{filename}")
async def serve_archived_file(folder_name: str, filename: str):
    file_path = ARCHIVE_DIR / folder_name / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    media_type = "video/mp4" if filename.endswith(".mp4") else ("image/png" if filename.endswith(".png") else None)
    return FileResponse(str(file_path), media_type=media_type, filename=filename)

@app.get("/api/chats/{chat_id}/video")
async def get_chat_video(chat_id: str):
    """Directly stream or download the video file for a chat by chat_id"""
    for folder in ARCHIVE_DIR.iterdir():
        if folder.is_dir():
            meta_file = folder / "meta.json"
            if meta_file.exists():
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        if meta.get("chat_id") == chat_id:
                            videos = list(folder.glob("*.mp4"))
                            if videos:
                                videos.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                                return FileResponse(
                                    str(videos[0]),
                                    media_type="video/mp4",
                                    filename=videos[0].name
                                )
                except Exception:
                    pass
    raise HTTPException(status_code=404, detail="No video found for this chat")

@app.get("/api/chats/{chat_id}/image")
async def get_chat_image(chat_id: str):
    """Directly stream or download the latest image for a chat by chat_id"""
    for folder in ARCHIVE_DIR.iterdir():
        if folder.is_dir():
            meta_file = folder / "meta.json"
            if meta_file.exists():
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        if meta.get("chat_id") == chat_id:
                            images = list(folder.glob("image_*.png"))
                            if images:
                                images.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                                return FileResponse(
                                    str(images[0]),
                                    media_type="image/png",
                                    filename=images[0].name
                                )
                except Exception:
                    pass
    raise HTTPException(status_code=404, detail="No image found for this chat")

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    if req.model:
        m_lower = req.model.lower()
        curr_m = (await bridge.get_current_model()).lower()
        if "pro" in m_lower and "pro" not in curr_m:
            await bridge.switch_model("pro")
        elif "flash" in m_lower and "flash" not in curr_m and "lite" not in m_lower:
            await bridge.switch_model("flash")
        elif "lite" in m_lower and "lite" not in curr_m:
            await bridge.switch_model("flash-lite")
        elif ("think" in m_lower or "사고" in m_lower) and "사고" not in curr_m:
            await bridge.switch_model("thinking")

    if req.stream:
        async def event_generator():
            try:
                async for event in bridge.send_prompt_stream(
                    prompt=req.prompt,
                    new_chat=req.new_chat,
                    chat_id=req.chat_id
                ):
                    if event["type"] == "delta":
                        yield f"data: {json.dumps({'type': 'delta', 'delta': event['text'], 'full_text': event['full_text']})}\n\n"
                    elif event["type"] == "done":
                        saved = archiver.save_turn(
                            chat_id=event["chat_id"],
                            title=event["title"],
                            user_prompt=req.prompt,
                            assistant_text=event["text"],
                            images_base64=event.get("images", []),
                            videos=event.get("videos", [])
                        )
                        done_payload = {
                            "type": "done",
                            "success": True,
                            "chat_id": event["chat_id"],
                            "title": event["title"],
                            "text": event["text"],
                            "images": saved["saved_images"],
                            "videos": saved.get("saved_videos", []),
                            "folder_name": saved["folder_name"],
                            "folder_path": saved["folder_path"],
                            "md_path": saved["md_path"]
                        }
                        yield f"data: {json.dumps(done_payload)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    try:
        # 1. Send to Gemini bridge
        res = await bridge.send_prompt(
            prompt=req.prompt,
            new_chat=req.new_chat,
            chat_id=req.chat_id
        )

        # 2. Archive locally
        saved = archiver.save_turn(
            chat_id=res["chat_id"],
            title=res["title"],
            user_prompt=req.prompt,
            assistant_text=res["text"],
            images_base64=res.get("images", []),
            videos=res.get("videos", [])
        )

        return {
            "success": True,
            "chat_id": res["chat_id"],
            "title": res["title"],
            "text": res["text"],
            "images": saved["saved_images"],
            "videos": saved.get("saved_videos", []),
            "folder_name": saved["folder_name"],
            "folder_path": saved["folder_path"],
            "md_path": saved["md_path"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chats/switch")
async def switch_chat_endpoint(req: SwitchChatRequest):
    try:
        if req.new_chat:
            await bridge.eval_js("""
            (() => {
                const btn = Array.from(document.querySelectorAll('a[aria-label*="새 채팅"], button[aria-label*="새 채팅"]')).find(el => el.innerText.includes('새 채팅')) || document.querySelector('a[aria-label*="새 채팅"]');
                if (btn) btn.click();
                else window.location.href = 'https://gemini.google.com/app';
            })()
            """)
        elif req.chat_id:
            await bridge.eval_js(f"window.location.href = 'https://gemini.google.com/app/{req.chat_id}';")
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/archive/open")
async def open_archive_folder():
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(ARCHIVE_DIR))
        return {"success": True, "path": str(ARCHIVE_DIR)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# OpenAI Compatible API Endpoint (/v1)
# ==========================================
@app.post("/v1/chat/completions")
async def openai_compatible_chat(req: OpenAIChatRequest):
    # Extract last user message
    user_msg = next((m.content for m in reversed(req.messages) if m.role == "user"), None)
    if not user_msg:
        raise HTTPException(status_code=400, detail="No user message provided")

    # Auto-switch model if requested
    if req.model and req.model.lower() not in ("gemini", "default"):
        m_lower = req.model.lower()
        curr_m = (await bridge.get_current_model()).lower()
        if "pro" in m_lower and "pro" not in curr_m:
            await bridge.switch_model("pro")
        elif "flash" in m_lower and "flash" not in curr_m and "lite" not in m_lower:
            await bridge.switch_model("flash")
        elif "lite" in m_lower and "lite" not in curr_m:
            await bridge.switch_model("flash-lite")
        elif ("think" in m_lower or "사고" in m_lower) and "사고" not in curr_m:
            await bridge.switch_model("thinking")

    now_ts = int(time.time())
    chunk_id = f"chatcmpl-{now_ts}"

    if req.stream:
        async def openai_stream_generator():
            try:
                async for event in bridge.send_prompt_stream(prompt=user_msg, new_chat=False):
                    if event["type"] == "delta":
                        chunk = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": now_ts,
                            "model": req.model or "gemini",
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": event["text"]},
                                    "finish_reason": None
                                }
                            ]
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                    elif event["type"] == "done":
                        saved = archiver.save_turn(
                            chat_id=event["chat_id"],
                            title=event["title"],
                            user_prompt=user_msg,
                            assistant_text=event["text"],
                            images_base64=event.get("images", []),
                            videos=event.get("videos", [])
                        )
                        # If video or images were generated, yield a final delta with the links
                        media_note = ""
                        if saved.get("saved_videos"):
                            vid_links = "\n".join([f"- 🎥 동영상 다운로드: http://localhost:{SERVER_PORT}/archive/{v['rel_path']}" for v in saved["saved_videos"]])
                            media_note += f"\n\n[생성된 동영상]\n{vid_links}"
                        elif saved.get("saved_images"):
                            img_links = "\n".join([f"- 🖼️ 이미지 다운로드: http://localhost:{SERVER_PORT}/archive/{img['rel_path']}" for img in saved["saved_images"]])
                            media_note += f"\n\n[생성된 이미지]\n{img_links}"

                        if media_note:
                            media_chunk = {
                                "id": chunk_id,
                                "object": "chat.completion.chunk",
                                "created": now_ts,
                                "model": req.model or "gemini",
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {"content": media_note},
                                        "finish_reason": None
                                    }
                                ]
                            }
                            yield f"data: {json.dumps(media_chunk)}\n\n"

                        stop_chunk = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "created": now_ts,
                            "model": req.model or "gemini",
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {},
                                    "finish_reason": "stop"
                                }
                            ]
                        }
                        yield f"data: {json.dumps(stop_chunk)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                err_chunk = {"error": {"message": str(e), "type": "server_error"}}
                yield f"data: {json.dumps(err_chunk)}\n\n"

        return StreamingResponse(
            openai_stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    try:
        res = await bridge.send_prompt(prompt=user_msg, new_chat=False)
        saved = archiver.save_turn(
            chat_id=res["chat_id"],
            title=res["title"],
            user_prompt=user_msg,
            assistant_text=res["text"],
            images_base64=res.get("images", []),
            videos=res.get("videos", [])
        )

        content_text = res["text"]
        if saved.get("saved_videos"):
            vid_links = "\n".join([f"- 🎥 동영상 다운로드: http://localhost:{SERVER_PORT}/archive/{v['rel_path']}" for v in saved["saved_videos"]])
            content_text += f"\n\n[생성된 동영상]\n{vid_links}"
        elif saved.get("saved_images"):
            img_links = "\n".join([f"- 🖼️ 이미지 다운로드: http://localhost:{SERVER_PORT}/archive/{img['rel_path']}" for img in saved["saved_images"]])
            content_text += f"\n\n[생성된 이미지]\n{img_links}"

        return {
            "id": chunk_id,
            "object": "chat.completion",
            "created": now_ts,
            "model": req.model or "gemini",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content_text
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": len(user_msg.split()),
                "completion_tokens": len(res["text"].split()),
                "total_tokens": len(user_msg.split()) + len(res["text"].split())
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    print(f"Starting Gemini Local Server on http://0.0.0.0:{SERVER_PORT}...")
    print(f"Archive directory: {ARCHIVE_DIR}")
    uvicorn.run("app:app", host="0.0.0.0", port=SERVER_PORT, reload=False)
