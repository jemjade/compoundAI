# Dependency-aware pilot v1.4 parser/calculator 개발 진단

상태: **VERIFIED** (실제 parser 및 기존 QA 실행), **BLOCKED** (실제 calculator answer와 수정 효과), **PROPOSED** (정책 특징 사용).

## 동결 범위와 실행 식별

- 명세: `research/specs/experiment_spec_v1_4.json`, SHA-256 `7c114b8e0f5596772b53260a483da383b1a5e161daf9e6ffb0e42a54ff40d80a`
- 실제 실행 commit: `03f66affe0b24790499140de2792706f952e4bf7`
- QA: Ollama `0.30.6`, `llama3:latest`, digest `365c0bd3c000a25d28ddbf732fe1c6add414de7275464c4e4d1c3b5fcb5d8ad1`, 8.0B, Q4_0, temperature 0, context 8192, 재시도 0
- 호출: 중단·보존 run-014 27회 + 복구 run-016 33회 = 누적 60회. 새 유료 API는 사용하지 않았다.
- 고정 페이지: AMCOR 50/52, Best Buy 40/42, AMD 12/48/56. 검색을 제외한 oracle-page 개발 진단이다.

Docling 2.126.0/Core 2.95.0/IBM Models 4.0.2/Parse 7.18.0은 CPU, no-OCR, accurate-table로 실행했다. PP-StructureV3는 paddleocr 3.7.0/paddlepaddle 3.3.1/paddlex 3.7.2와 CPU를 사용했다. 설치·장치·옵션은 [Docling 설치](https://docling-project.github.io/docling/getting_started/installation/), [Docling CLI](https://docling-project.github.io/docling/reference/cli/), [PP-StructureV3](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/pipeline_usage/PP-StructureV3.html), [PaddleOCR 설치](https://paddlepaddle.github.io/PaddleOCR/main/version3.x/installation.html) 공식 문서와 대조했다.

## 실제 parser 연결

| Parser | 성공 페이지 | 표 페이지 | 셀 합계 | 상태 |
|---|---:|---:|---:|---|
| Docling | 7/7 | 6 | 565 | VERIFIED |
| PP-StructureV3 | 7/7 | 6 | 963 | VERIFIED |

두 parser 모두 raw JSON → CanonicalDocument를 실제 연결했다. Docling은 표 셀 ID·행/열·span·bbox와 좌표 원점을 보존했다. Paddle은 JSON 내부의 문자열화된 parsing block을 출처 표시와 함께 복원하고, HTML 표 셀을 보존했다. `cell_box_list`와 HTML cell의 순차 대응은 검증되지 않아 `coordinate_alignment_verified=false`다. 중간 pixel raster는 구조 JSON에서 명시적으로 생략하며 생략 이유와 타입을 남겼다.

PP-StructureV3의 최초 실제 추론은 선택적 Markdown 직렬화의 `python-docx` 누락 및 `page_continuation_flags` KeyError 때문에 실패했다(run-008/009). 이를 raw JSON 성공과 분리했다. 이어 raw JSON의 1.5GB raster 팽창과 parsing-block 문자열화를 발견해 run-010/011을 중단·보존하고, 최종 run-012에서 7/7을 완료했다. mock 결과가 아니다.

원문 대조에서 Docling은 7문항의 핵심 값/문장을 모두 읽을 수 있었다. PP-StructureV3는 실제 오류를 보였다. 예를 들어 AMCOR p52는 `Cash and cashequivalents`, `otal current liabilities`로 라벨이 훼손됐고, AMD p56의 Cash 행은 2022 `4,835` 대신 잘못 정렬된 `1,073`, Accounts receivable 행은 `4,126` 대신 `3,771`과 Inventories 라벨을 함께 배치했다. Best Buy p42의 `total` 첫 글자도 누락됐다. 이는 소스 PDF 대조로 확인한 실제 parser 오류다. 반면 parser 간 내용 불일치 자체는 gold 오류로 판정하지 않았다.

좌표 정렬 진단은 7페이지 중 표가 없는 AMD p12를 제외해 수행했다. 페이지별 cell count 차이와 정렬 분류는 raw 진단에 보존했다. PP 좌표 연결이 미검증이고 구조가 과분할되어 exact agreement가 매우 적고 alignment failure가 많았다. 이 값을 오류 확률로 사용하지 않는다. 인위적 AMD A/B는 parser 오류가 아니라 post-parse controlled mutation으로 별도 기록했다.

## 7문항 × 네 조건 결과

`C`는 pipeline 완료, `F`는 fail-closed, `✓/✗`는 동결된 전체 과제 판정이다.

| 질문 | pypdf+LLM | pypdf+Calc | Docling+LLM | Docling+Calc |
|---|---:|---:|---:|---:|
| AMCOR quick ratio (00799) | C/✗ | F/✗ | C/✗ | F/✗ |
| AMCOR gross margin (00684) | C/✗ | F/✗ | C/✗ | F/✗ |
| Best Buy gross consistency (00685, primary 제외) | C/✗ | F/✗ | C/✗ | F/✗ |
| Best Buy cash flow (01275) | C/✗ | F/✗ | C/✗ | F/✗ |
| AMD quick ratio (00222) | C/✗ | F/✗ | C/✗ | F/✗ |
| AMD segment growth (00563) | C/✓ | F/✗ | C/✓ | F/✗ |
| AMD concentration (00757) | C/✓ | F/✗ | C/✓ | F/✗ |
| **전체** | **2/7** | **0/7 (0 완료)** | **2/7** | **0/7 (0 완료)** |
| **Primary** | **2/6** | **0/6 (0 완료)** | **2/6** | **0/6 (0 완료)** |

기존 LLM QA의 결론 판정은 pypdf에서 correct 3, incorrect 4이고 Docling에서 correct 2, incorrect 4, missing 1이다. 완전 정답은 두 조건 모두 2개다. Docling은 표 구조를 보존했지만 quick ratio에서 “필요 정보가 없다”고 답했고, 다른 계산 문항의 지표·산술·결론 모순도 남았다. 따라서 parser 변경만으로 기본 QA 실패가 해결됐다고 할 수 없다.

계산 도구는 현재 evidence numeric source → LLM metric/value plan → Decimal operation → answer dependency edge를 구현하고 테스트했다. 그러나 실제 19개 calculator 행은 planner `length` 17건, invalid output reference 2건으로 모두 executor 또는 answerer 완료 전에 실패했다. 원시 provider 응답은 run-016 call ledger에 보존했다. 산술 성공 사례가 없으므로 metric/value/year/unit/denominator 선택의 실제 정확도나 answer가 program result를 사용했는지는 **BLOCKED**다.

## AMD 수정 진단

Docling p56에서 A=`#/tables/0/data/table_cells/6`(Cash, row 4/column 1, `$ 4,835`)와 B=`#/tables/0/data/table_cells/12`(Accounts receivable, row 6/column 1, `4,126`)를 2022 header와 함께 하나씩 대응했다. damaged baseline/no-op/A-only/B-only/A+B 입력은 각각 별도 해시로 저장됐고, no-op도 캐시 없이 새 planner 호출을 했다. 총 current assets, inventory, prepaid 등 대체 계산 경로는 제거하지 않았다.

다섯 상태 모두 planner length 실패여서 실제 피연산자·연산·답변이 생성되지 않았다. 입력 상태와 downstream 재호출은 **VERIFIED**지만, 답변 변화·복구·새 오류·상호작용은 **BLOCKED**이며 0 효과로 집계하지 않는다.

## 연구 판정

1. 오픈소스 parser 실제 연구 연결: **VERIFIED**. Docling과 PP-StructureV3 모두 actual raw와 Canonical을 7페이지에서 생성했다. Docling→기존 QA도 실제 연결했다. PP는 비교 parser/특징 진단까지만 연결됐다.
2. 기본 QA 실패: **BLOCKED**. 표 구조 제공으로 완전 정답 수가 늘지 않았다. Data Center와 concentration 두 문항만 두 근거 표현 모두 통과했다. 산술, 지표 선택, 결론-계산 일관성 문제가 남았다.
3. 수정에 따른 답변 변화 해석: **BLOCKED**. 셀 수정과 독립 downstream 호출은 확인했지만 calculator planner가 답변 전 실패했다.
4. 후보 특징·의존관계의 정책 충분성: **PROPOSED**. 실제 parser disagreement, 라벨/셀 구조 차이, 좌표 정렬 실패, calculator dependency edge 스키마는 확보했다. 그러나 parser 정렬 신뢰도가 낮고 실제 calculator edge가 한 건도 완성되지 않아 정책 비교 입력으로 충분하지 않다.

가장 큰 다음 작업은 프롬프트 반복 튜닝이 아니라, 개발 자료에서 planner 출력 계약을 짧고 유한한 후보-ID 선택으로 재설계하고 최소 한 개의 clean/손상/복구 상태에서 값 선택→산술→답변 chain을 실제 완료시키는 것이다. 그 뒤에만 독립 평가와 정책 비교 gate를 다시 판단한다.

## 보존 위치

- Docling raw/canonical/manifest/checksums: `/Users/suhyunpark/suhyun_dev/compoundAI/research/work/open-source-parser-v1_4-docling-run-007`
- PP-StructureV3 raw/canonical/manifest/checksums: `/Users/suhyunpark/suhyun_dev/compoundAI/research/work/open-source-parser-v1_4-pp-structure-v3-run-012`
- parser 정렬 raw: `/Users/suhyunpark/suhyun_dev/compoundAI/research/work/parser-alignment-v1_4-run-015.json`
- QA raw input/calls/records/manifest/checksums: `/Users/suhyunpark/suhyun_dev/compoundAI/research/work/dependency-aware-pilot-v1_4-parser-calculator-run-016`
- checksum inventory hashes: Docling `d5f8a9cc4e287cb76f98694746cd740a4def3dd23ad9b3cc3ac98a33f4556414`, PP-StructureV3 `cf16753f09ddcb1ed2163c370471eeffd36473aad26f291d76300fd3d95977ff`, QA `a5337093f47e7fe23fbd1744f7594e977eff605cb33eee8d9609b6ed76add6ec`; alignment raw `e2095a897a313bad2d33bf540b95910c742faf3adbcd6fd7ed740e275db4ebc8`
- 중단 실행도 run-008/009/010/011/013/014에 삭제하지 않고 남겼다.
- 독립 물리 백업은 확인하지 못했다. 지속 프로젝트 경로의 원시 파일과 Git 추적 요약은 별개이며, 요약/해시로 원시 파일을 대체하지 않았다.
