#!/usr/bin/env python3
"""문서 문안의 AI식 말투·표현 점검 (public-doc-korean-style 8번 규칙을 코드로 옮김)

사용: python3 .claude/hooks/style_check.py 파일 [파일 ...] [--public]
  --public : 공문서 형식 규칙(서술형 어미, 문장 끝 마침표, 천 단위 콤마)까지 검사
지원 형식: md, txt, html, docx, pptx, hwpx, xlsx, pdf
걸린 표현이 있으면 종료코드 1
"""
import re, sys, html, zipfile, subprocess

DOC_EXT = (".md", ".txt", ".html", ".htm", ".docx", ".pptx", ".hwpx", ".xlsx", ".pdf")

# 항상 검사: AI 말투·구조, 구어·외래어, 표기
BAN = {
    "영문 라벨": r"TODAY'?S|KEY TAKEAWAY|BY TRACK|DAILY BRIEF|NEXT STEPS"
                r"|(?<![A-Za-z])(?:ACTION|INSIGHT|SUMMARY|OVERVIEW|DASHBOARD)(?![A-Za-z])",
    "AI 말투": r"인\s?만큼|하는\s?만큼|라고 할 수 있|살펴보(?:겠|았|자)|해 ?보았|중요한 것은|주목할 점은"
              r"|핵심적인|완벽한|강력한|혁신적인|것 같|만 추렸|를 정리했|을 정리했|한눈에|단순히 .{1,15}(?:이|가) 아니라",
    "대칭 슬로건": r"[가-힣]+[은는] [가-힣 ]{1,12}(?:하게|없이|있게|으로), [가-힣]+[은는] [가-힣 ]{1,12}(?:하게|없이|있게|으로)",
    "구어·외래어": r"니즈|인사이트|케이스|팔로업|퀄리티|체크리스트|공수|되게|굉장히"
                  r"|세그먼트|코호트|파일럿|킥오프|인포그래픽|데이터 정제|목업|고도화",
    "저널리즘체": r"겨냥|노린다|국면|판도|후끈|시동|심화일로",
    "실무 은어": r"오탐|단어 스침|재유입|미생성|유효 0건",
    "드문 표현": r"가늚|가늘어|얇[다아은게]",
    "한자": r"[外等約]",
    "줄표": r"[가-힣A-Za-z0-9)·]\s?[—–]\s?[가-힣A-Za-z0-9(]",   # 글자 사이의 줄표만. 표의 빈 칸(—)은 제외
    "말줄임": r"…",
}
# --public 일 때만: 공문서 형식
PUBLIC = {
    "서술형 어미": r"(?:합니다|습니다|입니다|됩니다)\.?\s*$",
    "개조식 마침표": r"[가-힣]\.\s*$",
    "콤마 누락 의심": r"(?<![\d,.\-:/#])\d{4,}(?![\d,.\-:/]|\s?년|\s?호)",
    "구어(날짜)": r"어제|오늘|내일",
}


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
    if p.endswith((".html", ".htm")):
        # 화면에 보이는 글만 남김 (script·style·주석 제외, 태그는 줄바꿈으로)
        t = re.sub(r"(?is)<(script|style)\b.*?</\1>|<!--.*?-->", "", t)
        t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr|td|th|section|article)>", "\n", t)
        t = html.unescape(re.sub(r"<[^>]+>", "", t))
    if p.endswith(".md"):
        t = re.sub(r"(?s)```.*?```", "", t)       # 코드 블록 제외
        t = re.sub(r"`[^`\n]*`", "", t)            # 인라인 코드 제외
    return t


def check(path, public=False):
    rules = dict(BAN, **(PUBLIC if public else {}))
    hits = []
    for no, line in enumerate(read(path).splitlines(), 1):
        for label, pat in rules.items():
            for m in re.finditer(pat, line):
                hits.append((label, m.group(0).strip(), no, line.strip()[:80]))
    return hits


def main(argv):
    public = "--public" in argv
    files = [a for a in argv if not a.startswith("--")]
    total = 0
    for f in files:
        try:
            hits = check(f, public)
        except Exception as e:                    # 읽기 실패는 알리고 넘어감
            print(f"[읽기 실패] {f}: {e}")
            continue
        for label, word, no, ctx in hits:
            print(f"{f}:{no} [{label}] '{word}' | {ctx}")
        total += len(hits)
    print("잔존 표현 없음" if not total else f"총 {total}건 확인 필요")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
