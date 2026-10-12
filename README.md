# Automata — 로봇·AI 뉴스룸

**바로가기: https://jowenchoi.github.io/newsroom/**

타임지 스타일 다크모드 뉴스 대시보드입니다.

- **커버 스토리 + 로보틱스·AI 주요 뉴스** (최소 12건): 로봇·휴머노이드·피지컬 AI에 더해 AI 모델·AI 반도체·자율주행 등 AI 산업 전반
- **경쟁사 동향** (최소 8건, 최근 30일): 레인보우로보틱스, HD현대로보틱스, 뉴로메카, 한화로보틱스, Universal Robots, FANUC, ABB, Yaskawa, KUKA, Techman, 중국 협동로봇
- **두산로보틱스 & 두산 계열사** (최소 8건): 두산에너빌리티, 두산밥캣, 두산퓨얼셀, 두산테스나 등

## 편집 원칙
- **공신력 있는 매체만**: 연합뉴스·주요 일간지·경제지·IT 전문지, Reuters·Bloomberg·TechCrunch·IEEE Spectrum 등 (`scripts/fetch_news.py`의 `SOURCES`)
- **중복 제거**: 같은 사건을 다룬 기사는 하나만
- **주가 기사 제외**: 시황·목표주가·특징주 제외. 상장·인수합병·대형 수주만 예외
- **영어 기사는 한국어로 번역**

중복 판별·주가 기사 필터·한 줄 번역은 LLM 편집자가 맡습니다.
`ANTHROPIC_API_KEY` 시크릿이 있으면 Claude, 없고 `OPENAI_API_KEY`가 있으면 OpenAI
(기본 `gpt-6-luna`, 안 되면 `gpt-5.4-nano` → `gpt-4o-mini` 순으로 시도. Actions 변수 `OPENAI_MODEL`로 고정 가능),
둘 다 없으면 규칙 기반 필터 + Google 번역으로 동작합니다. Claude는 `claude-haiku-5-5`를 씁니다.

## 구성
- `index.html` — 대시보드 (`data/news.js`를 읽어 렌더링)
- `manifest.webmanifest`, `icons/` — 휴대폰 홈 화면 바로가기(앱 아이콘)
- `scripts/fetch_news.py` — 뉴스 수집·편집
- `.github/workflows/update-news.yml` — 뉴스 수집. **예약 실행 없음**: 사이트의 새로고침 버튼(또는 Actions의 Run workflow)을 누를 때만 실행

## 처음 한 번 설정
1. Settings → Pages → Build and deployment: **Deploy from a branch**, Branch **main** / **(root)** → Save
2. (권장) Settings → Secrets and variables → Actions → `ANTHROPIC_API_KEY` 또는 `OPENAI_API_KEY` 추가
3. 사이트 오른쪽 위 **새로고침** 버튼 → 처음 한 번 GitHub 토큰 등록
   (Fine-grained token, Repository access: newsroom만, Permissions: Actions **Read and write**).
   토큰은 그 브라우저에만 저장됩니다.

## 휴대폰 홈 화면에 추가
- **iPhone (Safari)**: 바로가기 주소 열기 → 공유 버튼 → *홈 화면에 추가*
- **Android (Chrome)**: 주소 열기 → ⋮ 메뉴 → *홈 화면에 추가* (또는 *앱 설치*)
- **PC (Chrome/Edge)**: 주소창 오른쪽 설치 아이콘, 또는 북마크

로컬 실행: `python3 scripts/fetch_news.py` 후 `index.html` 열기.
