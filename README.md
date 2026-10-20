# 한국GPT협회 수달일보

한국GPT협회에 다니는 수달 사원이 매일 아침 골라오는 AI 뉴스. 협회 오픈채팅방에 매일 올릴 페이지입니다.

## 매일 하는 일

```
python daily.py
```

1. 9개 RSS(AI타임스, 지디넷코리아, 전자신문, 블로터, 구글뉴스, OpenAI, Google AI, TechCrunch, The Verge)에서 최근 36시간의 AI 기사를 모읍니다.
2. 6건을 골라 `data/news/날짜.json`에 저장합니다.
3. `public/`에 페이지를 만듭니다. 오늘 페이지(`index.html`), 날짜별 페이지(`d/날짜/`), 지난 호 목록(`archive/`).

### 선별 모드 두 가지

| 모드 | 조건 | 결과 |
|---|---|---|
| Claude 모드 | `ANTHROPIC_API_KEY` 환경변수가 있을 때 | 독자에게 흥미로운 6건 선별, 한국어 제목·요약, "수달 한마디", 분류, 그날 웹툰 소재 추천 |
| 기본 모드 | 키가 없거나 API 오류일 때 | 국내 기사만 키워드 점수로 선별, 원제목만 표시 (요약·한마디 없음) |

- Claude 모델: `config.json`의 `curation.model` (기본 `claude-opus-5-5`). 거절(refusal) 시 서버가 자동으로 다른 모델로 재시도하도록 `fallbacks: "default"`를 켜 두었습니다.
- 링크는 항상 실제 수집한 기사에서 가져오며, AI가 만든 링크는 쓰지 않습니다.
- 기사 전문은 가져오지 않습니다. 제목·짧은 요약·원문 링크만 보여줍니다.

## 옵션

```
python daily.py --basic        # Claude 없이 기본 모드
python daily.py --build-only   # 수집 없이 페이지만 다시 만들기 (디자인·웹툰 수정 후)
python daily.py --date 2026-10-21
```

## 웹툰 넣기

1. 이미지를 `data/webtoons/`에 넣습니다 (JPG 권장).
2. `data/webtoons.json`에 항목을 추가합니다. `date`가 같은 날 페이지에 "오늘의 수달 사원"으로 나오고, 그날 웹툰이 없으면 가장 최근 웹툰이 "수달 사원 웹툰"으로 나옵니다.
3. `python daily.py --build-only`

## 미리보기

```
python -m http.server 8765 --directory public
```

브라우저에서 http://localhost:8765 를 엽니다.

## 설정 (`config.json`)

- `site.base_url`: 배포 주소. 넣어야 카카오톡 링크 미리보기에 웹툰 이미지가 뜹니다 (2단계).
- `site.publisher_url`: 협회 홈페이지 주소. 넣으면 바닥글의 협회 이름이 링크가 됩니다.
- `feeds`: 뉴스 소스. `ai_only: false`인 일반 IT 매체는 AI 키워드가 있는 기사만 고릅니다.

## 자동 발행 (GitHub Actions)

`.github/workflows/daily.yml`이 매일 06:30(한국 시간)에 뉴스를 모아 저장소에 기록하고 GitHub Pages로 배포합니다.

- 웹툰 이미지·`webtoons.json`·디자인을 바꿔 올리면 페이지만 다시 만듭니다 (뉴스는 다시 모으지 않음).
- 저장소 Actions 탭 → "수달일보 발행" → Run workflow 로 바로 실행할 수 있습니다.
- Claude 모드를 쓰려면 저장소 Settings → Secrets and variables → Actions 에 `ANTHROPIC_API_KEY`를 등록합니다. 없으면 기본 모드로 발행됩니다.

## 오픈채팅방에 올리기

1. `배포주소/share/` 를 엽니다 (운영자용, 검색엔진 비노출).
2. 그날 게시글의 "게시글 복사하기"를 누르고 오픈채팅방에 붙여 넣습니다.
3. 게시글 속 링크는 날짜별 주소(`/d/날짜/`)라서 카카오톡 미리보기에 그날 썸네일(`/og/날짜.jpg`)이 뜹니다.

카카오톡은 한 번 읽은 미리보기를 오래 기억합니다. 썸네일을 고친 뒤에도 옛 이미지가 보이면 [카카오 공유 디버거](https://developers.kakao.com/tool/debugger/sharing)에서 해당 주소의 캐시를 지웁니다.

## 진행 상황

- [x] 1단계: 뉴스 수집·선별·요약, 수달 사원 브랜드 페이지, 지난 호 목록, 첫 웹툰(장보기까지 AI에게?) 연결
- [x] 2단계 준비: 카톡 미리보기 썸네일, 오픈채팅방 복사 페이지, 매일 자동 실행·배포 설정
- [x] 2단계 연결: https://koreagpt.github.io/sudal-news (저장소 koreagpt/sudal-news), 매일 06:30 자동 발행 확인
- [ ] 3단계: 웹툰 자동 생성 + 확인 후 게시 화면
- [ ] 4단계: 클릭 측정

확인한 것: 기본 모드로 2026-10-20 실제 뉴스 수집·페이지 생성, 모바일(375px) 화면 확인.
확인 못 한 것: Claude 모드 실제 호출 (API 키 없음). 응답 처리 로직과 SDK 인자는 가짜 응답으로만 점검함.
