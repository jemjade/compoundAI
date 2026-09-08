# CompoundAI 연구 구현 감사 — 2026-09-08

## 최종 판정

**논문의 모든 내용이 구현됐는가? — 아니오: 명시적으로 빠진 구현이 있다.**

**논문 주장을 뒷받침할 실험과 분석이 완료됐는가? — 아니오.** 논문 조건의 실제 실험 결과, 검증 예산별 정책 비교, structural reach–recovery 분석, 실제 파서 오류 표본, 멀티모달/VLM 실행, 연구용 provenance-aware 검증 인터페이스가 없다.

현재 증거가 입증하는 범위는 더 좁다. 공개 PDF를 pypdf 텍스트로 준비하고, 한 Boeing 문서의 두 숫자 오류를 대상으로 baseline/no-op/A/B/AB를 각각 새 파이프라인 실행으로 비교할 수 있는 파일럿 코드가 있다. 최신 코드에는 선택적 LLM 합성, 문자 청킹, BM25 검색, 근거 ID를 제한한 QA, 실행 trace, 수동 정오 판정과 최종 복구 집계가 구현되어 있다. 그러나 저장된 연구 실행·판정·요약 결과는 없다.

이 문서에서 구현 상태는 요청된 `완료/부분 구현/미구현/확인 불가`를 사용한다. 실행 증거는 `코드 확인만 완료`, `mock 또는 단위 테스트만 확인`, `실제 모델 smoke test 확인`, `논문 조건의 실제 실험 결과 확인`, `결과의 평가·분석까지 확인`으로 별도 표기한다. 저장소 지침의 연구 주장 라벨로 요약하면 파일럿 실행기는 `IMPLEMENTED`, 실제 논문 주장은 `PROPOSED`, 외부 모델·실제 파서 실행 일부는 `BLOCKED`이며, 논문 주장에 대해 `VERIFIED`인 항목은 없다.

## 1. 감사 대상과 확인 범위

### 저장소·브랜치·PR

- 실제 작업 디렉터리: `/Users/suhyunpark/suhyun_dev/compoundAI`
- 원격: `origin = https://github.com/jemjade/compoundAI.git`
- 작업트리: `research/repair-pilot@fe0524c3e5525684559eadd0fb10da67ab5304cd`, `origin/research/repair-pilot`과 일치, 감사 시작 시 미커밋 변경 없음.
- 접근 가능한 원격 branch: `main@6e586c6234858a2eb6782ae2b4e400c915a906fb`, `research/repair-pilot@fe0524c...`, `codex/research-bridge@dad9cab...`.
- PR #1 `Add reproducible paired-repair research pilot`: GitHub 조회 시 `MERGED`, `isDraft=true`, head `research/repair-pilot@fe0524c...`, merge commit `240c730d...`, merged at `2026-09-07T15:26:17Z`.
- 원격 `main`은 PR head 이후 `feat: support local Ollama research runs`까지 포함한다. 따라서 **주 감사 버전은 최신 원격 `main@6e586c6`**이며, 현재 checkout `fe0524c`는 PR head 비교용으로 확인했다. 최신 main은 별도 임시 clone에서 읽고 실행해 원래 작업트리와 branch를 변경하지 않았다.

### 지침·논문·계획 문서

- 현재 checkout에는 `AGENTS.md`가 없지만 최신 main에는 있다. 최신 main의 `AGENTS.md`, `docs/RESEARCH_SPEC.md`, `docs/EXPERIMENT_PLAN.md`, `docs/AI_COLLABORATION.md`, `README.md`, 두 이해 가이드와 연구 코드를 확인했다.
- 논문 본문이나 요청의 제목/초록과 동일한 원고는 저장소·첨부에서 찾지 못했다. 따라서 **사용자가 제공한 수정 초록과 A–G 요구사항을 감사 기준**으로 삼았다.
- 저장소 문서와 새 초록 사이에는 명시적 차이가 있다. `docs/RESEARCH_SPEC.md`의 제목은 *Beyond Parser Ranking: Consequence-Aware Evaluation...*이고 상태는 `PROPOSED`다. 이 문서는 dependency-aware human verification, provenance graph, structural reach/repairability를 현재 연구 계약으로 정의하지 않는다. `research/README.md`도 연구 폴더가 초록 전체 시스템은 아니며 실제 결과가 없다고 명시한다. 어느 문서도 새 초록을 덮어쓰는 것으로 간주하지 않았다.

### 확인한 데이터와 산출물

- `research/work/financebench-source`의 HEAD는 FinanceBench 고정 commit `cc39aeb4afdf33909ee1412188bf89035950c2eb`와 일치했다.
- 공개 PDF 3개: Boeing 190쪽, Amcor 156쪽, Best Buy 75쪽, 합계 421쪽. SHA-256은 manifest와 일치했다.
- 준비 입력: 421 page-text blocks, 14 questions/gold rows. 질문 수는 Boeing 7, Amcor 4, Best Buy 3이다.
- 오류 사례: `boeing-digit-deletion-pilot-v1` 한 개, Boeing PDF 55쪽의 두 통제된 digit-deletion 후보 A/B. 자연 발생 parser 오류는 0개다.
- 저장된 `records.jsonl`, judgment, score summary, 실제 parser Canonical snapshot은 0개다. 즉 **논문 조건의 연구 실행 결과는 없다.**

## 2. 전체 요구사항 대조표

### A. 실제 파이프라인

| 요구사항·논문 주장 | 구현 상태 | 코드 근거 | 실행·결과 근거 | 문제와 영향 | 필요한 조치 |
|---|---|---|---|---|---|
| 이종 parser 출력을 공통 구조로 변환 | 부분 구현 | `backend/app/schemas/canonical_document.py:22-68`; `task_manager/pipeline.py:78-100`; Synap/Paddle normalizer; generic/Docling/MinerU의 text canonical 경로 | mock/단위 테스트만 확인; backend unit 82 통과, integration 6 통과·실제 Paddle 1 skip | 공통 schema와 adapter는 있으나 일부 adapter는 page/layout을 1-page text로 축약한다. 연구 데이터에서 여러 실제 parser 실행 증거가 없다. | 실제 parser별 version/config를 고정해 동일 문서 Canonical snapshot을 만들고 schema/좌표 보존을 검증한다. |
| VLM이 실제 이미지·layout을 입력받아 처리 | 미구현 | 연구 runner 입력은 text block allowlist뿐(`pipeline_runner.py:553-600`); backend PP-Structure는 PDF/image를 받지만 논문의 VLM stage로 연결되지 않음 | 코드 확인만 완료; 실제 Paddle 추론 test는 skip | 현재 연구 실행은 시각 입력, 이미지 region, layout feature를 downstream model에 전달하지 않는다. 멀티모달 주장을 뒷받침하지 못한다. | 명시적 VLM adapter, image/page crop 입력, model trace와 multimodal-required 평가 사례를 추가한다. |
| block→LLM 합성→chunking→검색→근거 QA 연결 | 부분 구현 | `pipeline_runner.py:792-1079`; model synthesis `816-893`, chunk `861-943`, BM25 `684-715`, QA `947-1023` | mock/단위 테스트 확인; 실제 모델 smoke는 **passthrough**→BM25→QA만 확인 | 실행 경로는 있으나 논문 데이터로 model synthesis까지 실제 실행한 증거가 없다. | 논문 설정을 고정하고 적어도 한 실제 문서에서 synthesis mode=model의 raw run을 보존한다. |
| 연구 경로가 backend CanonicalDocument/실제 parser 결과 사용 | 부분 구현 | `research/canonical_adapter.py:13-114` | mock/단위 테스트만 확인(`test_pipeline_runner.py:356-406`); 실제 Canonical 연구 입력 없음 | 변환 CLI만 있고 backend run을 자동 연결하거나 실제 snapshot으로 실험한 기록이 없다. | backend run ID에서 canonical artifact를 export해 candidate/case/run manifest까지 잇는 경로와 실제 기록을 만든다. |
| pypdf/mock/fixed response 범위가 분리됨 | 완료 | `pilot.py:106-213`; `make_boeing_case.py`; tests의 `FakeGenerator`; README의 명시적 제한 | 데이터 재생성 확인; 실제 모델 smoke 1회 별도 확인 | 분리는 잘 문서화됐지만, `score()`가 `test_fake_model`/metadata 부재를 자동 거부하지 않아 mock 결과도 기술적으로 점수화 가능하다. | 논문 결과 export 시 live execution mode, model/version, config, trace 필수 검증 gate를 추가한다. |

### B. Provenance graph와 추적

| 요구사항·논문 주장 | 구현 상태 | 코드 근거 | 실행·결과 근거 | 문제와 영향 | 필요한 조치 |
|---|---|---|---|---|---|
| node/edge/ID/page/좌표/source/parent-child 정의 | 부분 구현 | source block field `pilot.py:26-41`; Canonical adapter `54-70`; synthesis/chunk/retrieval/QA trace `pipeline_runner.py:829-1023` | mock/단위 테스트 및 작은 실제 QA smoke 확인 | trace와 ID는 있으나 명시적 provenance graph schema, edge type, candidate/output node 정의가 없다. | versioned graph schema와 node/edge invariants를 정의하고 artifact로 저장한다. |
| graph가 실제 실행 기록에서 downstream output까지 생성 | 부분 구현 | response의 `trace`; `run_case()`가 raw response를 records에 저장(`pilot.py:447-470`) | mock/단위 테스트만 확인; 저장된 논문 run 없음 | runner response는 chain trace지만 graph artifact/조회 API가 아니며 실제 연구 기록이 없다. | 각 실행에서 graph JSONL을 materialize하고 run/candidate/question/result IDs로 연결한다. |
| LLM 누락·병합·변형 후 근거 추적 | 부분 구현 | synthesis prompt의 `[source:BLOCK_ID]`; marker parsing과 batch fallback `pipeline_runner.py:867-879` | mock/단위 테스트만 확인 | marker가 없으면 chunk를 batch 전체 source에 연결한다. marker가 내용상 올바른지 검증하지 않으며 chunk 경계가 marker와 paragraph를 분리할 수 있다. 이는 semantic provenance가 아니라 보수적 연결이다. | span/claim 수준 attribution 검증, marker coverage/error metric, 불확실 provenance 상태를 추가한다. |
| structural reach/shared dependency/overlap 계산이 정의·구현과 일치 | 미구현 | 관련 함수·schema·수식 없음 | 코드 확인만 완료 | 초록 핵심 독립변수가 없다. | reach의 방향/가중치/질문 집합, shared descendant와 set overlap 수식을 사전 고정하고 테스트한다. |
| graph 연결을 실제 causal repair로 오인하지 않음 | 부분 구현 | 실제 A/B/AB 재실행과 README의 제한; `score()`의 관측 final utility | mock/단위 테스트만 확인 | 현재 코드는 둘을 등치하지 않지만 structural reach 자체가 없어 관계를 분석하지도 못한다. | structural metric과 counterfactual recovery를 별도 field로 저장하고 문서 단위로 비교한다. |

### C. 검증 대상 선택과 예산 배분

| 요구사항·논문 주장 | 구현 상태 | 코드 근거 | 실행·결과 근거 | 문제와 영향 | 필요한 조치 |
|---|---|---|---|---|---|
| candidate 단위·사용자·질문 집합·cost·budget 정의 | 부분 구현 | candidate는 정확히 A/B text span(`pilot.py:216-275`); 질문은 Boeing 고정 7개 | 코드 확인만 완료 | 사용자, 검증 action, cost model, review budget은 없다. model-call cap은 human verification budget이 아니다. | candidate schema에 stage/content/reviewer action/cost/eligibility를 넣고 budget 단위와 대상 질문 모집단을 동결한다. |
| parsing·LLM synthesis·downstream stage에서 후보 선택·개입 | 미구현 | 개입은 frozen source text의 두 span에만 적용(`pilot.py:278-299`) | mock/단위 테스트만 확인 | stage allocation이라는 초록 주장을 충족하지 않는다. | stage별 candidate 생성, 수정 계약, invalidation/rerun 경계를 구현한다. |
| risk, shared dependency, cost, expected repairability 반영 | 미구현 | 선택 정책 코드 없음 | 코드 확인만 완료 | 제안 방법 자체가 없다. | feature provenance와 점수 수식, set-dependent marginal-gain allocator를 구현한다. |
| 고정 개별 순위와 set-dependent 추가 이득 구별 | 미구현 | 관련 rank/optimizer 없음 | 코드 확인만 완료 | independent ranking 대비 기여를 시험할 수 없다. | individual score baseline과 marginal set selection을 같은 feature로 구현한다. |
| expected repairability가 pre-intervention 정보만 사용 | 미구현 | predictor 없음 | 코드 확인만 완료 | 현재 oracle leakage를 평가할 대상이 없다. | training/selection 시점 field를 분리하고 observed post-repair utility 접근을 차단한다. |
| 정상·무효 candidate도 후보군에 포함 | 미구현 | 두 후보 모두 정답 근거를 보고 만든 의도적 오류 | 코드 확인만 완료 | 쉬운 oracle candidate set으로 selection 성능이 부풀 수 있다. | blinded candidate enumeration에 정상/오탐/수정 불능 사례를 보존한다. |
| 확인했으나 수정하지 않은 경우도 cost 지불 | 미구현 | review event/cost ledger 없음 | 코드 확인만 완료 | 실제 검증 비용·효율을 계산할 수 없다. | inspect와 repair를 별도 event로 기록하고 inspection cost를 항상 차감한다. |
| 자동 정답 교정과 human verification 가정 구분 | 완료 | inverse repair 및 selection note `make_boeing_case.py:38-57`; README 제한 | 코드 확인만 완료 | 현재는 사람이 찾고 고치는 과정이 아니라 알려진 문자열을 정확히 복원하는 oracle action이다. 문서는 이를 숨기지 않는다. | 불완전 수정/거부/오수정 확률과 실제 검토 workflow를 별도 실험한다. |

### D. 개입과 downstream 재실행

| 요구사항·논문 주장 | 구현 상태 | 코드 근거 | 실행·결과 근거 | 문제와 영향 | 필요한 조치 |
|---|---|---|---|---|---|
| baseline/no-op/A/B/AB 조건 | 완료 | `CONDITIONS`와 `run_case()` `pilot.py:25,385-483` | mock/단위 테스트만 확인; 논문 case 실제 run 없음 | 실행 scaffold는 정확하나 저장된 연구 결과가 없다. | frozen 설정으로 raw five-condition run을 생성한다. |
| AB를 실제 동시 수정·재실행으로 측정 | 완료 | reverse-offset patch `278-299`; AB 조건; tests `85-97,168-204` | mock/단위 테스트만 확인 | union으로 합성하지 않는 점은 타당하다. | 실제 문서 반복 결과와 불확실성을 저장한다. |
| 수정 후 필요한 downstream을 fresh 실행, stale state 미사용 | 완료 | 조건마다 새 subprocess `pilot.py:418-470`; runner 내부 상태 fresh | mock/단위 테스트만 확인 | 외부 custom runner의 내부 cache까지 강제하지는 못한다. | execution ID/response ID uniqueness와 cache policy를 manifest gate로 검증한다. |
| no-op이 이전 LLM cache가 아닌 독립 호출 | 완료 | baseline/no-op 동일 입력을 각기 subprocess로 실행; `test_runner_executes...` | mock/단위 테스트만 확인 | provider stochasticity 분리를 위한 실제 반복 결과는 없다. | 충분한 repeat와 no-op variance를 보고한다. |
| 복구·새 오류·순복구·효과 소실 구분 | 부분 구현 | recovered/regressed/net `pilot.py:584-603` | mock/단위 테스트만 확인 | 최종 QA 복구·회귀는 구분하지만 중간 stage의 repair effect loss는 측정하지 않는다. | stage별 outcome과 final transition을 기록한다. |
| 실패·누락·timeout·미판정을 정답으로 집계하지 않음 | 완료 | response fail-closed `353-383`; incomplete run 거부 `490-517`; judgment 완전성 `551-569`; timeout test | mock/단위 테스트만 확인 | 한 조건 실패 시 전체 run이 미완료가 되어 분석 불가한 보수적 설계다. 실패 분포 분석 schema는 없다. | 실패/timeout을 raw outcome으로 유지하는 분석 테이블을 추가한다. |

### E. 데이터와 평가

| 요구사항·논문 주장 | 구현 상태 | 코드 근거 | 실행·결과 근거 | 문제와 영향 | 필요한 조치 |
|---|---|---|---|---|---|
| 실제 data, source/version, 독립 문서·질문·오류 수 | 부분 구현 | FinanceBench prepare/manifest `pilot.py:106-213` | 재생성·hash 확인: 3문서, 421쪽, 14질문; 실제 오류 case는 1문서·2주입 오류 | 데이터 provenance는 양호하나 평가 규모와 오류 다양성이 초록 주장에 부족하다. | 자연 오류를 포함한 독립 문서 표본과 inclusion ledger를 확장한다. |
| 자연 오류와 인위 오류 구분 | 완료 | case `source_note`, `intervention_mode`, README | 코드·data 확인만 완료 | 구분은 정확하지만 자연 오류 데이터가 없다. | 자연 오류 관찰/annotation artifact를 추가한다. |
| “자연 발생 오류에 근거한 통제 오류”의 관찰 사례·출처 | 미구현 | repository 검색 결과 없음; case가 명시적으로 `Not a naturally observed parser error` | 코드 확인만 완료 | 초록 문구를 뒷받침하지 못한다. | real parser error taxonomy와 각 corruption template의 source example을 연결한다. |
| long-document이면서 multimodal 필요 | 부분 구현 | 전체 75–190쪽 PDF를 page text로 추출 | 실제 data 준비 확인 | 길이는 실제지만 downstream 입력은 text-only이고 시각/layout 없이는 풀 수 없는 평가임이 입증되지 않았다. | image/table/layout-grounded 질문과 modality ablation을 포함한다. |
| gold·근거·repair 값·condition 누출 방지 | 부분 구현 | payload allowlist `pilot.py:284-313`; runner strict keys `pipeline_runner.py:553-600`; blind judgment template | mock/단위 테스트만 확인 | 모델 입력 누출 방지는 테스트됐다. 그러나 candidate 위치는 gold evidence를 보고 선택돼 allocation 평가에는 oracle leakage다. 외부 runner filesystem 격리도 없다. | candidate discovery와 test labels를 문서 단위로 분리하고 runner sandbox/manifest audit를 추가한다. |
| 학습/tuning의 document-level split | 미구현 | 학습 없음; manifest도 `pilot_only` | 코드 확인만 완료 | 현재는 적용 대상이 없지만 repairability predictor 주장을 시험할 split이 없다. | group split을 사전 생성하고 모든 corruption variant를 원문 문서 그룹에 묶는다. |
| 알려진 질문 개선과 future-question 일반화 구분 | 완료 | manifest/README가 pilot-only, no generalization임을 명시 | 코드·data 확인만 완료 | 현재 결과는 알려진 7질문 조건에 한정된다. | 일반화를 주장하려면 candidate selection 시 보지 않은 held-out questions를 둔다. |
| QA 판정 rule, 숫자 tolerance, unit/evidence, 자동 평가 검증 | 부분 구현 | blind template와 boolean `correct` `pilot.py:520-612` | mock/단위 테스트만 확인 | 판정 rubric, 수치 허용치, unit, evidence correctness, adjudication/자동 evaluator validation이 없다. | versioned rubric/schema, evidence label, double annotation 또는 validated evaluator를 추가한다. |

### F. 비교 실험과 분석

| 요구사항·논문 주장 | 구현 상태 | 코드 근거 | 실행·결과 근거 | 문제와 영향 | 필요한 조치 |
|---|---|---|---|---|---|
| random, uncertainty, output-only, individual-impact, proposed method | 미구현 | policy/baseline 코드 없음 | 코드 확인만 완료 | 초록의 비교 실험은 존재하지 않는다. | 동일 candidate pool/features/cost에서 다섯 정책을 구현한다. |
| 동일 질문·허용 정보·범위·cost·budget 비교 | 미구현 | experiment contract 없음 | 코드 확인만 완료 | 공정 비교를 판정할 수 없다. | machine-readable frozen experiment spec과 policy input allowlist를 만든다. |
| 여러 budget 실제 결과 | 미구현 | model call preflight cap만 존재 | 코드 확인만 완료 | human-review budget sweep와 결과가 없다. | 비용 단위별 budget grid를 사전 고정해 실행한다. |
| structural reach와 downstream recovery 관계 | 미구현 | reach 계산/분석 없음 | 코드 확인만 완료 | 초록 핵심 분석이 없다. | 문서-clustered 분석과 calibration/correlation을 구현한다. |
| stage별 intervention 효과 | 미구현 | source text span intervention만 존재 | 코드 확인만 완료 | parsing/LLM/downstream 배분 주장을 시험할 수 없다. | stage-stratified candidates와 cost-matched effect table을 만든다. |
| no-op variability와 intervention effect 구분 | 부분 구현 | no-op condition과 `no_op_net_change` `pilot.py:603` | mock/단위 테스트만 확인 | 한 baseline draw에 대한 차이만 저장하며 variance model/CI가 없다. | repeat 내 paired contrast와 document-clustered uncertainty를 사전 정의한다. |
| repeated model call을 독립 문서로 세지 않음 | 완료 | score scope와 experiment plan이 document unit을 명시; CI 출력 없음 | 코드 확인만 완료 | 잘못된 집계는 현재 없다. 실제 분석 코드도 아직 없다. | 향후 export/bootstrap에서 document clustering을 강제한다. |
| item count/cost를 human-time 절감으로 표현하지 않음 | 완료 | score scope `no ... human-time claim` | 코드 확인만 완료 | 현재 근거 없는 시간 절감 주장은 없다. | 시간 주장은 별도 사용자/시간 측정이 있을 때만 추가한다. |

### G. Provenance-aware interface

| 요구사항·논문 주장 | 구현 상태 | 코드 근거 | 실행·결과 근거 | 문제와 영향 | 필요한 조치 |
|---|---|---|---|---|---|
| source evidence, competing parses, affected downstream 결과를 실제 data로 표시 | 부분 구현 | parser comparison UI `frontend/src/pages/ComparePage.tsx`; original download `237-248`; parser columns `275-345` | frontend build 확인 | parser 결과/Canonical/diff는 표시하지만 원본 preview API는 없다고 UI가 명시(`233`). QA evidence, graph, affected downstream outputs는 표시하지 않는다. | provenance graph/query API와 source region/QA impact view를 추가한다. |
| 조회→수정→rerun→결과 확인 workflow | 미구현 | manual parser-quality score 저장만 있음 `ComparePage.tsx:506-599` | 코드 확인·frontend build | candidate repair editor, budget selection, rerun, before/after 결과가 없다. | intervention transaction, invalidation, rerun status와 result comparison UI를 연결한다. |
| mock/screen과 backend 작동 범위 구분 | 완료 | comparison service가 stored parser artifacts를 읽고 manual evaluation을 저장 | backend integration mock 및 frontend build 확인 | 기존 parser 비교 UI는 backend vertical slice가 있으나 연구 검증 UI는 존재하지 않는다. | 논문에서는 이를 “기존 parser comparison UI”로만 기술한다. |
| usability/cognitive load/time-saving user evaluation | 미구현 | 사용자 연구 schema/result 없음 | 코드 확인만 완료 | HCI 효과 주장을 할 수 없다. | 연구 설계·IRB/동의·task·metric을 정한 뒤 사용자 평가를 수행한다. |

## 3. 보완 방향 점검 — 초록 필수 구현과 별도

| 연구 강화 항목 | 상태 | 코드·수식 근거 | 논문 기여에 미치는 영향 |
|---|---|---|---|
| graph 연결 중복과 실제 repair-effect 중복 구별 | 미구현 | graph overlap/recovery-overlap 계산 없음 | structural redundancy를 causal redundancy로 오인하지 않게 하는 핵심 분석이 빠져 있다. |
| redundancy, complementarity, effect dissipation 구분 | 부분 구현 | 최종 QA에서 실제 AB 실행과 `I=G(AB)-G(A)-G(B)`만 구현 | 양/음 interaction은 허용하지만 이를 안정적으로 분류하거나 stage 소실을 측정하지 않는다. |
| 같은 feature/predictor의 individual ranking 및 simple dedup baseline | 미구현 | baseline policy 없음 | 제안법의 이득이 feature 우위인지 set-aware optimization 우위인지 분리할 수 없다. |
| risk/reach/repairability/overlap ablation | 미구현 | feature/allocator 없음 | 각 요소의 기여를 주장할 수 없다. |
| 여러 독립 문서·실제 parser 오류 재현 | 미구현 | 준비는 3문서이나 repair run case는 Boeing 1문서·합성 오류 2개 | 외적 타당도와 parser-error claim이 없다. |
| cost 및 imperfect repair sensitivity | 미구현 | review cost/repair success model 없음 | 인간 workflow에 대한 결론을 낼 수 없다. |
| 결과 기반 interface design implications | 미구현 | 결과·사용자 연구 없음 | 기존 UI 기능 설명 외 설계 시사점을 경험적으로 도출할 수 없다. |

### 구현된 utility/interaction의 정확한 범위

각 repeat `r`, 질문 `q`, 조건 `S`에 대해 정오를 `y[r,S,q]`라 하면 현재 코드는 다음 최종 QA 효용만 계산한다.

```text
G_r(S) = sum_q (y[r,S,q] - y[r,baseline,q])
       = recovered_count - regressed_count

I_r(A,B) = G_r(AB) - G_r(A) - G_r(B)
```

구현 위치는 `research/pilot.py:579-603`이다. `AB`는 A/B 복구 집합의 합집합이 아니라 실제 동시 수정 후 독립 재실행 결과다. 따라서 코드가 submodularity를 강제하거나 같은 answer descendant라는 이유만으로 redundancy를 확정하지는 않는다. 이는 장점이다.

다만 `I<0`만으로 실제 중복, `I>0`만으로 보완 효과를 확정할 수는 없다. 독립 model generation noise, no-op variation, 문서 표본 수와 판정 오류가 있기 때문이다. 현재는 반복/문서 수준 uncertainty 분석이 없고, graph overlap utility나 cost-adjusted set utility도 없다. effect dissipation을 보려면 synthesis/retrieval/QA 각 stage의 counterfactual outcome이 추가로 필요하다.

## 4. 실행·검증 결과

### 실행한 명령과 결과

| 검증 | 명령 요약 | 결과 | 증거 등급 |
|---|---|---|---|
| 연구 테스트 | `uv run --with pypdf==6.10.0 --with pytest==8.4.2 --with openai==2.54.0 python -m pytest research/tests -q` | 25 passed | mock 또는 단위 테스트만 확인 |
| 연구 lint | `uv run --with ruff==0.12.12 ruff check --config backend/pyproject.toml research` | all checks passed | 코드 확인만 완료 |
| backend unit | `cd backend && uv run pytest tests/unit -q` | 82 passed | mock 또는 단위 테스트만 확인 |
| backend integration | `cd backend && uv run pytest tests/integration -q -rs` | 6 passed, 1 skipped | mock/fixture integration; 실제 Paddle smoke는 미실행 |
| frontend | `npm ci`; `npm run build` | Vite build 성공, 153 modules | build 확인; 사용자 workflow 검증 아님 |
| dataset 재생성 | `research.pilot prepare`를 임시 경로에 실행 | 3문서, 421 blocks, 14 questions; blocks/questions/gold file hash가 기존과 동일 | 실제 data preparation 확인 |
| Boeing case 재생성 | `research.make_boeing_case` | 190 pages, 7 questions, 2 repairs | 실제 synthetic case preparation 확인 |
| OpenAI preflight | `pipeline_runner preflight ... runner.example.json ... --max-total-calls 70` | 5 pipeline runs, 70 calls, 최대 출력상한 462,000 tokens, API key 미설정 | 코드/preflight만 확인 |
| Ollama preflight | `... runner.ollama.example.json ... --max-total-calls 35` | 5 pipeline runs, 35 calls, 최대 출력상한 42,000 tokens | 코드/preflight만 확인 |
| 실제 local model smoke | 설치된 `llama3:latest`로 synthetic 1-block/1-question passthrough run | answer `123 million dollars`; execution ID `cb4144f2-074b-4f1a-9d59-11ab02d0c26b`; Ollama 0.30.6; model digest `365c0bd3...`; 277 tokens | **실제 모델 smoke test 확인**, 논문 실험 아님 |

데이터 입력의 재생성 hash는 일치했다. 단, 재생성된 case file은 `dataset_manifest_sha256`만 달랐다. dataset manifest의 `created_at`까지 digest에 포함하기 때문이다. 실제 blocks/questions/gold와 repair 내용은 동일하지만 case SHA와 deterministic condition order seed는 재생성 시 바뀐다. 논문 결과 재현성을 위해 content identity와 run timestamp identity를 분리하는 편이 낫다.

### 실행하지 못했거나 의도적으로 실행하지 않은 항목

- full Boeing five-condition model run: 저장된 실행 예산 승인이 없고, OpenAI API key도 설정되지 않았다. 임의 70-call 외부 실행을 하지 않았다.
- local example full run: example model `gemma3:4b`가 설치되어 있지 않았다. 설치 모델은 `llama3:latest`와 `nomic-embed-text:latest`뿐이었다. 설정을 몰래 바꿔 논문 결과를 생성하지 않았다.
- actual PaddleOCR integration: `RUN_PADDLEOCR_INTEGRATION_TESTS=1`이 없어 test suite가 명시적으로 skip했다. 실제 parser inference 증거로 세지 않았다.
- 실제 Synap/Docling/MinerU run: endpoint/config 및 저장된 artifact가 없어 코드·fixture 범위만 확인했다.

### 기존 테스트가 보장하는 것과 놓치는 것

보장하는 것: gold/condition/repair target payload 누출 방지, A/B offset과 동시 patch, 다섯 조건 독립 subprocess 호출, timeout/실패/누락/변조 fail-closed, blind judgment completeness, final recovery/regression/interaction, provider request parameter, trace lineage, Canonical ID/page/bbox 보존, parser adapter/normalizer의 기본 계약.

놓치는 것: 실제 model synthesis의 marker fidelity, long-context truncation, semantic provenance, real parser output의 연구 연결, visual input, actual error discovery, candidate selection/cost/budget, policy baselines, multiple budgets, evaluator validity, statistical analysis, UI intervention workflow, human usability. 테스트 통과 수는 이 항목들의 완료 증거가 아니다.

## 5. 심각한 문제 상위 5개

1. **제안 방법과 비교 정책이 없다.**
   - 증거: risk/reach/repairability/cost/overlap allocator와 random/uncertainty/output-only/individual-impact 코드가 전무하다.
   - 영향: 제목과 핵심 기여인 dependency-aware budget allocation을 시험할 수 없다.
   - 수정: 동일 candidate pool과 pre-intervention feature allowlist를 쓰는 다섯 정책, cost ledger, budget sweep를 구현한다.

2. **논문 조건의 실제 결과가 한 건도 없다.**
   - 증거: `research/work`에는 input/gold/case만 있고 `records.jsonl`, judgments, summary가 없다.
   - 영향: repair 효과, redundancy, stage 차이, 정책 우위에 관한 완료형 문장을 뒷받침할 수 없다.
   - 수정: frozen spec과 승인된 예산으로 raw runs→blind judgments→document-level analysis를 순서대로 보존한다.

3. **멀티모달/VLM/실제 parser 오류 평가가 아니다.**
   - 증거: 연구 입력은 pypdf 6.10.0 page text; 실제 case는 한 문서의 수동 digit deletion 두 개이며 source note가 자연 오류가 아님을 명시한다.
   - 영향: “multimodal long-document QA”와 “naturally occurring parser errors informed corruption” 주장이 성립하지 않는다.
   - 수정: 실제 parser pair의 자연 오류 ledger, image/layout-dependent 질문, VLM input trace를 추가한다.

4. **provenance trace는 있으나 dependency graph와 semantic attribution은 없다.**
   - 증거: marker가 없을 때 합성 batch 전체를 source로 연결하며 reach/shared-dependency/overlap 계산이 없다.
   - 영향: structural reach와 actual repairability를 구분·비교한다는 핵심 분석을 수행할 수 없고 영향 범위를 과대귀속할 수 있다.
   - 수정: graph schema, uncertain edge, marker coverage validation, reach/overlap metric과 counterfactual utility를 별도 저장한다.

5. **candidate selection과 평가가 allocation 연구에 유효하지 않다.**
   - 증거: 후보 위치를 gold evidence를 보고 선택했고 정상/무효 후보와 review cost가 없다. 정오 판정도 versioned rubric/evidence correctness 없이 boolean뿐이다.
   - 영향: selection performance는 oracle leakage로 부풀 수 있고, 비용 대비 효용 및 근거 기반 QA 품질을 신뢰할 수 없다.
   - 수정: blinded candidate generation, normal/irreparable candidates, inspect-versus-repair cost, 숫자/unit/evidence rubric과 adjudication을 동결한다.

## 6. 남은 작업 우선순위

### P0 — 결과를 내기 전 반드시 막아야 할 validity 문제

- gold evidence를 본 Boeing 두 후보로 selection/allocation 성능을 보고하지 않는다. causal plumbing debug에만 사용한다.
- result acceptance gate가 `execution_mode=live_*`, model/digest/config/prompt/code/input hash, 완전한 trace를 요구하도록 한다. 현재 `score()`는 metadata 없는 fake runner도 점수화할 수 있다.
- versioned QA rubric에 numerical tolerance, sign/unit, evidence correctness, insufficient-evidence, adjudication을 정의하고 미판정/불일치/실패를 별도 outcome으로 둔다.
- document-group split과 분석 단위를 사전 고정해 같은 문서의 corruption/repeat가 train/test 또는 독립 표본으로 섞이지 않게 한다.
- no-op stochasticity를 repair effect에서 분리할 paired estimand와 document-clustered uncertainty를 실험 전에 고정한다.

### P1 — 현재 초록 핵심 주장을 충족하기 위한 작업

- versioned provenance graph와 structural reach/shared descendant/overlap 구현.
- parsing, synthesis, downstream candidate와 stage별 intervention/rerun 구현.
- pre-intervention risk 및 expected-repairability predictor와 feature provenance 구현.
- random, uncertainty, output-only, individual-impact, proposed set-aware allocation의 cost-matched 구현.
- 실제 parser Canonical outputs, VLM/visual inputs, 자연 오류 기반 corruption set으로 여러 budget 실행.
- structural reach–actual recovery, redundancy/complementarity, stage 효과 분석.
- source evidence/competing parse/affected output 조회와 repair/rerun까지 잇는 연구용 interface.

### P2 — 일반화와 연구 강화

- 같은 predictor를 쓰는 individual ranking 및 simple dedup 비교.
- risk/reach/repairability/overlap ablation.
- parser/document/language/layout strata 확장과 external replication.
- review cost와 imperfect repair sensitivity.
- 결과 기반 design implications; 효율/인지부담 주장은 별도 사용자 연구 후에만 제시.

## 7. 현재 증거로 가능한 초록 표현

### 유지 가능한 축소 표현

- “We implement a reproducible paired-repair pilot that independently reruns baseline, no-op, A-only, B-only, and joint A+B conditions.”
- “The runner can connect optional text synthesis, deterministic character chunking, BM25 retrieval, and evidence-ID-constrained QA while recording execution traces.” 단, 실제 확인 범위는 tiny local-model QA smoke와 fake-model synthesis test임을 함께 쓴다.
- “We prepare a small debugging pilot from three public long financial PDFs and create two controlled digit-deletion corruptions in one pypdf-extracted Boeing document.”
- “The existing application supports side-by-side parser-output comparison and manual parser-quality ratings.”

### 축소·삭제하거나 추가 증거가 필요한 표현

- “I evaluate ... across multiple verification budgets” — 삭제. 결과와 budget allocator가 없다.
- “compare graph-aware allocation with random, uncertainty-based, output-only, and individual impact” — 삭제. 모두 미구현이다.
- “model component dependencies with a provenance graph” — 현재는 execution trace뿐이므로 축소하거나 graph 구현 후 사용한다.
- “distinguish structural reach from actual repairability” 및 둘의 관계 분석 — reach 구현·실험 후에만 사용한다.
- “multimodal ... VLM” — image/layout input과 VLM run 없이는 삭제한다.
- “controlled corruptions informed by naturally occurring parser errors” — 현재는 “two hand-designed controlled digit deletions”로 바꾼다.
- “allocate across parsing, LLM synthesis, and downstream stages” — stage candidate/intervention 구현 전 삭제한다.
- “provenance-aware interface ... affected downstream results” — 현재 parser comparison UI와 혼동하지 말고 연구 UI가 연결된 뒤 사용한다.
- human effort, usability, cognitive load, time saving — 사용자 평가 전에는 주장하지 않는다.

## 8. 역할별 체크리스트

### Codex가 처리할 구현 작업

- [ ] graph/candidate/review-event/cost/run/evaluation versioned schema와 invariants 구현
- [ ] backend Canonical artifact→research manifest 자동 연결 및 실제 parser fixture 추가
- [ ] stage별 patch/invalidation/fresh rerun 엔진과 provenance graph artifact 구현
- [ ] five-policy baseline, set-aware allocator, budget sweep, ablation 구현
- [ ] live-result acceptance gate와 failure/timeout analysis export 구현
- [ ] versioned evaluator interface와 evidence-aware test suite 구현
- [ ] provenance-aware UI/API의 source region→candidate→affected output→repair→rerun vertical slice 구현
- [ ] document-grouped analysis와 reproducible raw/derived/report artifact 생성

### 수현이 결정·검토해야 할 연구 작업

- [ ] target reviewer와 실제 verification action, candidate granularity, 비용 단위 확정
- [ ] 대상 질문이 known set인지 future questions인지와 primary estimand 확정
- [ ] 자연 parser 오류 수집·annotation protocol과 corruption inclusion rule 승인
- [ ] dataset/document strata, train/validation/test group split, budget grid 동결
- [ ] QA 정오·숫자 tolerance·unit·evidence rubric과 adjudication 승인
- [ ] expected repairability에 허용할 pre-intervention 정보와 oracle boundary 승인
- [ ] 실제 model/parser 호출 예산·provider/model/version 승인
- [ ] interface contribution을 design implication으로 둘지 사용자 연구를 수행할지 결정
- [ ] 새 dependency-aware 초록과 기존 `RESEARCH_SPEC.md`의 연구 계약을 정합화

## 9. 바로 다음에 수행할 작업 한 가지

**모델을 더 호출하기 전에 `experiment_spec_v1`을 기계 판독 가능한 형태로 동결한다.** 여기에는 reviewer, candidate unit/stage, 대상 질문 모집단, pre-intervention feature allowlist, normal/irreparable candidate 포함 규칙, inspect/repair cost, budgets, 다섯 비교 정책, document-group split, QA/evidence rubric, primary estimand와 no-op 처리법을 반드시 넣는다. 이 계약이 없으면 다음 실제 실행도 pipeline smoke test일 뿐 allocation 실험 증거가 되지 않는다.

