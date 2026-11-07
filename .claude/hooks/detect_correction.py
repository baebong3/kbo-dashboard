#!/usr/bin/env python3
"""UserPromptSubmit 훅: 사용자 메시지에서 표현 교정 지시를 알아채 규칙 반영을 지시

교정으로 보이는 메시지(예: "A 말고 B", "A → B", "A 대신 B로", "A라는 표현 쓰지 마", "AI스러운 말투")가 오면
1) 이번 요청 시작 시각 기록 (mark_turn과 같은 역할)
2) 교정 플래그 파일 생성 - Stop 훅이 규칙 반영 여부를 확인
3) Claude에게 반영 절차를 추가 문맥으로 전달
"""
import json, os, re, sys, tempfile

try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
sid = data.get("session_id", "default")
prompt = data.get("prompt", "") or ""

d = os.path.join(tempfile.gettempdir(), "claude-style-gate"); os.makedirs(d, exist_ok=True)
open(os.path.join(d, f"{sid}.marker"), "w").close()
flag = os.path.join(d, f"{sid}.correction")
if os.path.exists(flag):
    os.remove(flag)

# 교정 신호: 치환 구문 + 문체 관련 낱말
SWAP = [r"\S+\s*(?:→|->|=>)\s*\S+", r"\S+\s*(?:말고|대신|아니라)\s*\S+(?:로|으로|라고)",
        r"(?:쓰지|사용하지|넣지)\s*(?:마|말|않)", r"(?:으로|로)\s*(?:바꿔|고쳐|수정해)", r"금지"]
TOPIC = [r"표현", r"말투", r"문체", r"단어", r"용어", r"어색", r"AI\s?스러", r"클로드식", r"조어", r"문구", r"어미", r"번역투"]
swap = any(re.search(p, prompt) for p in SWAP)
topic = any(re.search(p, prompt) for p in TOPIC)
QUOTED = r"[\"'“‘「][^\"'”’」\n]{1,30}[\"'”’」]\s*(?:말고|대신|→|->|=>|은|는|이라는|라는)?\s*(?:[\"'“‘「][^\"'”’」\n]{1,30}[\"'”’」]|\S+\s*(?:쓰지|사용하지))"
if not (swap and topic) and not re.search(QUOTED, prompt) and not re.search(r"AI\s?스러|클로드식|AI식", prompt):
    sys.exit(0)

open(flag, "w").write(prompt[:2000])
ctx = """[표현 교정 감지] 이번 메시지에 표현·말투 교정이 들어 있는 것으로 보임. 본 작업과 함께 아래를 바로 반영할 것
1. 교정 내용을 (쓰지 않음 / 대체 / 과업명) 단위로 뽑음. 교정이 아니면(질문·일반 요청) 반영하지 않고 끝에 한 줄로 알림
2. 정본 「AI·클로드식 표현 수정 대체표」(Claude Docs, project e9fd442b-20ca-448f-af23-519e168a1d8d)의 해당 절(구조는 2절, 조어는 3절, 단어는 4절, 문장 사례는 5절)에 행 추가. 같은 행이 있으면 대체만 보강. Docs 도구는 guide topic.editing을 먼저 읽고 사용
3. .claude/hooks/style_rules.py RULES에 규칙 한 줄 추가 - 문맥에 따라 유지 가능하면 '확인', 거의 항상 고칠 표현이면 '수정'. 기존 파일에 오탐이 나지 않는지 style_check.py로 확인
4. .claude/style_corrections.md에 날짜·원문·대체·과업 한 줄 기록 (claude.ai 스킬 public-doc-korean-style·final-style-gate에 옮길 개선안 목록)
5. 이미 만든 산출물·생성기에 같은 표현이 있으면 함께 고침
6. 커밋·푸시하고 결과 보고에 '반영: 대체표 N행, 규칙 N개' 한 줄을 적음"""
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}, ensure_ascii=False))
