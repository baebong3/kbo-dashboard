#!/usr/bin/env python3
"""Stop 훅: 문서 작업 마무리 단계에서 AI식 말투·표현 점검을 강제

이번 요청 중에 만들거나 고친 문서(md·txt·html·docx·pptx·hwpx·xlsx·pdf)를 찾아
style_check.py로 검사하고, 걸린 표현이 있으면 종료를 막고 수정 지시를 Claude에게 돌려줌
- 검사 위치: 프로젝트 폴더, 세션 스크래치패드(/tmp/claude-*)
- 한 번 막은 뒤 다시 종료할 때(stop_hook_active)는 통과시켜 무한 반복을 막음
"""
import glob, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from style_check import DOC_EXT, check  # noqa: E402

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "tool-results"}
SKIP_NAMES = {"CLAUDE.md", "SKILL.md", "README.md"}   # 규칙 설명 문서는 예시 표현을 담고 있어 제외
PUBLIC_HINT = ("제안", "보고서", "결과보고", "계획서", "브리핑", "안내문", "과업")  # 파일명에 있으면 공문서 형식까지 검사

data = {}
try:
    data = json.load(sys.stdin)
except Exception:
    pass
if data.get("stop_hook_active"):
    sys.exit(0)

marker = os.path.join(tempfile.gettempdir(), "claude-style-gate", f"{data.get('session_id', 'default')}.marker")
since = os.path.getmtime(marker) if os.path.exists(marker) else time.time() - 30 * 60

roots = [os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()]
roots += glob.glob(os.path.join(tempfile.gettempdir(), "claude-*", "*", "*", "scratchpad"))

def git_changed(root):
    """git 저장소면 커밋되지 않은 변경·새 파일만 돌려줌 (새로 clone한 파일의 수정 시각에 속지 않게)"""
    try:
        out = subprocess.run(["git", "-C", root, "status", "--porcelain", "-z", "--untracked-files=all"],
                             capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return {os.path.join(root, e[3:]) for e in out.stdout.split("\0") if len(e) > 3}


files = []
for root in dict.fromkeys(roots):
    changed = git_changed(root)
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            fp = os.path.join(dp, fn)
            if not fn.lower().endswith(DOC_EXT) or fn in SKIP_NAMES:
                continue
            if changed is not None and fp not in changed:
                continue                      # git 저장소: 이번에 손대지 않은 파일은 제외
            if os.path.getmtime(fp) >= since:
                files.append(fp)

report = []
for fp in files:
    try:
        hits = check(fp, public=any(k in os.path.basename(fp) for k in PUBLIC_HINT))
    except Exception:
        continue
    for label, word, no, ctx in hits[:30]:
        report.append(f"- {os.path.relpath(fp, roots[0]) if fp.startswith(roots[0]) else fp}:{no} [{label}] '{word}' | {ctx}")

if report:
    reason = ("[문체 점검] 이번 작업에서 만들거나 고친 문서에 AI식 말투·표현이 남아 있음. "
              "public-doc-korean-style 스킬과 대체표 기준으로 고친 뒤 마무리할 것. "
              "생성 스크립트가 만든 파일이면 산출물이 아니라 생성기 문안을 고칠 것. "
              "고유명사·인용문·표의 빈 칸처럼 고치면 안 되는 항목은 그대로 두고 이유를 사용자에게 알릴 것.\n"
              + "\n".join(report[:60]))
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
sys.exit(0)
