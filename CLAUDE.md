# 작업 규칙

## 문서 문체
- 리포트·README·HTML·DOCX·PPTX·HWPX 등 사람이 읽는 문안은 공공기관 문서가 아니어도 `public-doc-korean-style` 스킬을 먼저 읽고 적용
- 마무리 단계에서 `python3 .claude/hooks/style_check.py <파일>` 결과가 `잔존 표현 없음`이 될 때까지 고침
- Stop 훅(`.claude/settings.json`)이 이번 요청 중 수정된 문서를 자동 검사하고, 걸리면 종료를 막음
- 월간 리포트 문안은 `monthly_report.py`에서 고침 (산출물 직접 수정 금지)
- 고유명사·인용문·표의 빈 칸(—) 등 고치면 안 되는 항목은 그대로 두고 사유를 알림
