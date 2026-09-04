# raw/ — 불변 원본 계층

여기 있는 파일은 **원본**이다. 사실의 최종 근거이며, 위키가 틀렸을 때 되돌아올 자리다.

## 절대 규칙

- **본문 수정 금지. 삭제 금지. 요약해서 덮어쓰기 금지.** 추가만 가능하다.
- 오타조차 고치지 않는다. 원본의 오류도 원본의 일부다.
- 정리하고 싶으면 `wiki/`에 새 페이지를 만든다. 여기서 하지 않는다.
- **단 하나의 예외**: ingest를 마친 뒤 frontmatter의 `ingested`를 `true`로 바꾼다.
  이 필드 외에는 frontmatter도 고치지 않는다. 서지정보가 틀렸으면 고치지 말고 나에게 알려라.

## 하위 폴더

| 폴더 | 넣는 것 | 인용 가능 |
|---|---|---|
| `articles/` | 웹 글, 블로그, 뉴스레터 | △ |
| `papers/` | 논문, 기술 리포트, 벤더 백서 | ✅ |
| `books/` | 책, 교재, 장별 발췌 | ✅ |
| `videos/` | 유튜브, 강연, 세미나 영상 | ✅ |
| `writeups/` | 취약점 분석, CTF 라이트업, 사고 대응 기록 | △ |
| `notes/` | 내가 직접 쓴 원본 메모, 회의록, 실습 로그 | — |
| `inbox/` | 분류 전 임시 투입구. 쌓이면 ingest 때 분류를 제안하라 | — |

폴더가 안 맞으면 `inbox/`에 넣는다. 새 하위 폴더는 같은 유형이 5개 이상 모였을 때만 만든다.

## 공통 frontmatter (모든 파일)

```yaml
---
type: article | paper | book | video | writeup | note | unsorted
title:
source:            # URL 또는 "직접 작성"
collected:         # 수집일 YYYY-MM-DD
why:               # 왜 담았나 — 한 줄
axis:              # ai-for-security | securing-ai | both
ingested: false
tags: []
---
```

- **`why`가 비어 있으면 ingest 때 반드시 물어라.** 6개월 뒤 이 줄이 없으면 왜 저장했는지 알 수 없다.
- `axis`가 비어 있어도 물어라. 두 축 어디에도 안 걸리면 우선순위가 낮은 자료다 ([[나의 핵심 맥락]]).
- 본문은 붙여넣은 그대로 둔다. 형식을 다듬지 마라.

## 매체별 추가 키

`papers/` `books/` `videos/`는 인용 대상이므로 서지정보를 더 받는다.

| 폴더 | 추가 키 | 위치 표기 (locator) |
|---|---|---|
| `papers/` | `author` `published` `venue` `doi` `cite_key` | 절·그림·표 번호 |
| `books/` | `author` `publisher` `published` `isbn` `cite_key` `read_range` | **페이지** |
| `videos/` | `channel` `published` `duration` `cite_key` | **타임스탬프 `mm:ss`** |
| `writeups/` | `author` `published` `target` `cve` | — |

### 인용키

위키 페이지의 `source`에는 경로가 아니라 `cite_key`를 쓴다.
형식은 `저자또는채널 + 연도 + 주제어` (영문 소문자, 공백 없음).

```
papers/  kim2024llmsec
books/   stallings2023netsec
videos/  computerphile2023sqli
```

경로가 아니라 키를 쓰는 이유는, 같은 자료를 나중에 다른 곳에서 다시 받아도 참조가 안 깨지기 때문이다.

### 지켜야 할 것

- **서지정보를 추측해서 채우지 마라.** 모르면 빈칸으로 두고 나에게 알려라. 지어낸 저자·연도는 논문 단계에서 치명적이다.
- `cite_key`가 비어 있으면 ingest 때 **제안하고 확인받은 뒤** 채운다. 혼자 정하지 마라.
- 서지정보가 없는 자료를 근거로 쓴 위키 페이지는 `status`를 `stable`로 올리지 않는다.
- `videos/`는 **트랜스크립트가 있어야 쓸모 있다.** 없으면 ingest 전에 나에게 알려라.
- 책·영상을 근거로 위키에 쓸 때는 **locator를 반드시 붙인다** — 예: `(computerphile2023sqli, 04:12)`.
  타임스탬프·페이지 없는 인용은 나중에 검증이 불가능하다.

## 수집 경로

- **웹**: Obsidian 웹 클리퍼. 템플릿은 `templates/clipper/*.json` (매체별 6종, 폴더·frontmatter가 자동으로 맞춰짐)
- **직접 작성**: `templates/원본 헤더 - *.md`를 복사해서 시작

## ingest 할 때

- 원본을 읽되 **본문을 고치지 않는다**. 출력은 전부 `wiki/`로 간다.
- 원본에 없는 내용을 위키에 추가하지 마라. 추론이면 `> [!inference]`로 표시한다.
- 끝나면 `ingested: true`로 바꾼다. 이게 다음 스캔의 기준이 된다.
