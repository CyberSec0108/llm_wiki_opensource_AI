---
title: _archive
type: reference
status: stable
source: 
updated: 2026-09-02
contested: false
contradictions: []
tags: [meta]
---

## 한 줄 요약
완전히 대체된 위키 페이지를 보관하는 곳. 지우지 않고 여기로 옮긴다.

> [!warning] 이 폴더의 페이지는 근거가 아니다
> `query`의 근거로 인용하지 마라. `index.md`에도 등록하지 않는다.
> 왜 폐기됐는지 알아야 할 때만 읽는다.

## 왜 지우지 않고 옮기는가

`raw/`는 불변이라 원본은 남는다. 하지만 **"내가 한때 이렇게 이해했다"는 기록**은 페이지를 지우면 사라진다.
나중에 같은 주제를 다시 정리할 때, 예전에 왜 그렇게 봤고 무엇이 틀렸는지가 중요한 단서가 된다.

## 옮기는 절차

`wiki/CLAUDE.md`의 "페이지 폐기" 절을 따른다. 요약하면:

1. **완전히 대체됐을 때만** 옮긴다. 얇다는 이유로는 옮기지 않는다
2. frontmatter에 `archived: YYYY-MM-DD`와 `superseded_by: 대체 페이지`를 적는다
3. 이 페이지를 가리키던 링크를 **전부 대체 페이지로 돌린다** — 안 하면 깨진 링크가 된다
4. `index.md`에서 줄을 지운다
5. `log.md`에 `archive`로 기록한다
