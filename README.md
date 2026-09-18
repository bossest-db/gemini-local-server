# 🚀 Gemini Local Server & Web Dashboard

> **구글 계정으로 로그인된 Gemini(앱 또는 Chrome 브라우저)를 백엔드 삼아 동작하는 개인용 초경량 API 서버 & 통합 웹 대시보드**  
> 공식 유료 API Key 없이도 웹 세션을 활용하여 **텍스트 대화, Imagen 3 이미지 생성, Google Veo 동영상 생성**을 자유롭게 호출하고, 모든 대화와 미디어를 **내 PC 로컬 디스크에 자동 아카이빙**합니다.

---

## ✨ 핵심 기능

1. **모던 웹 대시보드 (`http://localhost:8000`)**
   * 깔끔한 다크 모드 UI와 실시간 Gemini 연결 상태 감지.
   * Markdown 렌더링, 코드 블록 문법 강조(Syntax Highlighting), 이미지 라이트박스 뷰어 탑재.
   * **HTML5 인라인 비디오 플레이어**: Google Veo로 생성된 1280x720 HD 비디오를 대시보드 내에서 즉시 재생 및 다운로드 가능.

2. **로컬 디스크 자동 아카이빙 (`Documents/Gemini_Archive`)**
   * 대화방별로 폴더가 자동 생성됩니다: `YYYY-MM-DD_대화방제목/`
   * 대화 전문이 Markdown(`conversation.md`)과 메타데이터(`meta.json`)로 자동 기록됩니다.
   * 생성된 고화질 이미지(`.png`)와 고화질 동영상(`.mp4`)이 원본 그대로 로컬 디스크에 자동 다운로드됩니다.

3. **듀얼 API 제공 (REST API & OpenAI 호환 API)**
   * **자체 REST API (`/api/chat`)**: 대화 내용 및 생성된 미디어의 로컬 경로/URL 상세 정보 반환.
   * **OpenAI 호환 API (`/v1/chat/completions`)**: Open WebUI, LibreChat, Dify, LangChain, Cursor 등 기존 OpenAI 연동 앱들과 즉시 연동 가능.
   * **미디어 전용 엔드포인트**: `GET /api/chats/{chat_id}/video`, `GET /api/chats/{chat_id}/image`, `GET /archive/{folder}/{file}`.

---

## 🛠️ 요구 사항 (Prerequisites)

* **운영체제**: Windows 10 / 11 (Linux / macOS에서도 Chrome 디버그 포트로 동일 원리 지원)
* **Python**: 3.10 이상
* **Gemini 환경** (다음 2가지 중 **하나만** 있으면 됩니다):
  * **옵션 A**: Google Gemini 공식 데스크톱 앱 (설치 및 로그인 완료 상태)
  * **옵션 B**: 일반 Google Chrome 브라우저 (`gemini.google.com` 로그인 완료 상태)

---

## 🚀 빠른 시작 (Quick Start)

### 1. 저장소 클론 및 패키지 설치

```bash
git clone https://github.com/bossest-db/gemini-local-server.git
cd gemini-local-server

# 필수 패키지 설치 (FastAPI, Uvicorn, WebSockets, Requests)
pip install -r requirements.txt
```

---

### 2. Gemini 브라우저/앱 디버그 모드로 켜기

서버가 Gemini 세션과 통신할 수 있도록 **원격 디버깅 포트(9223)**를 열고 실행합니다.

#### 🔹 방법 1. 구글 크롬(Chrome)을 사용하는 경우 (추천: Gemini 앱 불필요)
Gemini 데스크톱 앱을 깔지 않아도, 크롬 브라우저만으로 100% 동일하게 동작합니다:
```bash
chrome.exe --remote-debugging-port=9223 https://gemini.google.com
```
> **팁**: 기존 크롬 창이 모두 닫힌 상태에서 실행하거나, 별도의 사용자 데이터 폴더 옵션(`--user-data-dir="C:\ChromeDebug"`)을 추가하여 실행하면 더 안정적입니다:
> ```bash
> chrome.exe --remote-debugging-port=9223 --user-data-dir="C:\ChromeDebug" https://gemini.google.com
> ```

#### 🔹 방법 2. 공식 Gemini 데스크톱 앱을 사용하는 경우
```bash
"%LOCALAPPDATA%\Google\Gemini\Gemini.exe" --remote-debugging-port=9223
```

---

### 3. 서버 실행

#### Windows 원클릭 실행 (`start_server.bat`):
Gemini가 켜져 있지 않으면 자동으로 띄우고 웹 대시보드 브라우저 창까지 한 번에 열어줍니다:
```bat
start_server.bat
```

#### 수동 실행:
```bash
python app.py
```

* 🌐 **웹 대시보드**: [http://localhost:8000](http://localhost:8000)
* ⚡ **Swagger API 문서**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 💻 API 사용 가이드

### 1. 자체 REST API (`POST /api/chat`)

새 대화를 시작하거나 기존 대화방에 이어 질문합니다.

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "바다속에서 흰수염고래가 헤엄치는 영상 만들어줘",
    "new_chat": true
  }'
```

#### 응답 예시:
```json
{
  "success": true,
  "chat_id": "3e6f521cf562dcf2",
  "title": "흰수염고래 영상 제작 요청",
  "text": "동영상이 준비되었습니다!",
  "images": [],
  "videos": [
    {
      "filename": "blue_whale.mp4",
      "url": "/archive/2026-09-18_흰수염고래_영상_제작_요청/blue_whale.mp4",
      "abs_path": "C:\\Users\\yu\\Documents\\Gemini_Archive\\2026-09-18_흰수염고래_영상_제작_요청\\blue_whale.mp4",
      "width": 1280,
      "height": 720
    }
  ],
  "folder_name": "2026-09-18_흰수염고래_영상_제작_요청"
}
```

---

### 2. OpenAI 규격 API (`POST /v1/chat/completions`)

기존 OpenAI 호환 라이브러리를 그대로 사용 가능합니다.

#### Python `openai` 라이브러리 예시:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"
)

response = client.chat.completions.create(
    model="gemini",
    messages=[
        {"role": "user", "content": "파이썬으로 웹 크롤러 만드는 법 알려줘"}
    ]
)

print(response.choices[0].message.content)
```

---

### 3. 생성된 동영상 / 이미지 직접 다운로드 API

* **동영상 바이너리 다운로드**:
  ```bash
  curl -O http://localhost:8000/api/chats/{chat_id}/video
  ```
* **이미지 바이너리 다운로드**:
  ```bash
  curl -O http://localhost:8000/api/chats/{chat_id}/image
  ```

---

## 📁 로컬 아카이브 디렉터리 구조

대화가 진행되거나 미디어가 생성되면 `Documents/Gemini_Archive`에 자동으로 폴더가 분류되어 보관됩니다:

```text
C:\Users\<USER>\Documents\Gemini_Archive\
├── 2026-09-18_맑은_가을_하늘/
│   ├── conversation.md      # 질문 & 답변 마크다운 대화록
│   ├── meta.json            # 대화 메타데이터 (ID, 생성일시 등)
│   └── image_01.png         # 생성된 Imagen 3 고화질 원본 이미지
│
└── 2026-09-18_흰수염고래_영상_제작_요청/
    ├── conversation.md      # 동영상 플레이어 링크가 포함된 대화록
    ├── meta.json
    └── blue_whale.mp4       # 생성된 Google Veo 1280x720 HD 비디오
```

---

## 🔒 보안 및 개인정보

* 본 프로그램은 외부 제3자 서버로 어떠한 개인정보나 대화 데이터를 전송하지 않습니다.
* 모든 통신은 사용자 로컬 PC(`127.0.0.1:9223` CDP 프로토콜)와 로컬 FastAPI 서버(`localhost:8000`) 사이에서만 암호화되어 안전하게 처리됩니다.

---

## 📄 라이선스
MIT License
