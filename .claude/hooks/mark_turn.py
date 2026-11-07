#!/usr/bin/env python3
"""UserPromptSubmit 훅: 이번 요청이 시작된 시각을 기록 (Stop 훅이 이후 수정된 문서만 검사)"""
import json, os, sys, tempfile
try:
    sid = json.load(sys.stdin).get("session_id", "default")
except Exception:
    sid = "default"
d = os.path.join(tempfile.gettempdir(), "claude-style-gate"); os.makedirs(d, exist_ok=True)
open(os.path.join(d, f"{sid}.marker"), "w").close()
