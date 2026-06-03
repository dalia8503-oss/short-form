# 👷 Safety Short-form Maker

현장 안전수칙 교육용 숏폼 영상을 로컬에서 제작하는 Streamlit 앱입니다.  
외부 AI API를 사용하지 않으며, 사진·자막·효과음 정보가 외부로 전송되지 않습니다.

---

## 주요 기능

- **사진 업로드 & 순서 조정** — 복수 사진 업로드, 드래그 없이 순서 이동 버튼 제공
- **위험유형 × 자막 톤 템플릿** — 고소작업·추락위험·지게차 등 위험유형별, 지시형·경고형 등 톤별 자막 자동 추천
- **이모지 & 효과음 설정** — 사진마다 포인트 이모지와 효과음 개별 지정
- **자막 디자인 옵션** — 위치(상단/중앙/하단), 글자 크기, 배경 투명도 조정
- **배경음악 합성** — BGM 업로드 시 볼륨 조절 후 자동 루프 합성
- **임시저장 & 복원** — 사진 파일과 자막 설정을 임시저장하여 앱 재시작 후 자동 복원
- **제작 이력 기록** — 영상 제작 시 `logs/` 폴더에 JSON 이력 자동 저장

---

## 설치 및 실행

### 요구사항

- Python 3.10 이상
- Windows / macOS / Linux

## 가상환경 생성
python -m venv venv

## 가상환경 실행
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1

### 설치

```bash
pip install -r requirements.txt
```

### 실행

```bash
streamlit run safety-form.py
```

## 가상환경 종료
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Deactivate.ps1

브라우저에서 `http://localhost:8501` 접속

---

## 프로젝트 구조

```
short-form/
├── safety-form.py          # 메인 앱
├── requirements.txt
├── README.md
├── assets/
│   └── sounds/             # 효과음 WAV 파일 (앱 최초 실행 시 자동 생성)
├── logs/                   # 제작 이력 JSON (자동 생성)
└── .streamlit/
    ├── secrets.toml.example
    ├── draft.json          # 임시저장 설정 (자동 생성)
    └── draft_images/       # 임시저장 이미지 (자동 생성)
```

---

## 업로드 보안 주의사항

아래 항목이 포함된 사진은 **업로드 전 반드시 모자이크 처리** 후 사용하세요.

- 직원 얼굴, 사번, 차량번호판
- 설계 도면, 고객사명, 보안 설비 사진

본 앱은 로컬에서만 동작하며 외부 서버로 데이터를 전송하지 않습니다.

---

## 지원 파일 형식

| 구분 | 형식 |
|------|------|
| 사진 | JPG, JPEG, PNG, WEBP, BMP |
| 오디오 | MP3, WAV, OGG, AAC, M4A, FLAC, WMA, OPUS, AIFF |
| 출력 영상 | MP4 (H.264 + AAC) |

---

## 출력 해상도

| 비율 | 해상도 | 용도 |
|------|--------|------|
| 16:9 가로형 | 1920 × 1080 | PPT 와이드, 모니터 |
| 9:16 세로형 | 1080 × 1920 | 휴대폰, 숏폼 플랫폼 |
