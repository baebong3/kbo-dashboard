# 작업 규칙

## 문서 문체
- 리포트·README·HTML·DOCX·PPTX·HWPX 등 사람이 읽는 문안은 공공기관 문서가 아니어도 `public-doc-korean-style` 스킬을 먼저 읽고 적용
- 마무리 단계에서 `python3 .claude/hooks/style_check.py <파일>` 결과의 '수정' 등급이 0건이 될 때까지 고침. '확인' 등급은 문맥을 보고 판단하고, 유지하면 사유를 알림
- Stop 훅(`.claude/settings.json`)이 이번 요청 중 수정된 문서와 생성기(py·js) 문안을 자동 검사하고, 걸리면 종료를 막음
- 규칙은 `.claude/hooks/style_rules.py`에 있음 - 정본 「AI·클로드식 표현 수정 대체표」(Claude Docs)에서 실제로 바로잡은 사례를 옮긴 것. 사용자가 새로 바로잡은 표현은 정본 문서에 먼저 추가하고, 이 파일에 규칙 한 줄을 추가
- 월간 리포트 문안은 `monthly_report.py`에서 고침 (산출물 직접 수정 금지)
- 고유명사·인용문·표의 빈 칸(—)·야구 용어(공수 교대 등)는 그대로 둠
