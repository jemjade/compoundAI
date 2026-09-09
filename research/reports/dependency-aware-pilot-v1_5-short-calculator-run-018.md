# Dependency-aware pilot v1.5 짧은 planner 개발 진단

상태: **IMPLEMENTED** (짧은 source 계약·검증·단계형 실행기), **VERIFIED** (AMD clean
실제 로컬 모델 호출과 fail-closed 기록), **BLOCKED** (산술→answerer 완료·수정 효과),
**PROPOSED** (후속 planner 설계와 정책 비교).

## 동결 및 실행

- 동결 코드 커밋: `73aeeec12b4172aee7609b116a336cc18418ce45`
- 명세: `research/specs/experiment_spec_v1_5.json`, 실행 시 SHA-256
  `ea426dea77044f5f1836c020b57ec261a58390a401a239b6bfdfd42ab9e5e698`
- 모델: Ollama `0.30.6`, `llama3:latest`, digest
  `365c0bd3c000a25d28ddbf732fe1c6add414de7275464c4e4d1c3b5fcb5d8ad1`, 8.0B,
  Q4_0, temperature 0, context 8192, retry 0
- parser: v1.4 Docling canonical 결과를 재사용했다. v1.5 parser 실행·설치·다운로드는
  0회이고 Synap은 필요하지 않다.
- 동결 순서: AMD clean 1회 → pipeline 완료 시 AMCOR clean 1회 → AMD clean 원문
  의미 판정까지 통과할 때만 5개 repair state. 정상 최대 14 calls, hard limit 16 calls.
- 실제 호출: planner 1회. AMD가 reference validation에서 실패하여 동결 규칙대로
  AMCOR와 repair 5조건을 실행하지 않았다. 자동 retry나 prompt 변경은 없었다.

## v1.4 원인 분리

v1.4 calculator 19요청 중 17건은 `prompt_eval_count=8191`, `eval_count=1`로 8192
context가 입력에서 소진된 경우였다. 따라서 출력 토큰 상한 도달이 아니라 입력 문맥
초과/잘림이다. 나머지 2건은 planner가 존재하는 step이 아닌 문자열 `0.16`을 output
reference로 쓴 실패였다. 실패 응답에서 반복되는 불필요한 장문 출력은 관측되지 않았다.

기존 판정은 보존한다. v1.4 calculator의 전체 요청 성공률은 각 조건 0/7이다. 완료된
calculator answer가 0건이었으므로 완료 응답 정확도는 0%가 아니라 분모 0으로 측정
불가다.

## v1.5 계약과 preflight

현재 페이지의 모든 숫자 span을 extraction order로 `s0..sN`에 대응했다. planner에는
short ID, 현재 값, parser 행, parser header에서 일반적으로 도출한 기간·단위, 짧은
cell/span 문맥만 보냈다. 원래 source ID, block/table/cell ID, bbox와 coordinate metadata는
raw input의 full registry에 남겼다. 정답, 정답 계산식, 문서/질문 ID, repair label, clean
값은 모델 입력에 없다.

후보 축소는 없었다. AMD 77개, AMCOR 60개 숫자 후보를 모두 유지했다. tokenizer-independent
보수 추정치는 AMD 5,028, AMCOR 3,626 prompt tokens였고, planner 400 tokens와 safety
512 tokens를 더해도 context 8192 안이다. 최대 배열 경계의 계획은 756 JSON chars,
약 252 tokens로 추정되어 400-token 출력 예산 안이었다. 이 값은 추정치이며 실제 AMD
Ollama 입력은 3,803 tokens였다.

## 실제 결과

| 요청 | planner | 형식 | 참조 | 산술 | answerer | pipeline 완료 | 원문 전체 정답 |
|---|---:|---:|---:|---:|---:|---:|---:|
| AMD quick ratio clean | 1/1 | 1/1 | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 |
| AMCOR gross margin clean | gate로 미실행 | - | - | - | - | - | - |
| AMD repair 5조건 | gate로 미실행 | - | - | - | - | - | - |

전체 요청 기준 pipeline 완료는 0/1, 원문 전체 정답은 0/1이다. 완료된 응답에 한정한
정확도는 분모가 0이므로 측정 불가다. 실제 planner token은 input 3,803/output 147이고
출력은 363 chars였다. 입력 잘림, 출력 상한, 반복 장문 문제는 이번 호출에서 발생하지
않았다.

Planner는 metric ID로 `quick_ratio_liquid_components_v1`을 골랐지만 inputs에는 `s4`
(2022 cash 4,835)와 `s5`(2021 cash 2,535)만 선언했다. steps는 선언하지 않은 `s10/s11`
(2022/2021 inventory), `s14/s15`(2022/2021 prepaid), `s6`(2022 short-term investments)을
사용했다. 따라서 존재하는 current source이더라도 planner가 선택·role 지정하지 않은
reference로 보아 fail-closed했다.

이 암묵 참조를 허용한다고 가정해도 계획은
`((3771-1955)+(1265-312))/1020 = 2.714705882...`이다. 원문 quick ratio 경로인
`(4835+1020+4126)/6369 = 1.567436018...`와 다르다. 기간을 섞고 accounts receivable과
current liabilities를 사용하지 않으므로 의미적으로도 틀리다.

오류 차원은 metric ID 선택 PASS, 값 선택 FAIL, 기간 선택 FAIL, 단위 연결 PASS,
산술 NOT EXECUTED, 결론/answer NOT EXECUTED, evidence FAIL이다. 구문상 유효한 계획을
정답 계획으로 집계하지 않았다. source→operation→result→answer dependency는 실제
산술이 시작되지 않아 관측되지 않았고, 이를 repair 효과 없음으로 해석하지 않는다.

## 보존 위치

- 모델 전 로컬 연결 권한 실패(run-017, 호출 0회, manifest와 checksum 보존):
  `/Users/suhyunpark/suhyun_dev/compoundAI/research/work/dependency-aware-pilot-v1_5-short-calculator-clean-run-017`
- 실제 AMD clean run-018(raw input, complete source map, prompt/schema, raw planner output,
  token use, failure record, model inventory, manifest, checksums):
  `/Users/suhyunpark/suhyun_dev/compoundAI/research/work/dependency-aware-pilot-v1_5-short-calculator-clean-run-018`
- compact 결과: `research/results/dependency-aware-pilot-v1_5-short-calculator-run-018-summary-v2.json`.
  작성자 표기 정정 전 초기 summary도 삭제하지 않고 보존했으며 v2가 현재 판정이다.
- 원문 audit/gate: `research/judgments/dependency-aware-pilot-v1_5-amd-clean-gate.json`

run-018 manifest SHA-256은
`31a40825996fe23674fbb10473c9004163417d13ec84317b984d3735c26547a0`, checksum manifest
SHA-256은 `2c22a667ea54103772652f491b6f832ac91d4e6908384003bb67a11c1a70758d`다. 프로젝트의
지속 저장 경로가 primary이고 독립 물리 백업은 확인되지 않았다.

## 판정과 다음 차단 원인

짧은 계약은 v1.4의 입력 문맥 초과를 해결했고 planner 출력 자체를 400-token 이내로
완료시켰다(**VERIFIED**). 그러나 `inputs`와 `steps.args` 사이 계약을 모델이 지키지 않았고,
더 근본적으로 선택한 값과 기간·분모가 지표 의미에 맞지 않았다(**BLOCKED**). 따라서
실제 값 선택→산술→답변 완료, AMCOR 교차 문서 확인, AMD 수정 조건 변화는 모두 아직
검증되지 않았다.

다음 한 가지 작업은 prompt 반복 튜닝이 아니라, **planner가 role/source 선택과 연산
operand를 서로 모순되게 표현할 수 없는 단일 typed operand 계약을 설계하고, 그 계약이
quick-ratio 의미 선택까지 보장하지는 않는다는 점을 별도 semantic gate로 유지하는 것**이다.
이 개발 실패만으로 후보 특징·의존관계가 정책 비교에 충분하다고 볼 수 없다.
