#!/usr/bin/env python3
"""문서 문안의 AI식 말투·표현 점검 (규칙: style_rules.py = 정본 대체표 사례)

사용: python3 .claude/hooks/style_check.py 파일 [파일 ...] [--public] [--fix-only]
  --public   : 공문서 형식 규칙(서술형 어미, 마침표, 콤마, 날짜 구어 등)까지 검사
  --fix-only : '수정' 등급만 출력 ('확인' 등급 제외)
지원 형식: md, txt, html, docx, pptx, hwpx, xlsx, pdf, 그리고 생성기 문안(py·js의 한글 문자열)
'수정' 등급이 하나라도 있으면 종료코드 1
"""
import html, os, re, subprocess, sys, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from style_rules import PUBLIC_RULES, RULES  # noqa: E402

DOC_EXT = (".md", ".txt", ".html", ".htm", ".docx", ".pptx", ".hwpx", ".xlsx", ".pdf")
GEN_EXT = (".py", ".js")


def _strings_with_hangul(src):
    """생성기 코드에서 한글이 든 문자열만 뽑음 (주석 제외). 줄 번호 유지"""
    out = []
    for line in src.splitlines():
        code = re.sub(r"(?<![\"'])(#|//).*$", "", line) if not re.search(r"https?://", line) else line
        segs = re.findall(r"\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'|`([^`]*)`", code)
        texts = [next(x for x in g if x) for g in segs if any(g)]
        texts = [re.sub(r"<[^>]+>|\$\{[^}]*\}|\{[^}]*\}", " ", t) for t in texts if re.search("[가-힣]", t)]
        out.append(" ".join(texts))
    return "\n".join(out)


def read(path):
    p = path.lower()
    if p.endswith((".docx", ".pptx", ".hwpx", ".xlsx")):
        z, out = zipfile.ZipFile(path), []
        part = (r"(word/(document|header\d*|footer\d*|footnotes)|ppt/slides/slide\d+"
                r"|ppt/notesSlides/notesSlide\d+|Contents/section\d+|xl/sharedStrings)\.xml$")
        for n in sorted(z.namelist()):
            if re.search(part, n):
                x = re.sub(r"</(w:p|a:p|hp:p|si)>", "\n", z.read(n).decode("utf-8", "ignore"))
                out.append(html.unescape(re.sub(r"<[^>]+>", "", x)))
        return "\n".join(out)
    if p.endswith(".pdf"):
        return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True).stdout
    t = open(path, encoding="utf-8", errors="ignore").read()
    if p.endswith(GEN_EXT):
        # 독스트링·블록 주석은 개발 주석이므로 제외 (줄 수는 유지)
        t = re.sub(r'(?s)("""|\'\'\'|/\*).*?("""|\'\'\'|\*/)', lambda m: "\n" * m.group(0).count("\n"), t)
        return _strings_with_hangul(t)
    if p.endswith((".html", ".htm")):
        # 화면 글(태그 밖) + 스크립트 안 한글 문자열(화면에 그려지는 문구)을 같이 검사
        scripts = "\n".join(re.findall(r"(?is)<script\b[^>]*>(.*?)</script>", t))
        t = re.sub(r"(?is)<(script|style)\b.*?</\1>|<!--.*?-->", "", t)
        t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr|td|th|section|article|title)>", "\n", t)
        t = html.unescape(re.sub(r"<[^>]+>", "", t)) + "\n" + _strings_with_hangul(scripts)
    if p.endswith(".md"):
        t = re.sub(r"(?s)```.*?```", "", t)
        t = re.sub(r"`[^`\n]*`", "", t)
    return t


def check(path, public=False):
    rules = RULES + (PUBLIC_RULES if public else [])
    comp = [(g, c, re.compile(r, re.M), s) for g, c, r, s in rules]
    hits = []
    for no, line in enumerate(read(path).splitlines(), 1):
        for grade, cat, rx, sug in comp:
            for m in rx.finditer(line):
                hits.append((grade, cat, m.group(0).strip(), no, line.strip()[:80], sug))
    return hits


def main(argv):
    public, fix_only = "--public" in argv, "--fix-only" in argv
    files = [a for a in argv if not a.startswith("--")]
    n_fix = n_chk = 0
    for f in files:
        try:
            hits = check(f, public)
        except Exception as e:
            print(f"[읽기 실패] {f}: {e}")
            continue
        for grade, cat, word, no, ctx, sug in hits:
            if fix_only and grade != "수정":
                continue
            print(f"{f}:{no} [{grade}·{cat}] '{word}' → {sug} | {ctx}")
        n_fix += sum(h[0] == "수정" for h in hits)
        n_chk += sum(h[0] == "확인" for h in hits)
    print("잔존 표현 없음" if not (n_fix or n_chk) else f"수정 {n_fix}건 · 확인 {n_chk}건")
    return 1 if n_fix else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
