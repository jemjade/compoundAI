# 수정 효과를 측정하기 위한 첫 파일럿

## Dependency-aware upstream pilot v1

`research/specs/experiment_spec_v1.json` is the frozen contract for the first
selection-policy wiring experiment. It is deliberately limited to controlled numeric text spans
from one pypdf document. It does not implement or claim multimodal evaluation, natural parser
errors, cross-stage allocation, an output-only baseline, multiple independent documents, or a
human-interface evaluation.

The policy implementation is split at an explicit leakage boundary:

- `research/allocation.py` sees corrupted blocks plus independently executed baseline/no-op traces
  and implements Random, Uncertainty, Individual impact, and Graph-aware selection.
- `research/allocation_pilot.py` serializes those policy inputs and selections before joining the
  selected spans to evaluation-only ideal repair labels and launching fresh downstream reruns.
- Every candidate costs one verification unit, including normal candidates that produce no edit.
  The unit is not human time.

Preflight the frozen two-question local experiment before making model calls:

```bash
python3 -m research.allocation_pilot preflight \
  --case research/work/boeing-case.json \
  --spec research/specs/experiment_spec_v1.json \
  --config research/configs/dependency_aware_pilot_llama3_v1.json \
  --max-total-calls 26
```

The `run` command requires a clean tracked worktree so that the committed spec and code precede
the live artifact. Outputs belong in the ignored, append-only `research/work/` directory. After a
run, create a blind judgment template, apply the narrow deterministic pilot judge, and score it:

```bash
python3 -m research.allocation_pilot run \
  --case research/work/boeing-case.json \
  --spec research/specs/experiment_spec_v1.json \
  --config research/configs/dependency_aware_pilot_llama3_v1.json \
  --out research/work/dependency-aware-pilot-v1-run-001 \
  --max-total-calls 26

python3 -m research.allocation_pilot judge-template \
  --run research/work/dependency-aware-pilot-v1-run-001 \
  --gold research/work/financebench-pilot/evaluation/gold.jsonl \
  --out research/work/dependency-aware-pilot-v1-run-001/judgments.template.jsonl

python3 -m research.allocation_pilot auto-judge \
  --template research/work/dependency-aware-pilot-v1-run-001/judgments.template.jsonl \
  --out research/work/dependency-aware-pilot-v1-run-001/judgments.jsonl

python3 -m research.allocation_pilot score \
  --run research/work/dependency-aware-pilot-v1-run-001 \
  --judgments research/work/dependency-aware-pilot-v1-run-001/judgments.jsonl \
  --out research/work/dependency-aware-pilot-v1-run-001/summary.json
```

The deterministic judge requires all reference numbers and a gold evidence block citation. It is
a strict plumbing evaluator, not a validated general FinanceBench judge; alternate evidence pages
must be reviewed manually.

**현재 완료:** 실제 공개 PDF·QA 준비 코드, 숫자 오류 주입 사례, 무수정/A/B/AB
실행·기록·평가 절차, 로컬 Ollama 또는 OpenAI Responses API 합성·문자 청킹·BM25
검색·근거 기반 QA 실행기.

`research/pipeline_runner.py`는 첫 실제 공급자 어댑터이고
`research/canonical_adapter.py`는 backend `CanonicalDocument` 스냅샷을 연구 입력으로
변환한다. 이 폴더 자체가 초록의 전체 시스템을 구현한 것은 아니다. 테스트 통과,
데이터 준비 수치, 테스트용 가짜 응답을 논문의 복구 성능으로 사용하지 않는다.

## 첫 실제 allocation 실행 결과

동결된 v1 명세로 로컬 `llama3:latest`를 26회 호출한 run 001을 완료했다. 구현 연결은
완료됐지만 BM25 top-k 후보군에 두 주입 오류가 있는 p55가 들어오지 않아 모든 정책이
정상 후보만 검사했고, 복구·악화·순복구는 모두 0이었다. 이는 정책 우수성 결과가 아니라
후보 recall 실패를 드러낸 exploratory wiring 결과다.

- 상세 보고서: `research/reports/dependency-aware-pilot-v1-run-001.md`
- 추적 가능한 요약: `research/results/dependency-aware-pilot-v1-run-001-summary.json`
- 원시 산출물: `research/work/dependency-aware-pilot-v1-run-001/` (Git 제외)
- 후속 변경안: `research/specs/experiment_spec_v1_1_change_proposal.md`

동결된 v1은 소급 변경하지 않으며 run 001을 독립 최종 평가로 재사용하지 않는다.

## v1.1 후보/근거 접근 진단

run 001의 후보 누락과 downstream 근거 접근 실패를 분리하기 위해 v1.1 development
diagnostic을 실행했다. 전체 문서의 숫자 span 6,777개를 열거해 A/B 후보 포함률은 2/2가
됐지만, 95.23%가 기존 top-k trace 기준 reach 0이고 모든 후보가 점수 동점 그룹에
속했다. A/B는 6,451개 정상 후보와 동일한 특징을 가져 어떤 scored policy도 선택하지
못했다.

일반 검색은 gross-margin 유효 근거를 찾지 못했다. 복구된 p55 전체를 강제로 제공한 D는
방향만 맞히고 필수 수치·계산을 생략했으며 tax는 답하지 못했다. 문맥은 잘리지 않았지만
pypdf의 flattened 표에서 gross-profit 행 라벨이 사라져 evidence representation과 QA
reasoning을 아직 분리할 수 없다. 동결 stop rule에 따라 더 큰 정책 비교는 중단했다.

- 명세: `research/specs/experiment_spec_v1_1.json`
- 데이터 연결 감사: `research/reports/dependency-aware-pilot-v1_1-data-linkage.md`
- 실행 보고서: `research/reports/dependency-aware-pilot-v1_1-diagnostic-run-002.md`
- 추적 요약: `research/results/dependency-aware-pilot-v1_1-diagnostic-run-002-summary.json`
- 원시 산출물: `research/work/preserved-dependency-aware-pilot-v1_1-diagnostic-run-002/`

## v1.2 QA evidence/output contract 진단

v1.1 D의 방향 정답과 수치 설명 누락을 분리하기 위해 결론 정확도, 실제로 명시한
수치의 정확도, 필수 정량 설명의 완결성, 근거 충분성을 별도 판정한다. 수치를 전혀
쓰지 않은 답변은 잘못된 수치가 아니라 `NOT_APPLICABLE_NO_NUMBERS`와 설명 누락으로
기록한다. 모든 참조 숫자를 반복할 필요는 없고, 두 기간의 마진과 타당한 계산 근거를
보인 동등 설명을 허용한다.

로컬 llama3로 flat/old prompt, flat/quantitative prompt, human-verified table/quantitative
prompt를 손상·A+B 상태에서 각각 실행했다. 명시적 계약은 수치 출력을 유도했지만 잘못된
계산도 드러냈고, 표 표현까지 포함해 완결된 정답은 없었다. p55의 3,502/3,017 행은 PDF
원문 자체에서 라벨이 비어 있음을 직접 확인했다. 표 직렬화는 oracle representation일
뿐 자동 파서 구현이 아니다.

- 명세: `research/specs/experiment_spec_v1_2.json`
- 개입 타당성 감사: `research/reports/dependency-aware-pilot-v1_2-intervention-validity.md`
- 실행 보고서: `research/reports/dependency-aware-pilot-v1_2-qa-contract-run-003.md`
- 추적 요약: `research/results/dependency-aware-pilot-v1_2-qa-contract-run-003-summary.json`
- 원시 산출물:
  `research/work/preserved-dependency-aware-pilot-v1_2-qa-contract-run-003/`

최종 판정은 v1.2.2다. 실행 후 발견한 negation/숫자 파싱 버그의 수정 이유와 이전 판정
보존 정책은 `research/specs/experiment_spec_v1_2_evaluator_correction.md`에 기록했다.
이 진단은 QA 계약 연결을 검증했을 뿐 정책 비교 준비 완료를 뜻하지 않는다.

## 지금 만들어진 자료

2026-09-07 다음 입력을 실제 생성했다.

| 원본 문서 | 전체 PDF 페이지 | 선택된 QA |
|---|---:|---:|
| Boeing 2022 10-K | 190 | 7 |
| Amcor 2023 10-K | 156 | 4 |
| Best Buy 2023 10-K | 75 | 3 |
| 합계 | **421** | **14** |

출처는 [FinanceBench 공식 저장소](https://github.com/patronus-ai/financebench)의 공개 150문항이다. 고정 커밋은 `cc39aeb4afdf33909ee1412188bf89035950c2eb`이다. 데이터 제공자 표기는 [CC-BY-NC-4.0](https://huggingface.co/datasets/PatronusAI/financebench)이며, 비상업적 학술 파일럿으로 사용한다. 원본 PDF의 권리를 코드의 라이선스로 덮어쓰지 않는다.

선정은 실행 경로 확인을 위한 명시적 소규모 선택이다. 모델 결과를 보고 선택한 것이 아니며, 대표 표본·훈련/시험 분할·최종 벤치마크 성능을 주장하지 않는다. 선택한 문서의 질문 중 다른 문서의 근거가 필요한 질문은 제외하고 그 목록을 기록한다.

현재 추출기는 `pypdf 6.10.0`의 페이지별 텍스트 추출이다. VLM이나 표 셀 구조 인식 성능을 측정한 것은 아니다. Boeing PDF 60페이지는 텍스트가 추출되지 않아 manifest에 기록했다. OCR 결과나 정답의 근거 문자열로 이를 몰래 채우지 않는다.

## 현재 다음 행동 한 가지

**독립 문서에서 오류 후보를 정상 후보와 구별할 비-gold 특징, 서로 다른 downstream
의존 구조, 최종 지표를 바꾸는 수정이 함께 존재하는 사례군을 동결한다.**

Boeing 개발 결과를 계속 튜닝하고 독립 평가로 재명명하지 않는다. 같은 후보·정보·비용·
예산 규칙에서 정책을 비교하며, Individual/Graph가 같은 집합을 고르거나 후보·검색이
실패한 사례도 삭제하지 않는다.

## 1. 데이터 다시 준비하기

저장소 루트에서 실행한다. 데이터와 실행 결과는 `research/work/`에 두며 Git 추적에서 제외한다. 원본 저장소 전체 PDF를 받을 필요는 없다.

```bash
git clone --depth 1 --filter=blob:none --no-checkout https://github.com/patronus-ai/financebench.git research/work/financebench-source
git -C research/work/financebench-source sparse-checkout set --no-cone '/data/' '/README.md' '/pdfs/BOEING_2022_10K.pdf' '/pdfs/AMCOR_2023_10K.pdf' '/pdfs/BESTBUY_2023_10K.pdf'
git -C research/work/financebench-source fetch --depth 1 origin cc39aeb4afdf33909ee1412188bf89035950c2eb
git -C research/work/financebench-source checkout cc39aeb4afdf33909ee1412188bf89035950c2eb

uv run --with pypdf==6.10.0 python -m research.pilot prepare \
  --source research/work/financebench-source \
  --out research/work/financebench-pilot
```

인터넷을 쓸 수 없는 실행 환경에서는 같은 커밋의 `data/`와 필요한 `pdfs/`를 로컬에 준비하고 `--source`로 지정한다. 파일 해시와 예상 원본 커밋은 manifest에 기록되며, 임의로 복사한 디렉터리가 그 커밋과 같다는 사실까지 자동으로 인증하지는 않는다.

생성 파일:

- `inputs/blocks.jsonl`: **전체 PDF**에서 추출한 페이지 텍스트. 모든 페이지가 포함된다.
- `inputs/questions.jsonl`: 질문 ID·문서 ID·질문만 포함한다.
- `evaluation/gold.jsonl`: 정답과 근거. 모델 입력에 전달하지 않는다.
- `manifest.json`: 출처, 라이선스 카드, 선택·제외 기준, 파일 해시, 추출기, 페이지 수.

FinanceBench의 근거 페이지는 0부터 센다. 코드에서는 1부터 세는 PDF 페이지 번호로 변환한다. 예를 들어 근거 인덱스 54는 PDF 55페이지이며, 보잉 문서 안에 인쇄된 페이지 번호는 53이다.

## 2. 소스 확인을 마친 숫자 오류 사례 만들기

```bash
python -m research.make_boeing_case \
  --dataset research/work/financebench-pilot \
  --out research/work/boeing-case.json
```

이 사례는 보잉 PDF 55페이지의 숫자 두 개에 의도적인 자릿수 누락을 적용한다.

| 후보 | 원본에서 확인한 값 | 의도적으로 바꾼 값 |
|---|---|---|
| A: 2022 Total revenues | `66,608` | `6,608` |
| B: 2022 Total costs and expenses | `63,106` | `6,106` |

원본 괄호는 유지한다. 수정 조건은 해당 숫자를 원래 추출값으로 되돌린다. 원본 페이지는 시각적으로 확인했지만, 전체 추출 문서가 정답이라고 보증하는 것은 아니다.

이것은 **자연 발생 파서 오류가 아닌 통제된 오류**다. 후보 위치는 정답의 근거를 참고해 골랐으므로 **검증 대상을 미리 모르는 배분 정책의 성능 평가에 사용할 수 없다.** 또한 전체 문서의 다른 위치에 같은 사실이 남아 있다. 모델이 다른 근거로 답하거나 오류를 스스로 해소할 수 있으며, 그런 경우도 그대로 기록해야 한다.

다른 사례를 만들 때는 `make-case --inputs ... --document ... --repairs edits.json --case-id ... --out ...`을 사용한다. `--inject`가 없으면 기존 오류에 대한 수정, 있으면 정상 추출값을 의도적으로 바꾸고 이를 되돌리는 사례를 만든다. `edits.json`에는 후보 A/B, 블록 ID, 원래 문자열 기준 start/end, before/after, 원본 확인 방법을 담는다. 중복·겹치는 패치나 오래된 위치는 거부된다.

## 3. 실제 파이프라인 실행기 계약

실행기는 **표준 입력으로 JSON 한 개**를 받고 **표준 출력으로 JSON 한 개**를 돌려주는 프로그램이다. 로그는 표준 오류로 보낸다. Python, 사내 API 클라이언트, 로컬 모델 호출 프로그램 모두 연결할 수 있다.

입력 필드:

```json
{
  "schema_version": 1,
  "repeat_id": 0,
  "blocks": [{"block_id": "doc:p1", "document_id": "doc", "page_number": 1, "text": "현재 조건의 파서 출력"}],
  "questions": [{"question_id": "q1", "document_id": "doc", "question": "질문"}]
}
```

출력 형식:

```json
{
  "answers": [{"question_id": "q1", "answer": "실제 생성 답변", "evidence_block_ids": ["doc:p1"]}],
  "metadata": {"model": "실제 모델 식별자", "prompt_version": "고정 프롬프트 버전"},
  "trace": [{"stage": "synthesis", "input_ids": ["doc:p1"], "output_id": "s1"}]
}
```

`research/pipeline_runner.py`가 이 계약의 실제 구현이다. `synthesis_mode=model`은
OpenAI Responses API 또는 로컬 Ollama로 각 블록 배치를 합성하고,
`synthesis_mode=passthrough`는 원문 블록을 그대로 사용한다. 이후 문자 단위 중첩 청킹,
BM25 검색, 질문별 근거 기반 QA를 수행한다. QA는 검색된 청크 ID만 허용하는 JSON schema
출력을 요청하고 후처리에서도 다시 검증한다. 모든 질문에 정확히 한 번씩 답해야 하며
존재하지 않는 근거 ID는 거부된다.

각 실행에는 다음이 저장된다.

- 합성의 실제 입력·출력, 원본 블록 ID와 span, 공급자 response ID 및 토큰 사용량
- 합성→청크 부모·자식 ID, 청크의 원본 블록 ID
- 질문, 검색 대상 청크 ID, 검색 결과 본문·BM25 점수
- QA의 실제 입력·원시 출력, 답변, 청크 근거와 원본 블록 근거
- 파이프라인 실행 ID, 요청/응답 모델, SDK 버전, 프롬프트 버전·해시,
  적용된 생성 설정, 코드·입력 해시, 호출 수, 토큰 사용량, 시작·종료 시각

모델에 전체 190페이지를 한 프롬프트로 붙이는 방식으로 연결할 필요는 없다. 실행기 내부에서 합성·청킹·검색을 수행하되, 어느 입력이 사용됐는지 추적한다. 현재 저장소의 실제 파서 Canonical 결과로 확장할 때에는 `(document_id, run_id, block_id)`와 원본 페이지·좌표를 보존한다.

입력에 gold, 정답 근거, 패치의 정답값, 조건 이름을 보내지 않는 whitelist를 적용했다. 다만 이것은 파일시스템 격리가 아니다. 외부 실행기는 신뢰할 수 있어야 하고, 별도 `evaluation/` 파일이나 사례 정의를 읽지 않도록 검토해야 한다.

### 설정과 호출량 사전 확인

로컬 실행은 `research/runner.ollama.example.json`, OpenAI 실행은
`research/runner.example.json`을 복사해 추적되지 않는 `research/work/runner.json`에서
모델과 URL, timeout, 재시도, 합성 배치, 청크, 검색, 출력 토큰 상한을 바꾼다. OpenAI
API 키 값은 JSON에 쓰지 않고 `api_key_env`가 가리키는 환경변수에만 둔다. 같은 항목의
`RESEARCH_*` 환경변수는 JSON보다 우선한다. `temperature`와 `top_p`는 동시에 설정할
수 없고, 모델이 지원하지 않는 항목은 `null`로 두어 요청에서 제외한다.

### 로컬 Ollama 실행

Ollama provider는 문서가 외부 host로 전달되지 않도록 loopback HTTP 주소만 허용한다.
API 키는 필요하지 않으며 실행 시 Ollama 버전, 설치 모델 digest, parameter size와
quantization을 provenance에 기록한다. 먼저 서버와 모델을 확인한다.

```bash
ollama serve
ollama list
```

모델 호출 없는 사전 점검과 실제 실행은 아래 설정을 사용한다.
로컬 예시는 `synthesis_mode=passthrough`로 원문 블록을 결정적으로 청크화하고 QA만
Ollama에서 실행한다. 따라서 입력 텍스트, 블록 ID, 페이지·좌표 계보는 그대로 남고
모델이 문서를 재작성하지 않는다. 이는 모델 합성을 사용하는 OpenAI 예시와 다른
탐색 실행 조건이므로 두 결과를 동일 조건처럼 비교하면 안 된다.

```bash
python3 -m research.pipeline_runner preflight \
  --case research/work/boeing-case.json \
  --config research/runner.ollama.example.json \
  --repeats 1 --max-total-calls 35

python3 -m research.pilot run \
  --case research/work/boeing-case.json \
  --out research/work/boeing-ollama-run-004 \
  --repeats 1 --timeout 7200 \
  -- python3 -m research.pipeline_runner run \
    --config research/runner.ollama.example.json
```

출력 디렉터리는 덮어쓰지 않으므로 재실행할 때마다 새 번호를 사용한다.

`temperature=0`도 완전한 결정성을 보증하지 않는다. 모델 tag는 바뀔 수 있으므로 결과의
`provider_runtime.model_digest`를 함께 비교해야 한다.

### OpenAI Responses API 실행

기본 예시는 공식 문서상 Responses API, reasoning effort `none`~`max`, structured
outputs를 지원하는 `gpt-5.6-terra`를 사용한다. 계정 접근성과 가격은 별도로 확인해야
한다. 구현은 OpenAI Python SDK `2.54.0`에 고정되어 있고 Responses API의
`instructions`, `input`, `max_output_tokens`, `store=false`, `reasoning`, `text`, 토큰
usage와 완료 상태를 사용한다.

- [Responses API create 공식 문서](https://developers.openai.com/api/reference/python/resources/responses/methods/create)
- [GPT-5.6 Terra 공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-5.6-terra)

모델 호출 없이 먼저 정확한 파이프라인·내부 호출 수와 최악의 출력 토큰 상한을 본다.

```bash
python3 -m research.pipeline_runner preflight \
  --case research/work/boeing-case.json \
  --config research/runner.example.json \
  --repeats 1 --max-total-calls 70
```

현재 보잉 pypdf 사례와 예시 설정에서는 5개 독립 파이프라인 실행, 실행당 합성 7회와
QA 7회, 총 모델 호출 70회다. 예시는 SDK 재시도를 0으로 두므로 네트워크 재시도로 호출
수가 숨겨지지 않는다. 최대 출력 토큰 상한은 462,000이지만 실제 사용량이나
비용을 뜻하지 않는다. `--max-total-calls`를 넘으면 exit code 2로 실제 호출 전에
중단한다.

### 실제 5조건 실행

API 키는 실행 환경에서 설정하며 명령 인수나 로그에 넣지 않는다. 최초 실행은 보잉
사례 1개, 반복 1회로 제한한다.

```bash
export OPENAI_API_KEY=...  # 셸에서만 설정; 파일/채팅/Git에 넣지 않는다

python3 -m research.pilot run \
  --case research/work/boeing-case.json \
  --out research/work/boeing-run-001 \
  --repeats 1 --timeout 900 \
  -- uv run --with-requirements research/requirements.txt \
    python -m research.pipeline_runner run --config research/runner.example.json
```

출력 디렉터리는 덮어쓰지 않는다. `manifest.json`은 완료된 파이프라인/모델 호출 수와
토큰 합계를, `records.jsonl`은 조건별 raw response와 전체 trace를 저장한다. 실제 모델
결과는 `metadata.execution_mode=live_model`, 테스트 fixture는 `test_fake_model`로
구분한다. 실패·시간초과·빈 응답·`completed`가 아닌 응답은 run을 실패 상태로 남기고
점수 계산을 막는다.

각 반복에서 기준 실행, 무수정 재실행, A만 수정, B만 수정, A+B 수정의 순서를 섞어 실행한다. 이 도구는 결과를 조건 간 재사용하지 않는다. 외부 실행기에서도 무수정 대조군을 과거 응답 캐시로 대체하지 않아야 한다. seed만으로 모델의 결정성을 보증하지 않는다.

### backend CanonicalDocument 입력

실제 parser의 `CanonicalDocument.model_dump()` JSON 스냅샷은 다음처럼 변환한다.

```bash
python3 -m research.canonical_adapter \
  --canonical research/work/parser-run/canonical.json \
  --questions research/work/financebench-pilot/inputs/questions.jsonl \
  --out research/work/canonical-pilot-input
```

변환 결과에는 `source_kind=canonical_parser`가 붙고 document/run/original block ID,
page, bounding box, reading order, parser name/version, page 크기가 보존된다. page와 block의
page 번호가 모순되면 변환을 거부한다. 이 경로는 `source_kind=pypdf_page_text`인 pypdf
page-text 기준과 manifest에서 명확히 구분한다. Canonical 입력으로 보잉 수정을 실험할
때는 해당 parser 출력의 실제 span에 맞춰 별도의 사전 고정 repairs 파일과 case를 만들어야
하며, pypdf offset을 재사용하면 안 된다.

## 4. 결과 평가

재무 서술형 답변에 단순 문자열 일치율을 적용하면 맞는 답변도 틀렸다고 셀 수 있다. 이 코드에서는 실행과 판정을 분리했다.

```bash
python -m research.pilot judge-template \
  --run research/work/boeing-run-001 \
  --gold research/work/financebench-pilot/evaluation/gold.jsonl \
  --out research/work/boeing-judgments.jsonl
```

이 파일에는 질문·생성 답변·정답·근거가 포함되지만 조건과 반복 번호는 보이지 않는다. 정해진 판정 규칙에 따라 `correct`를 true/false로, `judge_id`를 실제 판정자나 평가기 ID로 채운다. 부정확하거나 부족한 근거가 있으면 원본 PDF로 확인한다. 나중에 자동 평가기를 붙여도 별도 검증이 필요하다.

```bash
python -m research.pilot score \
  --run research/work/boeing-run-001 \
  --judgments research/work/boeing-judgments.jsonl \
  --out research/work/boeing-summary.json
```

집계는 다음을 포함한다.

- 기준 대비 복구된 질문과 **새로 틀린 질문**
- 순복구 수와 정확도
- 무수정 재실행의 변화량
- 직접 동시 수정한 결과를 사용한 상호작용: `G(AB) - G(A) - G(B)`

상호작용은 음수·양수 모두 허용한다. A와 B 각각의 복구 집합의 합집합으로 AB 결과를 만들어내지 않는다. 같은 문서의 반복 실행을 독립 문서로 취급한 신뢰구간이나 사람의 시간 절감 수치를 출력하지 않는다. 완료되지 않은 실행, 빠진 판정, 변경된 입력·출력은 점수 산출에서 거부한다.

## 검증

저장소 루트에서:

```bash
uv run --with pypdf==6.10.0 --with pytest==8.4.2 --with openai==2.54.0 \
  python -m pytest research/tests -q
uv run --with ruff==0.12.12 ruff check --config backend/pyproject.toml research
```

테스트는 정답 필드 분리, 동시에 적용되는 길이가 다른 패치, 주입·복구의 역변환,
누락·중복·빈·미완료 응답, 실패·시간초과 처리, 출력 변경 감지,
중복·상호보완·새 오류 집계, 무수정 독립 호출, 단계 trace와 lineage, 생성 파라미터,
Canonical ID·좌표 보존을 검증한다. 테스트 안의 답변은 전부 합성 fixture이며 연구 결과가
아니다.

## 현재 남은 연구 작업

1. 연결 정보와 명시적 예산으로 실제 모델 5조건을 실행하고 판정해 첫 결과표 생성.
2. 실제 parser별 CanonicalDocument 스냅샷에서 별도의 사전 고정 사례 실행.
3. 자연 발생 오류 표본과 더 많은 문서·조건으로 확장.
4. 추정기 개발용·평가용 문서를 분리하고, 정답을 모르는 배분 방법 및 기준 방법 구현.
5. 그래프 영향 범위와 실제 복구를 비교할 연구 설계, 비용 가정, HCI 기여 및 선행연구 대조 완성.

본 파일럿만으로 CHI 제출 준비나 채택 가능성을 주장하지 않는다. 지금 초록의 완료형 실험 주장은 실제 결과가 확보된 범위에 맞춰 다시 정리해야 한다.

## v1.3 다문서 개발 실행 가능성 진단

v1.3은 Boeing 프롬프트·모델 튜닝을 종료하고 AMCOR, Best Buy, AMD의 7개 개발 문항으로
clean 일반 검색과 full-page oracle evidence를 분리한다. 동결 명세는
`research/specs/experiment_spec_v1_3.json`, 실행기는 `research/development_v1_3.py`, 소스
대조 판정기는 `research/evaluate_development_v1_3.py`다. PyMuPDF는 실제 두 번째 텍스트
추출과 단어 좌표 관측에만 사용하며 VLM이나 자동 표 파서로 부르지 않는다.

```bash
uv run --with-requirements research/requirements.txt \
  python -m research.development_v1_3 preflight \
  --data research/work/financebench-development-v1_3 \
  --spec research/specs/experiment_spec_v1_3.json \
  --config research/configs/dependency_aware_pilot_llama3_development_v1_3.json \
  --max-calls 18
```

완료된 개발 결과는
`research/results/dependency-aware-pilot-v1_3-development-run-005-summary.json`과
`research/reports/dependency-aware-pilot-v1_3-development-run-005.md`에 있다. 일반 검색과
oracle 모두 완전 정답 2/7이었고 통제 AMD quick-ratio 수정은 완전 복구 0건이었다. 이는
실행·실패 위치·특징 관측 경로를 확인한 결과이지 정책 우수성 결과가 아니다.

독립 평가 문서/규칙은 `research/specs/independent_evaluation_protocol_v1.json`에 성능
확인 전에 고정되어 있다. 소스 스냅샷까지만 준비됐으며 reference audit, injection
manifest, dependency-structure gate를 통과하기 전에는 정책 성능 실행을 시작하지 않는다.
