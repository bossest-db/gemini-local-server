import os
import asyncio
import json
import logging
import urllib.request
import websockets
from typing import Optional, Dict, Any, List

logger = logging.getLogger("gemini_bridge")
logging.basicConfig(level=logging.INFO)

CDP_HOST = os.environ.get("CDP_HOST", "127.0.0.1")
CDP_PORT = int(os.environ.get("CDP_PORT", "9223"))

class GeminiBridge:
    def __init__(self, host: str = CDP_HOST, port: int = CDP_PORT):
        self.host = host
        self.port = port
        self.ws = None
        self.ws_url = None
        self.msg_id = 1
        self.pending = {}
        self.lock = asyncio.Lock()
        self._listen_task = None

    async def get_ws_url(self) -> Optional[str]:
        try:
            req = urllib.request.urlopen(f"http://{self.host}:{self.port}/json", timeout=3)
            tabs = json.loads(req.read().decode("utf-8"))
            gemini_tab = next((t for t in tabs if "gemini.google.com" in t.get("url", "")), None)
            if gemini_tab:
                url = gemini_tab.get("webSocketDebuggerUrl")
                if url and self.host not in ("127.0.0.1", "localhost"):
                    url = url.replace("127.0.0.1", self.host).replace("localhost", self.host)
                return url
        except Exception as e:
            logger.warning(f"Failed to fetch CDP targets from {self.host}:{self.port}: {e}")
        return None

    def is_connected(self) -> bool:
        if not self.ws:
            return False
        try:
            from websockets.protocol import State
            return self.ws.state == State.OPEN
        except Exception:
            return getattr(self.ws, "open", False)

    async def connect(self) -> bool:
        if self.is_connected():
            return True

        self.ws_url = await self.get_ws_url()
        if not self.ws_url:
            return False

        try:
            self.ws = await websockets.connect(self.ws_url, max_size=100_000_000, ping_interval=20)
            if self._listen_task and not self._listen_task.done():
                self._listen_task.cancel()
            self._listen_task = asyncio.create_task(self._listener())
            logger.info("Connected to Gemini CDP")
            return True
        except Exception as e:
            logger.error(f"CDP connection failed: {e}")
            self.ws = None
            return False

    async def _listener(self):
        try:
            async for msg_str in self.ws:
                data = json.loads(msg_str)
                mid = data.get("id")
                if mid and mid in self.pending:
                    fut = self.pending.pop(mid)
                    if not fut.done():
                        if "error" in data:
                            fut.set_exception(Exception(data["error"]))
                        else:
                            fut.set_result(data.get("result", {}))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"CDP listener closed: {e}")
        finally:
            self.ws = None

    async def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Any:
        if not await self.connect():
            raise RuntimeError("Gemini is not running or CDP is not accessible on port 9223.")

        self.msg_id += 1
        cur_id = self.msg_id
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self.pending[cur_id] = fut

        payload = {"id": cur_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(payload))

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self.pending.pop(cur_id, None)
            raise TimeoutError(f"CDP call {method} timed out after {timeout}s")

    async def eval_js(self, expression: str, await_promise: bool = False, timeout: float = 30.0) -> Any:
        res = await self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise
        }, timeout=timeout)
        return res.get("result", {}).get("value")

    async def get_status(self) -> Dict[str, Any]:
        connected = await self.connect()
        if not connected:
            return {"connected": False, "error": "Gemini process not detected on port 9223"}

        try:
            page_info = await self.eval_js("""
            (() => {
                const match = window.location.pathname.match(/\\/app\\/([a-zA-Z0-9]+)/);
                return {
                    url: window.location.href,
                    title: document.title.replace(' - Google Gemini', '').trim(),
                    chat_id: match ? match[1] : null,
                    hasEditor: !!document.querySelector('.ql-editor')
                };
            })()
            """)
            return {
                "connected": True,
                "url": page_info.get("url"),
                "title": page_info.get("title"),
                "chat_id": page_info.get("chat_id"),
                "ready": page_info.get("hasEditor", False)
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def get_recent_chats(self) -> List[Dict[str, str]]:
        if not await self.connect():
            return []
        try:
            chats = await self.eval_js("""
            (() => {
                const links = Array.from(document.querySelectorAll('a[href*="/app/"]')).filter(a => {
                    return a.href && !a.href.endsWith('/app') && !a.href.endsWith('/app/');
                });
                const seen = new Set();
                const result = [];
                for (const a of links) {
                    const match = a.href.match(/\\/app\\/([a-zA-Z0-9]+)/);
                    if (!match) continue;
                    const id = match[1];
                    if (seen.has(id)) continue;
                    seen.add(id);
                    const title = a.innerText.trim() || a.getAttribute('aria-label') || '대화';
                    result.push({ id, title, url: a.href });
                }
                return result;
            })()
            """)
            return chats or []
        except Exception as e:
            logger.warning(f"Failed to fetch recent chats: {e}")
            return []

    async def send_prompt_stream(
        self,
        prompt: str,
        new_chat: bool = False,
        chat_id: Optional[str] = None,
        timeout: float = 120.0
    ):
        """
        Sends prompt to Gemini and streams deltas in real-time as an async generator.
        Yields:
          {"type": "delta", "text": "...", "full_text": "..."}
          {"type": "done", "chat_id": "...", "title": "...", "text": "...", "images": [...], "videos": [...]}
        """
        async with self.lock:
            if not await self.connect():
                raise RuntimeError("Cannot connect to Gemini on port 9223.")

            # 1. Chat navigation
            if chat_id:
                curr_status = await self.get_status()
                if curr_status.get("chat_id") != chat_id:
                    logger.info(f"Switching to chat: {chat_id}")
                    await self.eval_js(f"window.location.href = 'https://gemini.google.com/app/{chat_id}';")
                    await asyncio.sleep(2.0)
            elif new_chat:
                logger.info("Opening new chat...")
                await self.eval_js("""
                (() => {
                    const btn = Array.from(document.querySelectorAll('a[aria-label*="새 채팅"], button[aria-label*="새 채팅"]')).find(el => el.innerText.includes('새 채팅')) || document.querySelector('a[aria-label*="새 채팅"]');
                    if (btn) {
                        btn.click();
                    } else {
                        window.location.href = 'https://gemini.google.com/app';
                    }
                })()
                """)
                await asyncio.sleep(2.0)

            # Wait for editor to be present
            for _ in range(10):
                has_editor = await self.eval_js("!!document.querySelector('rich-textarea .ql-editor')")
                if has_editor:
                    break
                await asyncio.sleep(0.5)

            # Record initial message count
            if new_chat:
                initial_count = 0
            else:
                initial_count = await self.eval_js(
                    "document.querySelectorAll('message-content').length"
                ) or 0

            # 2. Insert prompt into editor
            inserted = await self.eval_js(f"""
            (() => {{
                const editor = document.querySelector('rich-textarea .ql-editor');
                if (!editor) return false;
                editor.focus();
                document.execCommand('selectAll', false, null);
                document.execCommand('insertText', false, {json.dumps(prompt)});
                editor.dispatchEvent(new Event('input', {{ bubbles: true }}));
                return true;
            }})()
            """)
            if not inserted:
                raise RuntimeError("Failed to locate or insert prompt into Gemini editor.")

            await asyncio.sleep(0.4)

            # 3. Dispatch Enter key
            await self.call("Input.dispatchKeyEvent", {
                "type": "rawKeyDown",
                "windowsVirtualKeyCode": 13,
                "unmodifiedText": "\r",
                "text": "\r",
                "key": "Enter",
                "code": "Enter"
            })
            await self.call("Input.dispatchKeyEvent", {
                "type": "char",
                "windowsVirtualKeyCode": 13,
                "unmodifiedText": "\r",
                "text": "\r",
                "key": "Enter",
                "code": "Enter"
            })
            await self.call("Input.dispatchKeyEvent", {
                "type": "keyUp",
                "windowsVirtualKeyCode": 13,
                "unmodifiedText": "\r",
                "text": "\r",
                "key": "Enter",
                "code": "Enter"
            })

            # Check if send button needs click as fallback
            await asyncio.sleep(0.4)
            await self.eval_js("""
            (() => {
                const editor = document.querySelector('rich-textarea .ql-editor');
                const sendBtn = document.querySelector('.send-button button, button.send-button, button[aria-label*="보내기"], .send-button');
                if (editor && editor.innerText.trim().length > 0 && sendBtn) {
                    sendBtn.click();
                    sendBtn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                }
            })()
            """)

            # 4. Stream response tokens
            logger.info("Streaming Gemini response...")
            start_time = asyncio.get_event_loop().time()
            last_text = ""
            last_yielded_len = 0
            stable_count = 0

            while (asyncio.get_event_loop().time() - start_time) < timeout:
                await asyncio.sleep(0.08)
                
                check = await self.eval_js(f"""
                (() => {{
                    const msgs = Array.from(document.querySelectorAll('message-content'));
                    const isGenerating = !!document.querySelector('button[aria-label*="중지"], button[aria-label*="Stop"], mat-progress-bar');
                    if (msgs.length <= {initial_count}) {{
                        return {{ text: '', isGenerating, hasNew: false }};
                    }}
                    const latest = msgs[msgs.length - 1];
                    const text = (latest.innerText || latest.textContent || '').trim();
                    return {{
                        text: text,
                        isGenerating: isGenerating,
                        hasNew: true
                    }};
                }})()
                """) or {}

                curr_text = check.get("text", "")
                is_gen = check.get("isGenerating", False)
                has_new = check.get("hasNew", False)

                if has_new and len(curr_text) > last_yielded_len:
                    delta = curr_text[last_yielded_len:]
                    last_yielded_len = len(curr_text)
                    last_text = curr_text
                    yield {
                        "type": "delta",
                        "text": delta,
                        "full_text": curr_text
                    }

                if has_new and curr_text:
                    if curr_text == last_text and not is_gen:
                        stable_count += 1
                        if stable_count >= 3:
                            # Response is stable and stop button is gone
                            break
                    else:
                        stable_count = 0
                        last_text = curr_text

            if not last_text:
                # Fallback: grab latest anyway
                last_text = await self.eval_js("""
                (() => {
                    const msgs = Array.from(document.querySelectorAll('message-content'));
                    if (!msgs.length) return '';
                    const latest = msgs[msgs.length - 1];
                    return (latest.innerText || latest.textContent || '').trim();
                })()
                """) or ""
                if len(last_text) > last_yielded_len:
                    yield {
                        "type": "delta",
                        "text": last_text[last_yielded_len:],
                        "full_text": last_text
                    }

            # 5. Extract Images and Videos (if generated)
            media_data = await self.eval_js("""
            (async () => {
                const results = { images: [], videos: [] };
                const msgs = Array.from(document.querySelectorAll('message-content'));
                const latest = msgs.length ? msgs[msgs.length - 1] : document.body;
                
                // Images
                const imgs = Array.from(latest.querySelectorAll('img, img[src^="blob:"]'));
                for (const img of imgs) {
                    if (img.naturalWidth < 100 || img.naturalHeight < 100) continue; // skip icons
                    try {
                        const canvas = document.createElement('canvas');
                        canvas.width = img.naturalWidth;
                        canvas.height = img.naturalHeight;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(img, 0, 0);
                        const dataUrl = canvas.toDataURL('image/png');
                        results.images.push({
                            data: dataUrl,
                            width: img.naturalWidth,
                            height: img.naturalHeight,
                            format: 'png'
                        });
                    } catch (e) {}
                }

                // Videos (Google Veo)
                const videos = Array.from(latest.querySelectorAll('video'));
                for (const v of videos) {
                    const src = v.currentSrc || v.src;
                    if (src) {
                        results.videos.push({
                            url: src,
                            width: v.videoWidth || 1280,
                            height: v.videoHeight || 720,
                            duration: v.duration || 10
                        });
                    }
                }
                return results;
            })()
            """, await_promise=True) or {"images": [], "videos": []}

            images_data = media_data.get("images", [])
            videos_data = media_data.get("videos", [])

            # 6. Extract page title and chat id
            meta_info = await self.eval_js("""
            (() => {
                const match = window.location.pathname.match(/\\/app\\/([a-zA-Z0-9]+)/);
                return {
                    url: window.location.href,
                    chat_id: match ? match[1] : ('chat_' + Date.now()),
                    title: document.title.replace(' - Google Gemini', '').trim() || 'Gemini 대화'
                };
            })()
            """) or {}

            yield {
                "type": "done",
                "chat_id": meta_info.get("chat_id", "default"),
                "title": meta_info.get("title", "Gemini 대화"),
                "text": last_text,
                "images": images_data,
                "videos": videos_data
            }

    async def send_prompt(
        self,
        prompt: str,
        new_chat: bool = False,
        chat_id: Optional[str] = None,
        timeout: float = 120.0
    ) -> Dict[str, Any]:
        """
        Non-streaming helper that waits for the full response and returns dict.
        """
        result = {}
        async for event in self.send_prompt_stream(
            prompt=prompt, new_chat=new_chat, chat_id=chat_id, timeout=timeout
        ):
            if event["type"] == "done":
                result = {
                    "chat_id": event["chat_id"],
                    "title": event["title"],
                    "text": event["text"],
                    "images": event.get("images", []),
                    "videos": event.get("videos", []),
                    "timestamp": asyncio.get_event_loop().time()
                }
        return result

bridge = GeminiBridge()
