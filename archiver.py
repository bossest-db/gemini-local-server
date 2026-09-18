import os
import re
import json
import base64
from datetime import datetime
from pathlib import Path

ARCHIVE_DIR = Path(os.environ.get("GEMINI_ARCHIVE_DIR", r"C:\Users\yu\Documents\Gemini_Archive"))
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

def sanitize_filename(name: str, max_length: int = 50) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
    cleaned = re.sub(r'\s+', "_", cleaned.strip())
    if not cleaned:
        cleaned = "무제_대화"
    return cleaned[:max_length]

def find_chat_dir(chat_id: str) -> Path | None:
    """Find existing chat directory by chat_id in meta.json"""
    for folder in ARCHIVE_DIR.iterdir():
        if folder.is_dir():
            meta_file = folder / "meta.json"
            if meta_file.exists():
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if data.get("chat_id") == chat_id:
                            return folder
                except Exception:
                    pass
    return None

def save_turn(
    chat_id: str,
    title: str,
    user_prompt: str,
    assistant_text: str,
    images_base64: list[dict] = None,
    videos: list[dict] = None
) -> dict:
    """
    Saves or appends a conversation turn to the archive.
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    folder = find_chat_dir(chat_id)
    if not folder:
        safe_title = sanitize_filename(title)
        folder_name = f"{date_str}_{safe_title}"
        folder = ARCHIVE_DIR / folder_name
        # avoid collision if another folder has the exact same name
        counter = 1
        while folder.exists():
            folder = ARCHIVE_DIR / f"{folder_name}_{counter}"
            counter += 1
        folder.mkdir(parents=True, exist_ok=True)

    # Save images
    saved_images = []
    if images_base64:
        existing_images = list(folder.glob("image_*.png"))
        img_idx = len(existing_images) + 1
        for img_item in images_base64:
            raw_data = img_item.get("data", "")
            if not raw_data:
                continue
            if raw_data.startswith("data:"):
                # Remove header
                raw_data = raw_data.split(",", 1)[1]
            try:
                img_bytes = base64.b64decode(raw_data)
                img_filename = f"image_{img_idx:02d}.png"
                img_path = folder / img_filename
                with open(img_path, "wb") as f:
                    f.write(img_bytes)
                saved_images.append({
                    "filename": img_filename,
                    "rel_path": f"{folder.name}/{img_filename}",
                    "abs_path": str(img_path),
                    "url": f"/archive/{folder.name}/{img_filename}"
                })
                img_idx += 1
            except Exception as e:
                print(f"[Archiver] Failed to decode image: {e}")

    # Save videos
    saved_videos = []
    if videos:
        import urllib.request
        vid_idx = len(list(folder.glob("video_*.mp4"))) + 1
        for vid_item in videos:
            url = vid_item.get("url", "")
            if not url:
                continue
            try:
                vid_filename = f"video_{vid_idx:02d}.mp4"
                vid_path = folder / vid_filename
                if url.startswith("http://") or url.startswith("https://"):
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req) as resp, open(vid_path, "wb") as out:
                        out.write(resp.read())
                    saved_videos.append({
                        "filename": vid_filename,
                        "rel_path": f"{folder.name}/{vid_filename}",
                        "abs_path": str(vid_path),
                        "url": f"/archive/{folder.name}/{vid_filename}",
                        "width": vid_item.get("width", 1280),
                        "height": vid_item.get("height", 720)
                    })
                    vid_idx += 1
            except Exception as e:
                print(f"[Archiver] Failed to download video: {e}")

    # Append to conversation.md
    md_path = folder / "conversation.md"
    is_new = not md_path.exists()
    
    with open(md_path, "a", encoding="utf-8") as f:
        if is_new:
            f.write(f"# {title}\n")
            f.write(f"- 생성 날짜: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"- 대화방 ID: `{chat_id}`\n\n---\n\n")
        
        f.write(f"### 👤 사용자 ({time_str})\n\n{user_prompt}\n\n")
        f.write(f"### 🤖 Gemini ({time_str})\n\n{assistant_text}\n\n")
        
        if saved_images:
            for img in saved_images:
                f.write(f"![{img['filename']}]({img['filename']})\n\n")
        if saved_videos:
            for vid in saved_videos:
                f.write(f"🎥 **생성된 비디오**: `{vid['filename']}`\n<video controls width=\"100%\" src=\"{vid['filename']}\"></video>\n\n")
        f.write("---\n\n")

    # Update meta.json
    meta_path = folder / "meta.json"
    meta = {
        "chat_id": chat_id,
        "title": title,
        "folder_name": folder.name,
        "updated_at": now.isoformat(),
        "created_at": now.isoformat() if is_new else None,
        "image_count": len(list(folder.glob("image_*.png"))),
        "video_count": len(list(folder.glob("*.mp4")))
    }
    if not is_new and meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                old_meta = json.load(f)
                meta["created_at"] = old_meta.get("created_at", now.isoformat())
        except Exception:
            pass

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {
        "folder_name": folder.name,
        "folder_path": str(folder),
        "md_path": str(md_path),
        "saved_images": saved_images,
        "saved_videos": saved_videos
    }

def list_archived_chats() -> list[dict]:
    """Returns all archived chats sorted by last updated"""
    results = []
    if not ARCHIVE_DIR.exists():
        return results

    for folder in ARCHIVE_DIR.iterdir():
        if folder.is_dir():
            meta_path = folder / "meta.json"
            meta = {}
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception:
                    pass
            if not meta:
                meta = {
                    "folder_name": folder.name,
                    "title": folder.name,
                    "updated_at": datetime.fromtimestamp(folder.stat().st_mtime).isoformat()
                }
            meta["image_count"] = len(list(folder.glob("image_*.png")))
            meta["video_count"] = len(list(folder.glob("*.mp4")))
            results.append(meta)
    results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return results

def get_archived_chat(folder_name: str) -> dict | None:
    folder = ARCHIVE_DIR / folder_name
    if not folder.exists() or not folder.is_dir():
        return None
    
    md_path = folder / "conversation.md"
    meta_path = folder / "meta.json"
    
    content = ""
    if md_path.exists():
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
            
    meta = {}
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass

    images = [img.name for img in folder.glob("image_*.png")]
    videos = [v.name for v in folder.glob("*.mp4")]

    return {
        "folder_name": folder.name,
        "meta": meta,
        "markdown": content,
        "images": images,
        "videos": videos
    }
