# GPT–Codex Collaboration Contract

이 문서는 연구 논의를 실제 코드 작업으로 넘기는 최소 운영 규칙이다.

## 역할

### GPT / ChatGPT

- 연구 질문, novelty, 주장 범위, 관련 연구와 논문 서술을 검토한다.
- 실험 결과를 해석하되 코드와 raw artifact로 확인되지 않은 수치를 만들지 않는다.
- 합의된 변경을 `RESEARCH_SPEC.md` 또는 `EXPERIMENT_PLAN.md`의 수정안으로 표현한다.

### Codex

- 저장소와 위 문서를 읽고 구현, 테스트, 실행, provenance 기록을 수행한다.
- 결과를 `IMPLEMENTED`, `VERIFIED`, `PROPOSED`, `BLOCKED`로 나누어 보고한다.
- 연구 질문을 바꾸는 구현 편의를 발견하면 임의로 바꾸지 않고 충돌을 보고한다.

### GitHub

- 연구 명세, 코드, 테스트, 실험 manifest, 리뷰 이력을 연결하는 공용 원장이다.
- 연구 논리 변경과 코드 변경은 review 가능한 branch/PR로 남긴다.

## 한 사이클

1. GPT에서 연구 결정을 내린다.
2. 결정 내용을 문서 diff 또는 명시적 작업 요청으로 만든다.
3. Codex가 작은 vertical slice를 구현하고 테스트한다.
4. Codex가 raw 결과와 claim status를 보고한다.
5. GPT가 결과가 실제 주장에 충분한지 비판적으로 검토한다.
6. 승인된 변경만 연구 명세와 논문 초안에 반영한다.

## Codex 작업 요청 템플릿

```markdown
Goal:
Supported research claim/RQ:
In scope:
Out of scope:
Inputs and versions:
Expected artifacts:
Acceptance tests:
Research risks or confounds:
```

## Codex 완료 보고 템플릿

```markdown
Implemented:
Verified:
Proposed/unverified:
Blocked:
Tests and commands:
Raw artifact locations:
Changed files:
Effect on research claims:
```

## 문맥 동기화 규칙

- 채팅 기억보다 저장소 문서를 우선한다.
- 새로운 결정은 채팅에만 남기지 않고 해당 문서에 반영한다.
- 논문용 숫자는 raw result ID, evaluator version, git SHA로 역추적 가능해야 한다.
- 실험 후 가설을 바꾸면 exploratory change로 기록한다.
- `main`에는 리뷰되지 않은 연구 주장이나 재현 불가능한 결과를 직접 넣지 않는다.

## 첫 번째 권장 요청

```markdown
Read AGENTS.md, docs/RESEARCH_SPEC.md, and docs/EXPERIMENT_PLAN.md.
Audit the current repository against Phase A only. Do not implement downstream LLM
evaluation yet. Return a gap table with IMPLEMENTED/VERIFIED/PROPOSED/BLOCKED status,
the exact files supporting each status, and the smallest vertical slice required for
one reproducible fact-extraction downstream task.
```
