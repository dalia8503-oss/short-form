"""
회사 안전 수칙 교육용 숏폼 영상 제작기 (템플릿 기반 / 오프라인 전용)
=======================================================================
- 외부 AI API 미사용 — 사진·자막·효과음 정보가 외부로 전송되지 않습니다.
- 위험유형별 안전문구 템플릿을 선택해 영상을 제작합니다.

사전 설치:
  pip install -r requirements.txt

실행:
  streamlit run safety-form.py
"""

import io
import json
import os
import shutil
import tempfile
import traceback
import wave
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import streamlit as st

try:
    from pilmoji import Pilmoji as _Pilmoji
    _PILMOJI = True
except ImportError:
    _PILMOJI = False

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FFFF"
    "\U00002500-\U000027BF"
    "\U0001F900-\U0001F9FF"
    "\U0000FE0F\U0000200D"
    "\U00002190-\U000021FF]+",
    flags=re.UNICODE,
)

def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()

# ══════════════════════════════════════════════════════════════════════════════
# 데이터 상수
# ══════════════════════════════════════════════════════════════════════════════

SUPPORTED_EXTS  = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SUPPORTED_AUDIO = ["mp3", "wav", "ogg", "aac", "m4a", "flac", "wma", "opus", "aiff"]
DEFAULT_CLIP_SEC   = 3.5
FADE_SEC           = 1.0
AUDIO_FADEOUT_SEC  = 3.0
CAPTION_FONT_SIZE  = 48

ASPECT_RATIO_OPTIONS = {
    "가로형 16:9 — PPT 와이드 (1920×1080)": (1920, 1080),
    "세로형 9:16 — 휴대폰 최적화 (1080×1920)": (1080, 1920),
}

CAPTION_POSITION_OPTIONS = ["상단", "중앙", "하단"]

CAPTION_TONES = ["지시형", "경고형", "질문형", "캠페인형", "감사형"]

# 위험유형별 안전문구 템플릿
SAFETY_TEMPLATES: dict = {
    "고소작업": {
        "recommended_emoji":    "🪜",
        "recommended_sfx_name": "짧은 경고음",
        "recommended_sfx_file": "warning_beep.wav",
        "captions": {
            "지시형":   ["안전벨트 체결 확인!", "작업발판 상태 확인!", "난간 없는 곳 접근 금지!", "고소작업 전 3초 확인!"],
            "경고형":   ["추락위험, 한순간도 방심 금지! ⚠️", "안전벨트 없이 작업 절대 금지! ⚠️", "발 아래 위험, 반드시 확인하세요 ⚠️"],
            "질문형":   ["지금 안전벨트는 체결되어 있나요?", "작업발판 상태, 확인했나요?", "난간은 설치되어 있나요?"],
            "캠페인형": ["고소작업 전 확인이 모두를 지킵니다", "한 번의 확인이 한 생명을 살립니다"],
            "감사형":   ["안전수칙을 지켜주셔서 감사합니다 🙏", "오늘도 안전하게 작업해 주셔서 감사합니다"],
        },
    },
    "추락위험": {
        "recommended_emoji":    "⚠️",
        "recommended_sfx_name": "짧은 경고음",
        "recommended_sfx_file": "warning_beep.wav",
        "captions": {
            "지시형":   ["추락방지 조치 확인!", "개구부 덮개 상태 확인!", "안전난간 설치 확인!", "한 걸음 전, 추락위험 확인!"],
            "경고형":   ["개구부 주변 추락 위험! ⚠️", "난간 없는 통로 접근 금지 ⚠️", "한 걸음 전, 추락위험 확인!"],
            "질문형":   ["개구부 덮개, 확인했나요?", "안전난간은 설치되어 있나요?", "추락 위험 구간 표시는 됐나요?"],
            "캠페인형": ["작은 부주의가 큰 사고로 이어집니다", "추락 방지, 지금 바로 확인하세요"],
            "감사형":   ["안전난간 설치에 감사드립니다 🙏", "추락 방지 조치를 해주셔서 감사합니다"],
        },
    },
    "지게차/차량": {
        "recommended_emoji":    "🚧",
        "recommended_sfx_name": "주의 알림음",
        "recommended_sfx_file": "alert_short.wav",
        "captions": {
            "지시형":   ["작업반경 접근 금지!", "차량 이동 동선 확인!", "후진 경고음 확인!", "지게차 주변 보행 금지!"],
            "경고형":   ["지게차 후방 사각지대 주의! ⚠️", "차량 이동 중 접근 절대 금지 🔴", "충돌 위험, 안전거리 유지! ⚠️"],
            "질문형":   ["지게차 이동 동선, 확인했나요?", "안전거리는 유지되고 있나요?", "유도자는 배치되어 있나요?"],
            "캠페인형": ["차량과 사람, 함께하는 안전한 현장", "서로를 배려하면 사고가 없습니다"],
            "감사형":   ["안전운행해 주셔서 감사합니다 🙏", "보행자 배려 운전에 감사드립니다"],
        },
    },
    "중량물/인양": {
        "recommended_emoji":    "🏗️",
        "recommended_sfx_name": "짧은 경고음",
        "recommended_sfx_file": "warning_beep.wav",
        "captions": {
            "지시형":   ["인양물 하부 출입 금지!", "줄걸이 상태 확인!", "신호수 배치 확인!", "중량물 이동 전 주변 확인!"],
            "경고형":   ["인양물 낙하 위험! 하부 접근 금지 ⚠️", "중량물 주변 안전거리 유지 🔴", "줄걸이 불량 → 대형사고! ⚠️"],
            "질문형":   ["줄걸이 상태, 확인했나요?", "인양 반경 내 작업자는 대피했나요?", "신호수가 배치되어 있나요?"],
            "캠페인형": ["신중한 인양 작업이 모두를 지킵니다", "확인 또 확인, 안전한 중량물 작업"],
            "감사형":   ["안전하게 인양 작업을 완료해 주셔서 감사합니다 🙏"],
        },
    },
    "협착위험": {
        "recommended_emoji":    "🔧",
        "recommended_sfx_name": "전기 경고음",
        "recommended_sfx_file": "electric_warning.wav",
        "captions": {
            "지시형":   ["손 끼임 위험 주의!", "회전체 접근 금지!", "설비 정지 후 점검!", "방호장치 임의 해제 금지!"],
            "경고형":   ["회전체 근접 절대 금지! ⚠️", "방호장치 없이 작업 금지 🔴", "한순간 방심이 협착사고로 이어집니다 ⚠️"],
            "질문형":   ["방호장치는 설치되어 있나요?", "설비 정지 후 점검하고 있나요?", "잠금·표지 조치는 완료했나요?"],
            "캠페인형": ["방호장치가 나를 지킵니다", "잠금 한 번이 손가락을 지킵니다"],
            "감사형":   ["방호장치를 지켜주셔서 감사합니다 🙏", "안전 점검에 감사드립니다"],
        },
    },
    "전기작업": {
        "recommended_emoji":    "⚡",
        "recommended_sfx_name": "전기 경고음",
        "recommended_sfx_file": "electric_warning.wav",
        "captions": {
            "지시형":   ["전원 차단 후 작업!", "절연보호구 착용 필수!", "충전부 접촉 주의!", "잠금·표지 후 작업하세요!"],
            "경고형":   ["감전사고, 생명을 위협합니다 ⚠️", "충전부 접촉 절대 금지 ⚡", "전원 차단 없이 작업 절대 금지 🔴"],
            "질문형":   ["전원은 차단했나요?", "절연장갑은 착용했나요?", "잠금·표지 조치는 완료했나요?"],
            "캠페인형": ["전기작업, 확인에서 안전이 시작됩니다", "절연보호구가 생명을 지킵니다"],
            "감사형":   ["안전하게 전기작업을 완료해 주셔서 감사합니다 🙏"],
        },
    },
    "화기작업": {
        "recommended_emoji":    "🔥",
        "recommended_sfx_name": "주의 알림음",
        "recommended_sfx_file": "alert_short.wav",
        "captions": {
            "지시형":   ["주변 가연물 제거 확인!", "소화기 비치 확인!", "불티 비산 방지 조치!", "화기작업 허가 확인!"],
            "경고형":   ["불티 하나가 대형화재로! ⚠️", "가연물 제거 없이 화기작업 금지 🔥", "화재 위험! 소화기 위치 확인 ⚠️"],
            "질문형":   ["화기작업 허가는 받았나요?", "주변 가연물은 제거됐나요?", "소화기는 비치되어 있나요?"],
            "캠페인형": ["화기작업 전 확인이 화재를 막습니다", "한 번의 점검이 현장을 지킵니다"],
            "감사형":   ["안전하게 화기작업을 완료해 주셔서 감사합니다 🙏"],
        },
    },
    "밀폐공간": {
        "recommended_emoji":    "🚨",
        "recommended_sfx_name": "짧은 사이렌",
        "recommended_sfx_file": "siren_short.wav",
        "captions": {
            "지시형":   ["작업 전 환기 필수!", "산소농도 측정 확인!", "감시자 배치 확인!", "구조장비 준비 확인!"],
            "경고형":   ["산소결핍 위험, 즉시 대피·신고!", "밀폐공간 무단 진입 절대 금지 🚨", "유해가스 위험, 반드시 측정 후 진입 ⚠️"],
            "질문형":   ["산소농도는 측정했나요?", "감시자는 배치됐나요?", "구조장비는 준비됐나요?"],
            "캠페인형": ["확인 후 진입이 생명을 지킵니다", "밀폐공간, 준비 없이는 절대 진입 금지"],
            "감사형":   ["안전하게 밀폐공간 작업을 완료해 주셔서 감사합니다 🙏"],
        },
    },
    "미끄럼/전도": {
        "recommended_emoji":    "⚠️",
        "recommended_sfx_name": "주의 알림음",
        "recommended_sfx_file": "alert_short.wav",
        "captions": {
            "지시형":   ["젖은 바닥 주의!", "통로 장애물 제거!", "미끄럼 방지 조치 확인!", "넘어짐 위험, 즉시 정리!"],
            "경고형":   ["젖은 바닥 미끄럼 위험! ⚠️", "통로 장애물 → 넘어짐 사고! ⚠️", "미끄럼 방지 없이 통행 금지 🔴"],
            "질문형":   ["바닥 상태, 확인했나요?", "통로 장애물은 제거했나요?", "미끄럼 방지 조치는 됐나요?"],
            "캠페인형": ["깨끗한 통로가 안전한 현장입니다", "미끄럼 방지 한 번이 넘어짐을 막습니다"],
            "감사형":   ["통로 정리에 감사드립니다 🙏", "미끄럼 방지 조치를 해주셔서 감사합니다"],
        },
    },
    "정리정돈": {
        "recommended_emoji":    "✅",
        "recommended_sfx_name": "확인 완료음",
        "recommended_sfx_file": "check_done.wav",
        "captions": {
            "지시형":   ["통로 적치물 즉시 제거!", "작업 후 정리정돈 필수!", "공구는 제자리에 보관!", "깨끗한 현장이 안전한 현장!"],
            "경고형":   ["어지러운 현장이 사고를 부릅니다 ⚠️", "통로 적치물은 사고 위험을 높입니다 ⚠️", "정리되지 않은 현장 = 위험한 현장 🔴"],
            "질문형":   ["작업 후 정리정돈은 했나요?", "통로에 장애물은 없나요?", "공구는 제자리에 보관됐나요?"],
            "캠페인형": ["정리된 현장이 안전한 내일을 만듭니다", "깨끗한 현장, 안전한 현장"],
            "감사형":   ["현장 정리에 감사드립니다 🙏", "깨끗한 작업 환경을 유지해 주셔서 감사합니다"],
        },
    },
    "보호구 착용": {
        "recommended_emoji":    "👷",
        "recommended_sfx_name": "확인 완료음",
        "recommended_sfx_file": "check_done.wav",
        "captions": {
            "지시형":   ["안전모 착용 확인!", "보안경 착용 필수!", "안전화 착용 상태 확인!", "보호구는 생명선입니다!"],
            "경고형":   ["보호구 없이 작업 절대 금지! ⚠️", "안전모 없이 현장 진입 금지 🔴", "보호구 미착용 → 즉각 착용 ⚠️"],
            "질문형":   ["안전모는 착용했나요?", "보안경은 착용했나요?", "안전화 상태는 양호한가요?"],
            "캠페인형": ["보호구가 나를 지킵니다", "보호구 착용, 습관이 생명을 지킵니다"],
            "감사형":   ["보호구를 착용해 주셔서 감사합니다 🙏", "안전수칙을 지켜주셔서 감사합니다"],
        },
    },
    "비상구/소화기": {
        "recommended_emoji":    "🚨",
        "recommended_sfx_name": "짧은 사이렌",
        "recommended_sfx_file": "siren_short.wav",
        "captions": {
            "지시형":   ["비상구 앞 적치 금지!", "소화기 위치 확인!", "대피로 확보 상태 확인!", "비상시 이동 동선 확인!"],
            "경고형":   ["비상구 막힘 = 대피 불가! ⚠️", "소화기 위치를 미리 확인하세요 🔴", "대피로 확보, 지금 당장 확인 ⚠️"],
            "질문형":   ["비상구 위치, 알고 있나요?", "소화기는 어디에 있나요?", "대피로는 확보되어 있나요?"],
            "캠페인형": ["비상구 확인이 생명을 지킵니다", "소화기 위치, 지금 확인하세요"],
            "감사형":   ["비상구 관리에 감사드립니다 🙏", "소화기 점검에 감사드립니다"],
        },
    },
    "좋은 안전사례": {
        "recommended_emoji":    "🙏",
        "recommended_sfx_name": "확인 완료음",
        "recommended_sfx_file": "check_done.wav",
        "captions": {
            "지시형":   ["오늘도 안전수칙을 지켜주세요!", "안전한 현장을 함께 만들어요!", "위험 발견 시 즉시 신고!"],
            "경고형":   ["방심은 금물! 오늘도 안전하게 ⚠️"],
            "질문형":   ["오늘 안전수칙 확인하셨나요?", "위험요소 발견했나요?"],
            "캠페인형": ["오늘도 안전하게 작업해 주셔서 감사합니다", "작은 실천이 큰 사고를 막습니다", "함께 지키는 안전, 모두의 내일입니다", "꼼꼼한 점검이 안전한 하루를 만듭니다"],
            "감사형":   ["안전하게 작업해 주셔서 진심으로 감사합니다 🙏", "꼼꼼한 안전 점검에 깊이 감사드립니다 🙏", "안전수칙을 솔선수범해 주셔서 감사합니다 👏"],
        },
    },
    "기타": {
        "recommended_emoji":    "✅",
        "recommended_sfx_name": "주의 알림음",
        "recommended_sfx_file": "alert_short.wav",
        "captions": {
            "지시형":   ["위험요소 발견 즉시 공유!", "작업 전 안전수칙 확인!", "무리한 작업은 멈추세요!", "안전은 확인에서 시작됩니다!"],
            "경고형":   ["방심이 사고를 부릅니다 ⚠️", "위험을 무시하면 사고가 납니다 🔴"],
            "질문형":   ["지금 안전한가요?", "위험요소는 없나요?", "안전수칙은 확인했나요?"],
            "캠페인형": ["안전은 모두의 책임입니다", "함께 만드는 안전한 현장"],
            "감사형":   ["안전에 협조해 주셔서 감사합니다 🙏", "안전수칙을 지켜주셔서 감사합니다"],
        },
    },
}

# 이모지 팩
EMOJI_PACK: dict = {
    "경고":     ["⚠️", "🔴", "🚨", "⛔", "🚫"],
    "보호구":   ["👷", "🦺", "🥽", "🧤", "👢"],
    "작업위험": ["🪜", "⚡", "🔥", "🚧", "🏗️", "🔧"],
    "확인/점검":["✅", "📋", "🔍", "🛠️"],
    "캠페인":   ["🙏", "💪", "👏", "🌱"],
}

# 위험유형별 추천 이모지 매핑
RISK_EMOJI_MAP: dict = {
    "고소작업":     "🪜",
    "추락위험":     "⚠️",
    "지게차/차량":  "🚧",
    "중량물/인양":  "🏗️",
    "협착위험":     "🔧",
    "전기작업":     "⚡",
    "화기작업":     "🔥",
    "밀폐공간":     "🚨",
    "미끄럼/전도":  "⚠️",
    "정리정돈":     "✅",
    "보호구 착용":  "👷",
    "비상구/소화기":"🚨",
    "좋은 안전사례":"🙏",
    "기타":         "✅",
}

# 효과음 설정
SFX_CONFIG: dict = {
    "없음":          {"file": None,                   "desc": "효과음 없음"},
    "짧은 경고음":   {"file": "warning_beep.wav",     "desc": "짧고 강한 경고 비프"},
    "주의 알림음":   {"file": "alert_short.wav",      "desc": "부드러운 주의 알림"},
    "확인 완료음":   {"file": "check_done.wav",       "desc": "작업 완료 확인음"},
    "짧은 사이렌":   {"file": "siren_short.wav",      "desc": "짧은 경고 사이렌"},
    "전기 경고음":   {"file": "electric_warning.wav", "desc": "전기 위험 경고음"},
    "금지 알림음":   {"file": "deny_alert.wav",       "desc": "접근 금지 알림음"},
}

KOREAN_FONT_PATHS = [
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\NanumGothic.ttf",
    r"C:\Windows\Fonts\gulim.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]

ASSETS_DIR       = Path(__file__).resolve().parent / "assets" / "sounds"
LOGS_DIR         = Path(__file__).resolve().parent / "logs"
DRAFT_FILE       = Path(__file__).resolve().parent / ".streamlit" / "draft.json"
DRAFT_IMAGES_DIR = Path(__file__).resolve().parent / ".streamlit" / "draft_images"


# ══════════════════════════════════════════════════════════════════════════════
# 효과음 생성 
# ══════════════════════════════════════════════════════════════════════════════

def _write_wav(path: Path, samples: np.ndarray, sr: int = 44100) -> None:
    pcm = (samples * 32767).astype(np.int16)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())

def generate_sfx_files() -> list:
    failed = []
    try:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return [{"file": "assets/sounds 폴더 생성", "error": str(e)}]

    sr = 44100

    specs = {
        "warning_beep.wav": lambda: _square(800, 0.3, sr),
        "alert_short.wav":  lambda: _sweep(600, 900, 0.4, sr),
        "check_done.wav":   lambda: _double_beep(880, 1046, sr),
        "siren_short.wav":  lambda: _siren(400, 900, 0.6, sr),
        "electric_warning.wav": lambda: _buzz(1200, 0.5, sr),
        "deny_alert.wav":   lambda: _sweep(700, 400, 0.35, sr),
    }

    for fname, builder in specs.items():
        fpath = ASSETS_DIR / fname
        if not fpath.exists():
            try:
                samples = builder()
                _write_wav(fpath, samples, sr)
            except Exception as e:
                failed.append({"file": fname, "error": str(e)})

    return failed

def _envelope(n: int, sr: int, attack_ms=10, release_ms=20) -> np.ndarray:
    env = np.ones(n)
    atk = int(sr * attack_ms / 1000)
    rel = int(sr * release_ms / 1000)
    env[:atk]  = np.linspace(0, 1, atk)
    env[-rel:] = np.linspace(1, 0, rel)
    return env

def _square(freq: float, dur: float, sr: int) -> np.ndarray:
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    s = np.sign(np.sin(2 * np.pi * freq * t)) * 0.4
    return s * _envelope(len(s), sr)

def _sweep(f0: float, f1: float, dur: float, sr: int) -> np.ndarray:
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    freq = np.linspace(f0, f1, len(t))
    phase = np.cumsum(2 * np.pi * freq / sr)
    s = np.sin(phase) * 0.5
    return s * _envelope(len(s), sr)

def _double_beep(f0: float, f1: float, sr: int) -> np.ndarray:
    b0 = _square(f0, 0.15, sr)
    gap = np.zeros(int(sr * 0.08))
    b1 = _square(f1, 0.15, sr)
    return np.concatenate([b0, gap, b1])

def _siren(f_lo: float, f_hi: float, dur: float, sr: int) -> np.ndarray:
    up   = _sweep(f_lo, f_hi, dur / 2, sr)
    down = _sweep(f_hi, f_lo, dur / 2, sr)
    return np.concatenate([up, down])

def _buzz(freq: float, dur: float, sr: int) -> np.ndarray:
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    s = (np.sin(2 * np.pi * freq * t) +
         0.3 * np.sin(2 * np.pi * freq * 2 * t)) * 0.35
    return s * _envelope(len(s), sr)

def get_sfx_bytes(sfx_name: str) -> Optional[bytes]:
    cfg = SFX_CONFIG.get(sfx_name, {})
    fname = cfg.get("file")
    if not fname:
        return None
    path = ASSETS_DIR / fname
    if path.exists():
        return path.read_bytes()
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 이미지 유틸리티
# ══════════════════════════════════════════════════════════════════════════════

def get_font(size: int = 48) -> ImageFont.FreeTypeFont:
    for p in KOREAN_FONT_PATHS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()

def letterbox(img: Image.Image, size: tuple) -> Image.Image:
    rgb = img.convert("RGB")
    scale = min(size[0] / rgb.width, size[1] / rgb.height)
    new_w = max(1, int(rgb.width * scale))
    new_h = max(1, int(rgb.height * scale))
    rgb = rgb.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", size, (0, 0, 0))
    canvas.paste(rgb, ((size[0] - new_w) // 2, (size[1] - new_h) // 2))
    return canvas

def wrap_text(text: str, font: ImageFont.FreeTypeFont,
              max_px: int, draw: ImageDraw.Draw) -> list:
    words, lines, buf = text.split(), [], ""
    for word in words:
        trial = (buf + " " + word).strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_px:
            buf = trial
        else:
            if buf:
                lines.append(buf)
            buf = word
    if buf:
        lines.append(buf)
    return lines or [text]

def append_single_emoji(text: str, emoji: str) -> str:
    if not emoji:
        return text.strip()
    if text.strip().endswith(emoji):
        return text.strip()
    return f"{text.strip()} {emoji} "

def stamp_caption(img: Image.Image, caption: str, font: ImageFont.FreeTypeFont,
                  caption_bg_alpha: int = 200, position: str = "하단") -> np.ndarray:
    """사진 위에 자막을 세련되게 오버레이(Rounded Rectangle)"""
    base     = img.convert("RGBA")
    tmp_draw = ImageDraw.Draw(base)
    # 텍스트가 박스 밖으로 나가지 않도록 여백 설정
    max_text_width = base.width - 120
    lines    = wrap_text(caption, font, max_text_width, tmp_draw)

    lh  = font.size + 16
    th  = len(lines) * lh
    pad_x, pad_y = 80, 24

    # 제일 긴 텍스트 줄의 길이 구하기
    max_w = 0
    for line in lines:
        w = tmp_draw.textbbox((0, 0), _strip_emoji(line), font=font)[2]
        if w > max_w: max_w = w

    box_w = max_w + pad_x * 2
    box_h = th + pad_y * 2

    # 자막 상자 X좌표 (가운데 정렬)
    x0 = (base.width - box_w) // 2
    
    # 설정에 따른 Y좌표 위치 결정
    if position == "상단":
        y0 = int(base.height * 0.1)
    elif position == "중앙":
        y0 = (base.height - box_h) // 2
    else: # 하단
        y0 = int(base.height * 0.85) - box_h

    # 반투명 라운드 배경 박스
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    
    # Pillow 8.2.0 이상에서 지원하는 rounded_rectangle 사용
    try:
        od.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=20, fill=(0, 0, 0, caption_bg_alpha))
    except AttributeError:
        # 구버전 Pillow 대비 폴백
        od.rectangle([x0, y0, x0 + box_w, y0 + box_h], fill=(0, 0, 0, caption_bg_alpha))
        
    base = Image.alpha_composite(base, overlay)

    # 글씨 렌더링
    draw = ImageDraw.Draw(base)
    offsets = [(-2,-2),(-2,0),(-2,2),(0,-2),(0,2),(2,-2),(2,0),(2,2)]

    pilmoji_ok = False
    if _PILMOJI:
        try:
            with _Pilmoji(base) as pj:
                for i, line in enumerate(lines):
                    bw = draw.textbbox((0, 0), line, font=font)[2]
                    x  = (base.width - bw) // 2
                    y  = y0 + pad_y + i * lh
                    for dx, dy in offsets:
                        pj.text((x+dx, y+dy), line, font=font, fill=(0, 0, 0, 255))
                    pj.text((x, y), line, font=font, fill=(255, 255, 255, 255))
            pilmoji_ok = True
        except Exception:
            pilmoji_ok = False

    if not pilmoji_ok:
        for i, line in enumerate(lines):
            render_line = _strip_emoji(line)
            bw = draw.textbbox((0, 0), render_line, font=font)[2]
            x  = (base.width - bw) // 2
            y  = y0 + pad_y + i * lh
            for dx, dy in offsets:
                draw.text((x+dx, y+dy), render_line, font=font, fill=(0, 0, 0, 255))
            draw.text((x, y), render_line, font=font, fill=(255, 255, 255, 255))

    return np.array(base.convert("RGB"))


# ══════════════════════════════════════════════════════════════════════════════
# 영상 제작
# ══════════════════════════════════════════════════════════════════════════════

def build_slideshow(
    paths: list,
    captions: list,
    clip_sec: float,
    video_size: tuple,
    sfx_name_list: list,
    sfx_volume: float = 0.7,
    caption_bg_alpha: int = 200,
    caption_font_size: int = 48,
    caption_position: str = "하단",
    fade_sec: float = FADE_SEC,
    rotations: list = None,
    on_progress: Optional[Callable] = None,
) -> str:
    from moviepy import ImageClip, AudioFileClip
    from moviepy.audio.fx import MultiplyVolume

    font    = get_font(caption_font_size)
    clips   = []
    has_sfx = any(n and n != "없음" for n in sfx_name_list)
    fps     = 24

    for i, (path, caption) in enumerate(zip(paths, captions)):
        if on_progress:
            on_progress(i / len(paths))

        with Image.open(path) as raw:
            rot_deg = rotations[i] if rotations and i < len(rotations) else 0
            if rot_deg:
                raw = raw.rotate(-rot_deg, expand=True)
            framed = letterbox(raw, video_size)

        # 캡션 생성 시 위치 옵션 적용
        arr  = stamp_caption(framed, caption, font, caption_bg_alpha, position=caption_position)
        clip = ImageClip(arr, duration=clip_sec)

        sfx_name = sfx_name_list[i] if i < len(sfx_name_list) else "없음"
        if sfx_name and sfx_name != "없음":
            sfx_file = ASSETS_DIR / SFX_CONFIG[sfx_name]["file"]
            if sfx_file.exists():
                try:
                    sfx = AudioFileClip(str(sfx_file))
                    sfx = sfx.subclipped(0, min(sfx.duration, clip_sec))
                    if sfx_volume != 1.0:
                        sfx = sfx.with_effects([MultiplyVolume(sfx_volume)])
                    clip = clip.with_audio(sfx)
                except Exception:
                    pass

        clips.append(clip)

    n_fade   = max(1, int(fade_sec * fps))
    n_hold   = max(1, int(clip_sec * fps) - n_fade)
    arrays   = []
    for i, clip in enumerate(clips):
        frame = clip.get_frame(0)
        arrays.append(frame)

    all_frames = []
    for i, arr in enumerate(arrays):
        all_frames.extend([arr] * n_hold)
        if i < len(arrays) - 1:
            nxt = arrays[i + 1]
            for f in range(n_fade):
                alpha   = f / n_fade
                blended = (arr * (1 - alpha) + nxt * alpha).astype(np.uint8)
                all_frames.append(blended)

    from moviepy import ImageSequenceClip
    merged = ImageSequenceClip(all_frames, fps=fps)

    if has_sfx:
        from moviepy import CompositeAudioClip
        audio_clips = []
        t = 0.0
        for i, clip in enumerate(clips):
            if clip.audio is not None:
                audio_clips.append(clip.audio.with_start(t))
            t += n_hold / fps + (n_fade / fps if i < len(clips) - 1 else 0)
        if audio_clips:
            merged = merged.with_audio(CompositeAudioClip(audio_clips))

    out = tempfile.NamedTemporaryFile(suffix="_slide.mp4", delete=False).name
    merged.write_videofile(
        out, fps=fps, codec="libx264",
        audio_codec="aac" if has_sfx else None,
        logger=None,
    )
    for c in clips:
        c.close()
    merged.close()

    if on_progress:
        on_progress(1.0)
    return out

def add_bgm(video_path: str, audio_path: str, bgm_volume: float = 0.25) -> str:
    from moviepy import VideoFileClip, AudioFileClip, concatenate_audioclips, CompositeAudioClip
    from moviepy.audio.fx import AudioFadeOut, MultiplyVolume

    video = VideoFileClip(video_path)
    bgm   = AudioFileClip(audio_path)
    vdur  = video.duration

    if bgm.duration < vdur:
        loops = int(np.ceil(vdur / bgm.duration))
        bgm   = concatenate_audioclips([bgm] * loops)
    bgm = bgm.subclipped(0, vdur).with_effects([AudioFadeOut(min(AUDIO_FADEOUT_SEC, vdur))])
    bgm = bgm.with_effects([MultiplyVolume(bgm_volume)])

    if video.audio is not None:
        mixed  = CompositeAudioClip([video.audio, bgm])
        result = video.with_audio(mixed)
    else:
        result = video.with_audio(bgm)

    out = tempfile.NamedTemporaryFile(suffix="_final.mp4", delete=False).name
    result.write_videofile(out, fps=24, codec="libx264", audio_codec="aac", logger=None)
    video.close()
    bgm.close()
    result.close()
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 기타 헬퍼
# ══════════════════════════════════════════════════════════════════════════════

def save_production_log(**kwargs) -> None:
    try:
        LOGS_DIR.mkdir(exist_ok=True)
        now      = datetime.now()
        filename = f"safety_video_log_{now.strftime('%Y%m%d_%H%M%S')}.json"
        log      = {"created_at": now.isoformat(), **kwargs}
        with open(LOGS_DIR / filename, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"⚠️ 제작 이력 저장 실패 (영상 제작에는 영향 없음): {e}")

class DraftImage:
    """UploadedFile과 호환되는 임시저장 이미지 래퍼"""
    def __init__(self, path: Path, name: str = None):
        self._path = path
        self.name = name or path.name
        self._data = None

    def getbuffer(self):
        if self._data is None:
            self._data = self._path.read_bytes()
        return memoryview(self._data)


_DRAFT_PREFIXES = (
    "risk_", "tone_", "tmpl_", "final_cap_", "emoji_",
    "sfx_sel_", "cap_custom_", "_pending_cap_",
    "cap_direct_", "_fp_", "_prev_tmpl_for_emoji_",
    "_cfg_", "_rot_",
)

def save_draft() -> None:
    draft = {}
    for k, v in st.session_state.items():
        if k.startswith(_DRAFT_PREFIXES) or k == "creator_name":
            try:
                json.dumps(v)
                draft[k] = v
            except (TypeError, ValueError):
                pass
    draft["_filenames"]     = st.session_state.get("_order_names", [])
    draft["_order_indices"] = st.session_state.get("_order_indices", [])
    draft["_order_names"]   = st.session_state.get("_order_names", [])
    draft["_saved_at"]      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 이미지 파일을 draft_images 디렉터리에 저장
    image_paths = st.session_state.get("_image_paths", [])
    img_names   = st.session_state.get("_img_cache_names", [])
    if image_paths and img_names:
        try:
            DRAFT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            for old in DRAFT_IMAGES_DIR.glob("*"):
                old.unlink()
            safe_names = []
            for idx, (src, name) in enumerate(zip(image_paths, img_names)):
                safe_name = f"{idx+1:03d}_{Path(name).name}"
                shutil.copy2(src, DRAFT_IMAGES_DIR / safe_name)
                safe_names.append(safe_name)
            draft["_draft_image_names"]     = safe_names
            draft["_draft_image_originals"] = list(img_names)
        except Exception:
            pass

    try:
        DRAFT_FILE.parent.mkdir(exist_ok=True)
        with open(DRAFT_FILE, "w", encoding="utf-8") as f:
            json.dump(draft, f, ensure_ascii=False)
        st.session_state["_draft_saved_at"] = draft["_saved_at"]
    except Exception:
        pass

def load_draft() -> bool:
    if st.session_state.get("_draft_loaded"):
        return False
    st.session_state["_draft_loaded"] = True
    if not DRAFT_FILE.exists():
        return False
    try:
        with open(DRAFT_FILE, encoding="utf-8") as f:
            draft = json.load(f)
        for k, v in draft.items():
            if k not in st.session_state:
                st.session_state[k] = v
        st.session_state.setdefault("_draft_filenames", draft.get("_filenames", []))

        # 임시저장 이미지 복원
        safe_names = draft.get("_draft_image_names", [])
        orig_names = draft.get("_draft_image_originals", safe_names)
        draft_imgs = []
        for safe, orig in zip(safe_names, orig_names):
            p = DRAFT_IMAGES_DIR / safe
            if p.exists():
                draft_imgs.append(DraftImage(p, orig))
        if draft_imgs:
            st.session_state["_draft_images"] = draft_imgs

        return bool(draft)
    except Exception:
        return False

def clear_draft() -> None:
    try:
        DRAFT_FILE.unlink(missing_ok=True)
        shutil.rmtree(DRAFT_IMAGES_DIR, ignore_errors=True)
    except Exception:
        pass

def make_emoji_json() -> bytes:
    return json.dumps(EMOJI_PACK, ensure_ascii=False, indent=2).encode("utf-8")

def make_emoji_txt() -> bytes:
    lines = ["안전교육 숏폼 이모지 팩\n" + "=" * 30]
    for cat, emojis in EMOJI_PACK.items():
        lines.append(f"\n[{cat}]")
        lines.append("  " + "  ".join(emojis))
    return "\n".join(lines).encode("utf-8")

def make_template_json() -> bytes:
    return json.dumps(SAFETY_TEMPLATES, ensure_ascii=False, indent=2).encode("utf-8")

def make_template_txt() -> bytes:
    lines = ["안전교육 숏폼 자막 템플릿\n" + "=" * 30]
    for risk, data in SAFETY_TEMPLATES.items():
        lines.append(f"\n{'─'*30}\n[{risk}]")
        lines.append(f"추천 이모지: {data['recommended_emoji']}  추천 효과음: {data['recommended_sfx_name']} ({data['recommended_sfx_file']})")
        for tone, caps in data["captions"].items():
            lines.append(f"  ▸ {tone}")
            for c in caps:
                lines.append(f"    - {c}")
    return "\n".join(lines).encode("utf-8")

def make_sfx_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for cfg in SFX_CONFIG.values():
            fname = cfg.get("file")
            if fname:
                fpath = ASSETS_DIR / fname
                if fpath.exists():
                    zf.write(fpath, fname)
    return buf.getvalue()

def dump_uploads(files) -> tuple:
    d, paths = tempfile.mkdtemp(), []
    for f in files:
        dest = os.path.join(d, f.name)
        with open(dest, "wb") as fp:
            fp.write(f.getbuffer())
        paths.append(dest)
    return d, paths


# ══════════════════════════════════════════════════════════════════════════════
# Streamlit UI — 메인
# ══════════════════════════════════════════════════════════════════════════════

def _check_password() -> bool:
    if st.session_state.get("_authenticated"):
        return True

    st.title("🔒 접근 제한")
    pw = st.text_input("비밀번호를 입력하세요", type="password", key="_pw_input")
    if st.button("확인"):
        correct = st.secrets.get("APP_PASSWORD", "")
        if pw == correct:
            st.session_state["_authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    return False


def main():
    st.set_page_config(
        page_title="👷 Safety short-form maker",
        page_icon="👷",
        layout="wide",
    )

    if not _check_password():
        st.stop()

    draft_restored = load_draft()
    sfx_failed = generate_sfx_files()
    if sfx_failed:
        st.warning("⚠️ 일부 기본 효과음 생성에 실패했습니다. 폴더 권한 또는 실행 위치를 확인하세요.")

    if draft_restored:
        saved_files = st.session_state.get("_draft_filenames", [])
        tip = f" 같은 파일({', '.join(saved_files[:2])}{'...' if len(saved_files) > 2 else ''})을 업로드하면 자막 설정이 자동 복원됩니다." if saved_files else ""
        st.toast(f"💾 이전 작업 내용이 복원되었습니다.{tip}")

    st.title("👷 Safety short-form maker")
    st.caption("외부 AI API를 사용하지 않으며, 사내 보안을 유지하는 로컬 템플릿 기반 제작기입니다.")

    with st.expander("📋 업로드 전 보안 안내 — 반드시 확인하세요", expanded=False):
        st.warning(
            "**업로드 금지 항목**\n"
            "- 직원 얼굴, 사번, 차량번호판\n"
            "- 설계 도면, 고객사명, 보안 설비 사진\n\n"
            "**조치 사항**\n"
            "- 해당 항목이 포함된 경우 업로드 전 **모자이크 처리** 후 사용하세요.\n"
            "- 회사 보안정책 및 개인정보 보호 기준을 준수하세요.\n\n"
        )

    # ══════════════════════════════════════════════════════
    # 사이드바 설정
    # ══════════════════════════════════════════════════════
    with st.sidebar:
        st.header("⚙️ 영상 기본 설정")

        aspect_label = st.radio("비율 (해상도)", options=list(ASPECT_RATIO_OPTIONS.keys()), index=0, key="_cfg_aspect")
        video_size = ASPECT_RATIO_OPTIONS[aspect_label]

        clip_sec = st.slider("사진당 재생 시간 (초)", 2.0, 6.0, DEFAULT_CLIP_SEC, 0.5, key="_cfg_clip_sec")

        st.subheader("텍스트 및 디자인")
        caption_position = st.selectbox("자막 위치", CAPTION_POSITION_OPTIONS, index=2, key="_cfg_cap_pos")
        caption_bg_alpha = st.slider("자막 배경 투명도 (박스)", 0, 255, 180, 5, key="_cfg_cap_bg")
        caption_font_size = st.slider("자막 글자 크기", 32, 72, CAPTION_FONT_SIZE, 2, key="_cfg_cap_sz")
        auto_emoji = st.checkbox("이모지 자막 끝 자동 삽입", value=True, key="_cfg_auto_emoji")

        st.divider()
        fade_sec = st.slider("사진 전환 페이드 (초)", 0.3, 2.0, FADE_SEC, 0.1, key="_cfg_fade")
        sfx_volume = st.slider("효과음 볼륨", 0.0, 1.0, 0.7, 0.05, key="_cfg_sfx_vol")
        bgm_volume = st.slider("배경음악 볼륨", 0.0, 1.0, 0.25, 0.05, key="_cfg_bgm_vol")

        st.divider()
        st.markdown("**📝 제작자 정보**")
        creator_name = st.text_input("제작자명 (로그 기록용)", placeholder="소속 및 성명", key="creator_name")

        st.divider()
        if st.button("💾 임시저장", use_container_width=True):
            save_draft()
            st.toast("💾 임시저장이 완료되었습니다!")
        saved_at = st.session_state.get("_draft_saved_at")
        if saved_at:
            st.caption(f"마지막 저장: {saved_at}")

        st.divider()
        if st.button("🗑️ 모든 설정 초기화", use_container_width=True):
            clear_draft()
            for k in list(st.session_state.keys()):
                if k.startswith(_DRAFT_PREFIXES) or k in (
                    "creator_name", "_draft_filenames", "_draft_loaded",
                    "_order_indices", "_order_names", "_draft_saved_at",
                ):
                    del st.session_state[k]
            st.rerun()

    # ══════════════════════════════════════════════════════
    # 탭 레이아웃 적용
    # ══════════════════════════════════════════════════════
    tab1, tab2, tab3 = st.tabs(["📸 1. 사진 및 자막 설정", "🎵 2. 오디오 및 리소스", "🎬 3. 영상 제작"])

    # ──────────────────────────────────────────────────────
    # TAB 1: 사진 업로드 및 자막 설정
    # ──────────────────────────────────────────────────────
    with tab1:
        st.subheader("① 현장·작업 사진 업로드")
        up_imgs = st.file_uploader(
            "사진을 드래그하거나 클릭해 업로드하세요 (복수 선택 가능)",
            type=["jpg", "jpeg", "png", "webp", "bmp"],
            accept_multiple_files=True,
            key="img_upload",
        )

        # 새 파일이 업로드되면 임시저장 이미지 세션 해제, 없으면 임시저장 이미지 사용
        if up_imgs:
            if "_draft_images" in st.session_state:
                del st.session_state["_draft_images"]
        else:
            draft_imgs = st.session_state.get("_draft_images", [])
            if draft_imgs:
                up_imgs = draft_imgs
                st.info(
                    f"📂 임시저장에서 **{len(draft_imgs)}장**의 사진이 복원되었습니다. "
                    "새 사진을 업로드하면 교체됩니다."
                )

        upload_names = [f.name for f in up_imgs] if up_imgs else []
        if st.session_state.get("_order_names") != upload_names:
            st.session_state["_order_names"]   = upload_names
            st.session_state["_order_indices"] = list(range(len(up_imgs))) if up_imgs else []
            st.session_state.pop("_img_cache_names", None)

        if up_imgs:
            st.success(f"✅ {len(up_imgs)}장 업로드됨")
            with st.expander("🔄 사진 순서 조정", expanded=False):
                order  = list(st.session_state["_order_indices"])
                n_cols = 4

                for row_start in range(0, len(up_imgs), n_cols):
                    cols = st.columns(n_cols)
                    for ci in range(n_cols):
                        idx = row_start + ci
                        if idx >= len(up_imgs):
                            break
                        orig = order[idx]
                        rot = st.session_state.get(f"_rot_{orig}", 0)
                        with cols[ci]:
                            try:
                                img_buf = io.BytesIO(up_imgs[orig].getbuffer())
                                preview = Image.open(img_buf)
                                if rot:
                                    preview = preview.rotate(-rot, expand=True)
                                st.image(preview, use_container_width=True)
                            except Exception:
                                st.image(up_imgs[orig], use_container_width=True)
                            st.caption(f"{idx + 1}번" + (f"  {rot}°" if rot else ""))
                            b1, b2, b3, b4 = st.columns(4)
                            with b1:
                                if idx > 0 and st.button("◀", key=f"mv_up_{idx}", use_container_width=True):
                                    order[idx - 1], order[idx] = order[idx], order[idx - 1]
                                    st.session_state["_order_indices"] = order
                                    st.session_state.pop("_img_cache_names", None)
                                    st.rerun()
                            with b2:
                                if idx < len(up_imgs) - 1 and st.button("▶", key=f"mv_dn_{idx}", use_container_width=True):
                                    order[idx], order[idx + 1] = order[idx + 1], order[idx]
                                    st.session_state["_order_indices"] = order
                                    st.session_state.pop("_img_cache_names", None)
                                    st.rerun()
                            with b3:
                                if st.button("↺", key=f"rot_ccw_{idx}", use_container_width=True):
                                    st.session_state[f"_rot_{orig}"] = (rot - 90) % 360
                                    st.session_state.pop("_img_cache_names", None)
                                    st.rerun()
                            with b4:
                                if st.button("↻", key=f"rot_cw_{idx}", use_container_width=True):
                                    st.session_state[f"_rot_{orig}"] = (rot + 90) % 360
                                    st.session_state.pop("_img_cache_names", None)
                                    st.rerun()

        st.divider()
        st.subheader("② 사진별 안전 자막 적용")
        risk_types      = list(SAFETY_TEMPLATES.keys())
        final_captions  = []
        final_sfx_names = []
        final_emojis    = []
        image_paths     = []

        if not up_imgs:
            st.info("사진을 먼저 업로드해주세요.")
        else:
            order_indices = st.session_state.get("_order_indices", list(range(len(up_imgs))))
            sorted_imgs   = [up_imgs[i] for i in order_indices]

            if st.session_state.get("_img_cache_names") != [f.name for f in sorted_imgs]:
                prev_dir = st.session_state.pop("_tmp_img_dir", None)
                if prev_dir: shutil.rmtree(prev_dir, ignore_errors=True)
                tmp_dir, image_paths = dump_uploads(sorted_imgs)
                st.session_state["_tmp_img_dir"]     = tmp_dir
                st.session_state["_image_paths"]     = image_paths
                st.session_state["_img_cache_names"] = [f.name for f in sorted_imgs]
            else:
                image_paths = st.session_state["_image_paths"]

            all_emoji_flat = [e for emojis in EMOJI_PACK.values() for e in emojis]
            sfx_options    = list(SFX_CONFIG.keys())

            for i, img_path in enumerate(image_paths):
                with st.expander(f"📷 {i+1}번 사진 — 자막 설정", expanded=(i == 0)):
                    col_img, col_set = st.columns([1, 2])
                    with col_img:
                        orig_idx = order_indices[i]
                        rot_preview = st.session_state.get(f"_rot_{orig_idx}", 0)
                        if rot_preview:
                            with Image.open(img_path) as _pv:
                                _pv = _pv.rotate(-rot_preview, expand=True)
                                st.image(_pv, use_container_width=True)
                        else:
                            st.image(img_path, use_container_width=True)
                    with col_set:
                        c1, c2 = st.columns(2)
                        with c1:
                            risk = st.selectbox(
                                "위험유형", risk_types, key=f"risk_{i}",
                                index=risk_types.index(st.session_state.get(f"risk_{i}", risk_types[0])) if st.session_state.get(f"risk_{i}") in risk_types else 0,
                            )
                        with c2:
                            tone = st.selectbox("자막 톤", CAPTION_TONES, key=f"tone_{i}")

                        template_data = SAFETY_TEMPLATES.get(risk, {})
                        tone_captions = template_data.get("captions", {}).get(tone, [])

                        selected_template = st.selectbox("추천 템플릿", ["(직접 입력)"] + tone_captions, key=f"tmpl_{i}")

                        # 직접 입력 전용 필드 (선택 시에만 표시)
                        if selected_template == "(직접 입력)":
                            st.text_input(
                                "✍️ 직접 입력",
                                key=f"cap_direct_{i}",
                                placeholder="자막을 직접 입력하세요",
                            )
                            source_text = _strip_emoji(
                                st.session_state.get(f"cap_direct_{i}", "")
                            ).strip()
                        else:
                            source_text = selected_template

                        rec_emoji = RISK_EMOJI_MAP.get(risk, "")
                        emoji_options = ["(없음)"] + all_emoji_flat
                        source_has_emoji = bool(_EMOJI_RE.search(source_text))

                        # 템플릿이 바뀔 때 이모지 선택기를 강제 리셋 (위젯 렌더링 전에 처리)
                        if st.session_state.get(f"_prev_tmpl_for_emoji_{i}") != selected_template:
                            st.session_state[f"_prev_tmpl_for_emoji_{i}"] = selected_template
                            if source_has_emoji:
                                st.session_state[f"emoji_{i}"] = "(없음)"
                            elif rec_emoji in emoji_options:
                                st.session_state[f"emoji_{i}"] = rec_emoji

                        chosen_emoji = st.selectbox("포인트 이모지", emoji_options, key=f"emoji_{i}")

                        # 이모지는 한 개만: 문구에 이미 있으면 추가 안 함
                        if source_has_emoji:
                            emoji_to_insert = ""
                        else:
                            emoji_to_insert = chosen_emoji if (auto_emoji and chosen_emoji != "(없음)") else ""
                        preview_cap = append_single_emoji(source_text, emoji_to_insert)

                        # source 또는 emoji가 바뀌면 최종 자막 자동 갱신
                        fingerprint = f"{selected_template}|{source_text}|{chosen_emoji}"
                        if st.session_state.get(f"_fp_{i}") != fingerprint:
                            st.session_state[f"final_cap_{i}"] = preview_cap
                            st.session_state[f"_fp_{i}"] = fingerprint

                        final_cap = st.text_input(
                            "📝 최종 자막 (수동 편집 가능)",
                            key=f"final_cap_{i}",
                            placeholder="영상에 출력될 자막",
                        )

                        final_captions.append(final_cap)
                        final_emojis.append(chosen_emoji if chosen_emoji != "(없음)" else "")

                        rec_sfx = template_data.get("recommended_sfx_name", "주의 알림음")
                        rec_sfx_idx = sfx_options.index(rec_sfx) if rec_sfx in sfx_options else 0
                        chosen_sfx = st.selectbox("효과음", sfx_options, index=rec_sfx_idx, key=f"sfx_sel_{i}")
                        final_sfx_names.append(chosen_sfx)

    # ──────────────────────────────────────────────────────
    # TAB 2: 오디오 및 다운로드
    # ──────────────────────────────────────────────────────
    with tab2:
        st.subheader("③ 배경음악 추가 (선택)")
        st.info("🎵 저작권이 확보되었거나 사내 사용이 허가된 파일만 사용해주세요.")
        up_audio = st.file_uploader("오디오 파일 업로드", type=SUPPORTED_AUDIO, key="audio_upload")
        if up_audio:
            st.audio(up_audio)

        st.divider()
        st.subheader("④ 템플릿 및 리소스 다운로드")
        dl_col1, dl_col2, dl_col3 = st.columns(3)
        with dl_col1:
            st.markdown("**🗂️ 이모지 데이터**")
            st.download_button("JSON 파일", data=make_emoji_json(), file_name="emoji_pack.json", mime="application/json", use_container_width=True)
        with dl_col2:
            st.markdown("**📋 자막 템플릿**")
            st.download_button("JSON 파일", data=make_template_json(), file_name="safety_caption_templates.json", mime="application/json", use_container_width=True)
        with dl_col3:
            st.markdown("**🔔 효과음 일괄 받기**")
            try:
                st.download_button("ZIP 파일", data=make_sfx_zip(), file_name="safety_sfx_pack.zip", mime="application/zip", use_container_width=True)
            except Exception:
                st.warning("ZIP 생성 실패")

    # ──────────────────────────────────────────────────────
    # TAB 3: 검토 및 영상 제작
    # ──────────────────────────────────────────────────────
    with tab3:
        st.subheader("⑤ 최종 검토 및 렌더링")
        
        st.markdown(
            "안전수칙을 점검하는 짧은 영상이 현장 인력과 외국인 직원분들께도 "
            "큰 도움이 될 수 있도록 내용과 사내 기준을 한 번 더 확인해 주세요."
        )

        approval_checked = st.checkbox(
            "✅ 모든 사진과 자막이 사내 안전기준 및 보안정책에 부합함을 확인했습니다.",
            key="approval"
        )

        has_images       = bool(up_imgs) and bool(image_paths)
        has_all_captions = has_images and all(c.strip() for c in final_captions)
        has_creator      = bool(creator_name.strip())

        if not has_images:
            st.error("📌 사진이 업로드되지 않았습니다.")
        elif not has_all_captions:
            st.error("📌 모든 사진에 자막이 입력되어야 합니다.")
        elif not has_creator:
            st.error("📌 사이드바에서 '제작자명'을 입력해주세요.")
        elif not approval_checked:
            st.warning("📌 확인란을 체크해야 제작 버튼이 활성화됩니다.")

        btn_disabled = not has_images or not has_all_captions or not has_creator or not approval_checked

        make_clicked = st.button(
            "🎬 숏폼 영상 렌더링 시작",
            type="primary",
            use_container_width=True,
            disabled=btn_disabled,
        )

        _oi = st.session_state.get("_order_indices", list(range(len(up_imgs))) if up_imgs else [])
        sorted_image_filenames = [up_imgs[i].name for i in _oi] if up_imgs else []
        rotations = [st.session_state.get(f"_rot_{orig}", 0) for orig in _oi]

        save_draft()

        if make_clicked and not btn_disabled:
            _run_pipeline(
                image_paths       = image_paths,
                image_filenames   = sorted_image_filenames,
                captions          = final_captions,
                sfx_name_list     = final_sfx_names,
                up_audio          = up_audio,
                clip_sec          = clip_sec,
                video_size        = video_size,
                aspect_label      = aspect_label,
                caption_bg_alpha  = caption_bg_alpha,
                caption_font_size = caption_font_size,
                caption_position  = caption_position,
                fade_sec          = fade_sec,
                sfx_volume        = sfx_volume,
                bgm_volume        = bgm_volume,
                approval_checked  = approval_checked,
                selected_emojis   = final_emojis,
                selected_sfx      = final_sfx_names,
                creator_name      = creator_name,
                rotations         = rotations,
            )

# ══════════════════════════════════════════════════════════════════════════════
# 파이프라인
# ══════════════════════════════════════════════════════════════════════════════

def _run_pipeline(
    image_paths: list,
    image_filenames: list,
    captions: list,
    sfx_name_list: list,
    up_audio,
    clip_sec: float,
    video_size: tuple,
    aspect_label: str,
    caption_bg_alpha: int,
    caption_font_size: int,
    caption_position: str,
    fade_sec: float,
    sfx_volume: float,
    bgm_volume: float,
    approval_checked: bool,
    selected_emojis: list,
    selected_sfx: list,
    creator_name: str,
    rotations: list = None,
) -> None:
    tmp_audio:  Optional[str] = None
    silent_mp4: Optional[str] = None
    final_mp4:  Optional[str] = None

    try:
        if up_audio:
            ext       = Path(up_audio.name).suffix
            tmp_audio = tempfile.NamedTemporaryFile(suffix=ext, delete=False).name
            with open(tmp_audio, "wb") as f:
                f.write(up_audio.getbuffer())

        pb = st.progress(0, text="🎬 영상 렌더링 준비...")

        def slide_cb(p: float):
            pb.progress(int(p * 89), text=f"🎬 렌더링 중... {int(p * 100)}%")

        silent_mp4 = build_slideshow(
            paths              = image_paths,
            captions           = captions,
            clip_sec           = clip_sec,
            video_size         = video_size,
            sfx_name_list      = sfx_name_list,
            sfx_volume         = sfx_volume,
            caption_bg_alpha   = caption_bg_alpha,
            caption_font_size  = caption_font_size,
            caption_position   = caption_position,
            fade_sec           = fade_sec,
            rotations          = rotations,
            on_progress        = slide_cb,
        )
        pb.progress(89, text="🎵 오디오 믹싱 중...")

        if tmp_audio:
            final_mp4 = add_bgm(silent_mp4, tmp_audio, bgm_volume)
            os.unlink(silent_mp4)
            silent_mp4 = None
        else:
            final_mp4  = silent_mp4
            silent_mp4 = None

        pb.progress(100, text="✅ 영상 제작 완료!")
        st.success("🎉 멋진 안전 교육 숏폼이 완성되었습니다!")

        with open(final_mp4, "rb") as f:
            video_data = f.read()

        col_vid, _ = st.columns(2)
        with col_vid:
            st.video(video_data)
        st.download_button(
            "⬇️ 완성된 영상 다운로드 (MP4)",
            data=video_data,
            file_name="safety_education.mp4",
            mime="video/mp4",
            use_container_width=True,
            type="primary",
        )

        risk_types_log = [st.session_state.get(f"risk_{i}", "") for i in range(len(image_paths))]
        tone_log = [st.session_state.get(f"tone_{i}", "") for i in range(len(image_paths))]
        
        save_production_log(
            creator_name         = creator_name,
            image_count          = len(image_paths),
            image_filenames      = image_filenames,
            aspect_ratio         = aspect_label,
            video_size           = list(video_size),
            clip_sec             = clip_sec,
            caption_position     = caption_position,
            caption_bg_alpha     = caption_bg_alpha,
            caption_font_size    = caption_font_size,
            selected_risk_types  = risk_types_log,
            selected_caption_tones = tone_log,
            final_captions       = captions,
            selected_emojis      = selected_emojis,
            selected_sfx         = selected_sfx,
            sfx_volume           = sfx_volume,
            background_music_used= bool(up_audio),
            bgm_volume           = bgm_volume,
            approval_checked     = approval_checked,
        )

    except Exception as e:
        st.error(f"❌ 오류 발생: {type(e).__name__}: {e}")
        with st.expander("🔍 상세 오류 내용"):
            st.code(traceback.format_exc())

    finally:
        for p in [silent_mp4, final_mp4]:
            if p and os.path.exists(p):
                try: os.unlink(p)
                except OSError: pass
        if tmp_audio and os.path.exists(tmp_audio):
            try: os.unlink(tmp_audio)
            except OSError: pass

if __name__ == "__main__":
    main()