# KBO 관중 분석 대시보드

2025·2026 KBO 리그 관중 데이터를 매일 자동 업데이트하는 대시보드입니다.

## 🔗 대시보드 링크
> 배포 후 이 부분에 링크를 넣으세요:
> `https://[GitHub사용자명].github.io/kbo-dashboard`

---

## ⚡ 5분 설치 가이드

### 1단계 — GitHub 저장소 만들기

1. [github.com](https://github.com) 로그인 (계정 없으면 무료 가입)
2. 우측 상단 `+` → **New repository**
3. Repository name: `kbo-dashboard`
4. **Public** 선택 (GitHub Pages 무료 사용 조건)
5. **Create repository** 클릭

---

### 2단계 — 파일 업로드

저장소 페이지에서 **uploading an existing file** 클릭 후 아래 파일 전부 업로드:

```
📁 업로드할 파일 목록
├── index.html              ← 대시보드 메인 파일
├── fetch_kbo.py            ← 데이터 수집 스크립트
├── requirements.txt        ← Python 패키지 목록
└── .github/
    └── workflows/
        └── update_kbo.yml  ← 자동 업데이트 설정
```

> ⚠️ `.github/workflows/update_kbo.yml` 은 폴더 구조 그대로 업로드해야 합니다.
> GitHub 웹에서 폴더 구조 유지 업로드: 파일을 드래그할 때 폴더째로 드래그하세요.

---

### 3단계 — GitHub Pages 활성화

1. 저장소 상단 **Settings** 탭 클릭
2. 왼쪽 메뉴 **Pages** 클릭
3. Source: **Deploy from a branch**
4. Branch: **gh-pages** / **/(root)** 선택 → **Save**

---

### 4단계 — 첫 번째 실행 (수동)

1. 저장소 상단 **Actions** 탭 클릭
2. 왼쪽 **KBO 관중 데이터 자동 업데이트** 클릭
3. **Run workflow** → **Run workflow** 버튼 클릭
4. 약 3~5분 대기 후 완료

완료되면 `https://[사용자명].github.io/kbo-dashboard` 에서 대시보드 확인!

---

## 🔄 자동 업데이트 스케줄

매일 **오전 8시 30분 KST** 에 자동 실행됩니다.

- KBO 전날 경기 관중 데이터 수집
- `kbo_games.json` 업데이트
- 대시보드 자동 배포

---

## 📁 파일 구조

```
kbo-dashboard/
├── .github/
│   └── workflows/
│       └── update_kbo.yml   # 자동화 설정
├── index.html               # 대시보드 (메인 페이지)
├── kbo_games.json           # 수집된 관중 데이터 (자동 생성)
├── fetch_kbo.py             # 데이터 수집 스크립트
├── requirements.txt         # Python 의존성
└── README.md                # 이 파일
```

---

## ❓ 문제 해결

**Actions 탭에서 실패(빨간 X)가 뜨는 경우**
→ Actions 클릭 → 실패한 워크플로우 클릭 → 로그 확인
→ KBO 사이트 접근 차단 시: 데이터 없이 기존 데이터로 유지됩니다

**대시보드 링크가 404인 경우**
→ Settings → Pages → Source가 `gh-pages` 브랜치로 설정됐는지 확인
→ Actions가 최소 1회 성공적으로 실행됐는지 확인

---

제작: (주)서던포스트
