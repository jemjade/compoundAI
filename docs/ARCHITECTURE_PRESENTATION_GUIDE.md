# ParseLab 아키텍처·설계 발표 가이드

> 기준: 2026-07-30 현재 작업 트리와 Kubernetes 시연 설정  
> 목적: 설계 리뷰나 시연 자리에서 “무엇을, 왜 이렇게 설계했는지” 설명하기 위한 자료

## 1. 발표를 시작하는 한 문장

**ParseLab은 동일한 문서를 여러 문서 Parser로 실행하고, 서로 다른 결과를 공통
Canonical Format으로 정규화해 품질과 성능을 비교한 뒤, 필요하면 각 Parser 결과를
Fasoo로 비식별화하는 내부 실험 플랫폼입니다.**

단순히 파일을 변환하는 서비스가 아니라 다음 세 가지를 관리하는 플랫폼이라는 점이
핵심입니다.

1. 여러 외부 Parser의 실행 방식과 결과 형식 차이
2. Parser별 실행 상태, 설정 Snapshot, 산출물과 평가 이력
3. Parsing과 비식별화 사이의 장애 격리와 단계별 재실행

## 2. 30초 요약

- 사용자가 문서와 Parser들을 선택해 Experiment를 생성합니다.
- Backend는 Parser마다 독립적인 Run을 만들고 즉시 `202 Accepted`를 반환합니다.
- 프로세스 내부 TaskManager가 동시 실행 수를 제한하며 각 Run을 실행합니다.
- Adapter가 Synap, Docling, MinerU, PaddleOCR 등의 호출 방식 차이를 감쌉니다.
- Normalizer가 각 결과를 동일한 `CanonicalDocument`로 변환합니다.
- DB에는 상태·설정·지표·평가 같은 메타데이터를, 파일 저장소에는 원본과 큰
  JSON/Markdown/Text 산출물을 저장합니다.
- 비식별화를 요청하면 각 Parser의 `output.txt`를 Fasoo에 전달합니다.
- Parsing과 비식별화 상태를 분리하므로 Fasoo가 실패해도 성공한 Parser 결과는
  보존되고, 재사용 가능한 산출물이 있으면 비식별화만 다시 실행합니다.

## 3. 전체 논리 아키텍처

```text
┌─────────────────────────────────────────────────────────────────────┐
│ React SPA                                                           │
│ 문서 업로드 · Parser 관리 · Experiment 생성 · 상태 Polling · 결과 비교 │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ HTTP/JSON, multipart, Bearer JWT
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ FastAPI                                                             │
│                                                                     │
│ Router → Dependency/Pydantic → Service → Repository                 │
│                                  │                                  │
│                                  ├─ SQLAlchemy DB                    │
│                                  ├─ StorageService                   │
│                                  └─ TaskManager                      │
└──────────────────────────────────────────┬──────────────────────────┘
                                           │ asyncio Task + Semaphore
                                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Run Pipeline                                                        │
│                                                                     │
│ Parser Adapter → Normalizer → CanonicalDocument → Artifact 저장     │
│      │                                                    │         │
│      ├─ Synap HTTP / Docling / MinerU / PaddleOCR / Mock   │         │
│      │                                                    ▼         │
│      └──────────────────────────────────────────────→ Fasoo Adapter  │
└──────────────────────────────┬───────────────────────────┬──────────┘
                               │                           │
                               ▼                           ▼
                    DB 메타데이터·상태·지표          파일 저장소/NAS
```

### 이 그림에서 강조할 것

- FastAPI는 외부 요청과 업무 흐름의 진입점입니다.
- Parser 제품별 차이는 Adapter와 Normalizer 경계 안에 가둡니다.
- 오래 걸리는 실행은 HTTP 요청과 분리합니다.
- DB와 파일 저장소의 역할을 분리합니다.
- Parsing과 비식별화는 연결되어 있지만 서로 다른 성공·실패 경계를 갖습니다.

## 4. 핵심 도메인 모델

```text
User
├─ Document
│  └─ Experiment
│     └─ ExperimentRun ── ParserConnector
│        ├─ RunResult
│        ├─ DeidentificationResult
│        └─ ManualEvaluation
└─ ParserConnector
   └─ ParserPreset
```

| 객체 | 의미 |
|---|---|
| `Document` | 업로드한 원본과 SHA-256, 크기, 저장 경로 |
| `ParserConnector` | Parser 이름, Adapter Key, URL/명령, 지원 확장자, 기본 설정 |
| `ParserPreset` | Connector별로 재사용하는 설정 |
| `Experiment` | 문서 하나를 여러 Parser로 비교하는 상위 작업 |
| `ExperimentRun` | Experiment 안에서 Parser 하나를 실행하는 독립 단위 |
| `RunResult` | Canonical 결과 경로, 페이지·블록·표 수, 지연시간 등 |
| `DeidentificationResult` | Fasoo 결과 경로, 탐지·마스킹 수, 오류와 지표 |
| `ManualEvaluation` | 사용자의 품질 점수, 메모, 선호 Parser |

### Experiment와 Run을 나눈 이유

Experiment 하나에 Parser별 Run을 여러 개 두면 다음이 가능합니다.

- 같은 문서를 같은 조건에서 여러 Parser로 비교
- 한 Parser만 실패해도 나머지 결과 유지
- Run 단위 취소와 재실행
- Parser별 지연시간과 품질 지표 비교
- Parser 설정과 Version을 Run마다 Snapshot으로 보존

## 5. Backend 계층과 책임

| 계층 | 책임 | 대표 위치 |
|---|---|---|
| Router | HTTP 경로, 입력, 인증 의존성, 상태 코드, 응답 모델 | `app/api/v1` |
| Schema | Pydantic 기반 요청·응답 검증, Canonical 계약 | `app/schemas` |
| Service | 소유권, 업무 규칙, Transaction, Workflow | `app/services` |
| Repository | 반복 SQLAlchemy 조회와 영속성 접근 | `app/repositories` |
| ORM Model | Table, Column, FK, 상태 Enum | `app/db/models` |
| Adapter | 외부 Parser/Fasoo 호출 방식의 차이 흡수 | `app/adapters` |
| Normalizer | 제품별 결과를 Canonical 구조로 변환 | `app/normalizers` |
| Storage | 안전한 경로 처리와 Artifact 읽기·쓰기 | `storage_service.py` |
| Task/Pipeline | 비동기 실행, 상태 전이, 실패 격리 | `app/task_manager` |

이 분리의 목적은 “파일을 많이 나누는 것”이 아니라 **변경 이유가 다른 코드를
분리하는 것**입니다. 예를 들어 Synap 응답이 바뀌면 Adapter/Normalizer를 수정하고,
Experiment 생성 규칙이나 API 경로는 유지할 수 있습니다.

## 6. Experiment 요청 한 건의 실제 흐름

```text
1. React가 POST /api/v1/experiments 호출
2. FastAPI가 JSON과 Bearer JWT 검증
3. 요청 전용 AsyncSession 생성
4. Document 소유권 확인
5. Parser 중복·활성 상태·지원 확장자 확인
6. default_config → preset → override 순으로 설정 병합
7. JSON Schema로 최종 설정 검증
8. Experiment INSERT 후 flush()로 UUID 확보
9. Parser마다 ExperimentRun INSERT
10. 한 Transaction으로 commit()
11. Commit된 Run들을 TaskManager에 제출
12. API는 202 Accepted 반환
13. React는 실행 중인 Experiment를 2초 간격으로 Polling
14. Pipeline은 HTTP 요청과 다른 Session으로 각 Run 실행
```

### 왜 `flush()` 후 `commit()`하고 Task를 제출하는가

- `flush()`는 Experiment ID를 확보하지만 Transaction을 끝내지 않습니다.
- Run 생성이 실패하면 Experiment까지 함께 Rollback할 수 있습니다.
- `commit()` 전에 Task를 제출하면 Task가 아직 확정되지 않은 Run을 조회하는 경쟁
  상태가 생길 수 있습니다.
- 따라서 **Experiment와 모든 Run을 확정한 뒤** 백그라운드 실행을 시작합니다.

### 왜 `202 Accepted`인가

문서 Parsing과 Fasoo 처리는 수초에서 수분이 걸릴 수 있습니다. HTTP 연결을 계속
잡아두지 않고 “요청은 접수되었고 처리는 진행 중”이라는 의미로 `202`를 반환합니다.

## 7. Run Pipeline

```text
PENDING
  ↓
RUNNING 상태 Commit
  ↓
Parser Adapter 선택
  ↓
Parser 실행 + Timeout
  ↓
Normalizer로 CanonicalDocument 생성
  ↓
raw.json / canonical.json / output.md / output.txt 저장
  ↓
RunResult와 지표 저장
  ↓
parse_status=SUCCEEDED Commit
  ↓
비식별화 요청 시 Fasoo 단계 실행
```

TaskManager는 `asyncio.create_task()`로 작업을 등록하고 Semaphore로 동시 실행 수를
제한합니다. 요청용 DB Session을 Task에 넘기지 않고, Pipeline 수명에 맞는 새
Session을 생성합니다.

### Parser 상태

```text
PENDING → RUNNING → SUCCEEDED
                  └→ FAILED

PENDING/RUNNING → INTERRUPTED
FAILED/INTERRUPTED → 재실행 → PENDING
```

서버가 시작될 때 이전 프로세스에 남아 있던 `RUNNING` 상태는 `INTERRUPTED`로
전환합니다. 프로세스 메모리 안의 Task는 재시작 후 복구할 수 없기 때문입니다.

## 8. Adapter와 Canonical Format

### Adapter Registry

현재 Registry는 다음 실행 방식을 허용 목록으로 관리합니다.

- Built-in: Mock, PaddleOCR PP-StructureV3
- HTTP: Synap, Docling, MinerU, Generic HTTP
- Command: Docling, Generic Command

모든 Parser는 다음 공통 계약을 구현합니다.

```text
health_check()
parse(input_path, output_dir, config) → ParserExecutionResult
normalize(execution_result, document_id, run_id) → CanonicalDocument
```

### CanonicalDocument

```text
CanonicalDocument
├─ 문서·Run·Parser 정보
├─ full_text / markdown
└─ pages[]
   ├─ page_number / width / height / text
   └─ blocks[]
      ├─ type
      ├─ reading_order
      ├─ text
      ├─ bbox / confidence
      └─ table cells(row, column, span, text)
```

Parser 결과를 공통 구조로 바꾸면 UI와 비교 로직은 Synap/Docling/MinerU의 원본
Schema를 몰라도 됩니다. 새 Parser를 추가할 때도 Adapter와 Normalizer만 계약에
맞추면 됩니다.

다만 Canonical Format에 없는 제품 고유 정보가 손실될 수 있으므로 원본
`raw.json`도 함께 보존합니다.

## 9. 현재 Synap 연동 흐름

```text
output 원본 문서
  ↓ POST /da, multipart upload
fid 수신
  ↓ POST /filestatus/{fid} 반복
LOADING/RUNNING
  ↓
SUCCESS + total_pages
  ↓ POST /result/{fid}, 페이지별 JSON 수집
Box/Chat의 서로 다른 중첩 구조에서 Text·Block 추출
  ↓
CanonicalDocument 변환
  ↓ finally
POST /delete/{fid}로 Synap 임시 결과 정리
```

주요 설계 포인트:

- Connector의 `base_url`로 Box와 Chat을 각각 등록할 수 있습니다.
- API Key는 Connector DB가 아니라 Secret/환경변수에서 주입합니다.
- 전체 Synap Workflow에 Timeout을 적용합니다.
- 알 수 없는 상태나 비정상 응답은 안정적인 내부 오류 코드로 변환합니다.
- `finally`에서 Synap 임시 결과 삭제를 시도하되, 정리 실패 여부는 지표로 남깁니다.
- Box/Chat의 중첩 응답 차이는 Normalizer가 흡수합니다.

## 10. Parsing과 비식별화의 실패 격리

Parsing과 비식별화 상태는 별도 Column입니다.

```text
parse_status          deidentification_status
------------          -----------------------
SUCCEEDED             SUCCEEDED
SUCCEEDED             FAILED
SUCCEEDED             NOT_REQUESTED
FAILED                INTERRUPTED
```

두 단계 사이에 명시적인 Commit 경계를 둡니다.

```text
Parser 실행·정규화·Artifact 저장
  ↓
parse_status=SUCCEEDED
  ↓ COMMIT  ← Parser 결과 보존 경계
Fasoo 실행
  ↓
deidentification_status 기록
  ↓ COMMIT
```

Fasoo 실패 때문에 비싼 Parsing을 다시 수행하거나 성공한 결과를 실패로 덮지 않기
위한 설계입니다.

재실행 시에는 다음 규칙을 적용합니다.

- Parsing이 실패/중단됨: Parsing부터 재실행
- Parsing은 성공하고 Fasoo만 실패/중단됨: 기존 Artifact로 Fasoo만 재실행
- 기존 Artifact가 없거나 `output.txt`가 비어 있음: Fasoo만 반복해도 같은 실패가
  나므로 Parsing부터 다시 실행

## 11. 현재 Fasoo 연동 흐름

시연 환경은 각 Parser의 전처리 결과인 `output.txt`를 Fasoo 입력으로 사용합니다.

```text
Parser별 output.txt
  ↓
공유 NAS의 Run 전용 staging 디렉터리로 복사
  ↓
Backend Mount 경로를 Fasoo가 보는 경로로 변환
  ↓
Fasoo 로그인 → access_token Cache
  ↓
POST /piiapi/detect/system/path
  ↓ 401이면 1회 재로그인 후 재요청
  ↓
NAS의 result.json + masked.txt 생성 대기
  ↓
응답 정규화 및 runs/{run_id}/ 최종 Artifact로 복사
```

Backend와 Fasoo는 같은 NAS를 서로 다른 경로로 봅니다.

| 주체 | NAS Root |
|---|---|
| ParseLab Pod | `/app/data/dwp_comp` |
| Fasoo | `/dwp_comp` |

예를 들어 Pod의
`/app/data/dwp_comp/parselab/fasoo-smoke/{run_id}/input/input.txt`는 Fasoo에
`/dwp_comp/parselab/fasoo-smoke/{run_id}/input/input.txt`로 전달됩니다.

Run별 디렉터리를 사용하므로 여러 Parser 결과가 섞이지 않습니다. Fasoo HTTP 응답이
먼저 끝나도 NAS Artifact 생성이 늦을 수 있어 현재 시연 환경에서는 최대 600초까지
`result.json`과 마스킹 파일을 기다립니다.

## 12. DB와 파일 저장소를 분리한 이유

| DB에 저장 | 파일 저장소/NAS에 저장 |
|---|---|
| 사용자와 소유권 | 업로드 원본 |
| Connector와 Preset | Parser 원본 JSON |
| Run 상태와 오류 | Canonical JSON |
| Config/Parser Snapshot | Markdown과 Text |
| 지연시간과 개수 지표 | Fasoo 결과와 마스킹 파일 |
| 수동 평가 | 오류 Artifact |

장점:

- 상태와 실험 목록은 DB에서 빠르게 검색할 수 있습니다.
- 큰 JSON과 원본 문서가 DB Connection과 Backup을 무겁게 하지 않습니다.
- 향후 StorageService 구현만 바꿔 S3/Object Storage로 이동하기 쉽습니다.

트레이드오프:

- DB Commit과 파일 저장을 하나의 ACID Transaction으로 묶을 수 없습니다.
- 파일만 남거나 DB 경로만 남는 불일치가 발생할 수 있습니다.
- 운영 환경에서는 임시 파일 후 Atomic Rename, Checksum, Artifact 상태,
  Garbage Collector가 필요합니다.

## 13. 현재 Kubernetes 시연 배포

논리 설계는 SQLAlchemy를 통해 DB에 독립적이지만, 환경별 DB가 다릅니다.

- 로컬 Docker Compose: PostgreSQL + Backend + React/Nginx + 선택적 Docling
- 현재 Kubernetes 시연: Backend 1 Pod + SQLite `emptyDir` + NAS Snapshot

```text
사용자 또는 별도 UI
  ↓ HTTPS /parselab/*
Nginx Ingress
  ↓ rewrite
ClusterIP Service
  ↓
ParseLab Backend Pod (replicas=1, Recreate)
  ├─ FastAPI/Uvicorn
  ├─ SQLite: /app/sqlite/parselab.db       ← emptyDir
  └─ /app/data/dwp_comp                    ← dwp-nas-volume PVC
      ├─ parselab/storage                  ← 문서·Run Artifact
      ├─ parselab/fasoo-smoke              ← Fasoo 공유 staging
      └─ parselab/demo-state/parselab.db   ← SQLite Snapshot
```

### Pod 시작과 종료

```text
Pod 시작
  ↓ Init Container: NAS Snapshot → emptyDir SQLite 복원
  ↓ Init Container: Alembic Migration
  ↓ Uvicorn 시작

정상 종료
  ↓ preStop: SQLite Backup API로 일관된 Snapshot 생성
  ↓ quick_check
  ↓ 임시 파일을 NAS Snapshot으로 Atomic Replace
```

### 왜 시연에서 SQLite인가

- 공용 PostgreSQL을 변경하지 않고 독립적으로 시연하기 위해서입니다.
- SQLite를 NFS 위에서 직접 실행하지 않아 파일 잠금 문제를 피합니다.
- `emptyDir`에서 실행하고 정상 종료 때만 NAS에 일관된 Snapshot을 보관합니다.

### 반드시 함께 말할 한계

- 이 SQLite 구조는 시연용이며 운영용 HA 구성이 아닙니다.
- `preStop`이 실행되지 않는 노드 장애나 강제 종료에서는 마지막 정상 Snapshot 이후
  데이터가 유실될 수 있습니다.
- 현재 `replicas=1`, `Recreate`, `MAX_CONCURRENT_RUNS=1`입니다.
- 현재 `k8s/` Manifest는 Backend만 배포하며 React Frontend는 포함하지 않습니다.
- 운영 전환 시 PostgreSQL, Durable Queue/Worker, Object Storage를 검토해야 합니다.

## 14. Frontend 데이터 흐름

- React Router가 인증 화면과 문서·Task·Parser·Experiment·비교 화면을 분리합니다.
- TanStack Query가 서버 상태 Cache와 재조회 주기를 관리합니다.
- 진행 중인 Experiment 상세는 2초마다 Polling합니다.
- Terminal 상태가 되면 Polling을 중단합니다.
- 공통 API Client가 Bearer Token, JSON Header, 공통 오류 형식을 처리합니다.

Polling은 MVP에서 구현과 장애 복구가 단순하지만, 사용자와 작업 수가 많아지면
SSE/WebSocket 또는 알림 기반 갱신을 검토할 수 있습니다.

## 15. 설계의 강점

1. **확장성**  
   Adapter/Normalizer 계약으로 새 Parser와 외부 제품 연동 범위를 제한했습니다.

2. **비교 가능성**  
   Canonical Format과 동일 문서·동일 Experiment 구조로 공정한 비교 기준을 만듭니다.

3. **재현성**  
   `parser_snapshot`과 `config_snapshot`으로 실행 당시 이름, Version, 설정을
   보존합니다.

4. **장애 격리**  
   Parser별 Run, Parsing/Fasoo별 상태와 Commit 경계로 부분 실패를 표현합니다.

5. **보안 경계**  
   사용자 소유권 검사, JWT, 파일 크기·확장자·MIME 검증, 저장 경로 이탈 차단,
   Command 실행파일 허용 목록과 `shell=True` 미사용을 적용합니다.

6. **검증 가능성**  
   Adapter, Normalizer, 상태 계산, 저장 경로, 동시성, Fasoo 인증/경로, SQLite
   Snapshot을 단위 테스트로 검증합니다.

## 16. 현재 한계와 운영 확장 방향

| 현재 MVP | 운영 확장 |
|---|---|
| `asyncio.create_task()` 기반 프로세스 내부 작업 | Durable Queue와 독립 Worker |
| 단일 프로세스 Semaphore | DB Lease 또는 분산 동시성 제어 |
| 재시작 시 RUNNING → INTERRUPTED | Heartbeat, 자동 재할당, Idempotency |
| 로컬/NAS 파일 저장 | Object Storage, Checksum, Lifecycle |
| 시연용 SQLite Snapshot | PostgreSQL HA와 Migration Pipeline |
| Polling | SSE/WebSocket 또는 Event 알림 |
| 단순 `/health` | Liveness/Readiness 및 외부 의존성 상태 분리 |
| 일반 Log | Request ID, 구조화 Log, Metric, Trace |
| Connector URL 허용 | SSRF 방어와 네트워크 Allowlist |
| 확장자/MIME 확인 | Magic Byte, 악성 문서 검사 |
| Browser Local Storage JWT | HttpOnly Cookie/Refresh Token 정책 검토 |

특히 현재 TaskManager는 Queue 제품이 아니라 **한 프로세스 안의 Task Registry**입니다.
여러 Pod로 바로 늘리면 전역 동시성, 중복 실행, 작업 소유권을 보장하지 못합니다.

## 17. 5분 발표 순서

### 0:00~0:30 — 문제와 목표

“문서 Parser마다 호출 방식과 결과 형식이 달라 품질을 같은 기준으로 비교하기
어렵습니다. ParseLab은 같은 문서를 여러 Parser로 실행하고 공통 구조로 변환해
결과와 성능을 비교하며, 각 결과의 비식별화까지 한 흐름으로 검증합니다.”

### 0:30~1:30 — 전체 구조

“React는 실험 생성과 상태 조회를 담당하고, FastAPI는 인증·검증·Workflow를
조정합니다. 오래 걸리는 실행은 TaskManager로 분리합니다. 외부 제품별 차이는
Adapter와 Normalizer가 흡수하고, DB에는 메타데이터, NAS에는 큰 Artifact를
저장합니다.”

### 1:30~2:30 — Experiment와 Pipeline

“Experiment는 비교 작업이고 Run은 Parser 하나의 실행 단위입니다. 생성 시 모든
Run을 한 Transaction으로 확정한 뒤 `202`를 반환하고 실행합니다. 각 Run은
PENDING, RUNNING, SUCCEEDED/FAILED 상태를 가지며 UI가 Polling합니다.”

### 2:30~3:30 — Canonical과 Synap

“Synap은 문서를 제출하고 fid를 받은 뒤 상태를 Polling하고 페이지별 결과를
가져옵니다. Box와 Chat의 결과 구조 차이는 Normalizer가 공통 Page/Block/Table
구조로 바꿉니다. 비교 화면은 제품별 원본 Schema에 의존하지 않습니다.”

### 3:30~4:20 — Fasoo와 실패 격리

“Parser가 성공하면 먼저 결과를 Commit합니다. 그 다음 각 Run의 `output.txt`를 공유
NAS에 배치하고 Fasoo 경로 API를 호출합니다. Fasoo가 실패해도 Parser 성공은
유지되고, 산출물이 있으면 Fasoo만 재실행합니다.”

### 4:20~5:00 — 시연 배포와 한계

“내일 시연은 공용 PostgreSQL을 건드리지 않기 위해 SQLite를 `emptyDir`에서
실행하고, 정상 종료 시 NAS Snapshot으로 보존합니다. 안전한 시연용 선택이지 운영
HA 설계는 아닙니다. 운영 단계에서는 PostgreSQL, Durable Queue/Worker, Object
Storage로 확장할 계획입니다.”

## 18. 예상 질문과 답변

### Q. 왜 Parser를 직접 Service에서 호출하지 않고 Adapter를 두었나요?

Parser마다 HTTP, Command, 내장 실행 방식과 응답이 다릅니다. Adapter가 호출 차이를,
Normalizer가 결과 차이를 흡수하면 Service와 UI는 공통 계약만 알면 됩니다.

### Q. 왜 Experiment와 Run을 분리했나요?

Experiment는 비교의 단위이고 Run은 Parser 하나의 실패·재시도·지표 단위입니다.
분리해야 부분 성공과 Parser별 비교를 정확히 표현할 수 있습니다.

### Q. 왜 요청을 기다리지 않고 `202`를 반환하나요?

Parser와 Fasoo가 수분 걸릴 수 있기 때문입니다. HTTP 요청 수명과 실행 수명을
분리하고 상태 API로 진행 상황을 조회합니다.

### Q. Canonical Format으로 바꾸면 정보가 손실되지 않나요?

공통 비교 항목에 없는 제품 고유 정보는 손실될 수 있습니다. 그래서 비교용
Canonical JSON과 함께 원본 `raw.json`도 보존합니다.

### Q. Fasoo가 실패하면 전체 실험은 실패인가요?

아닙니다. Parser 성공과 비식별화 실패를 별도로 기록합니다. 전체 Experiment는
상황에 따라 `PARTIALLY_COMPLETED`가 되고 Parser 결과는 계속 비교할 수 있습니다.

### Q. 왜 Fasoo에 원본 문서가 아니라 `output.txt`를 보내나요?

현재 시연 목표는 각 Parser가 전처리한 텍스트 기준으로 비식별화 품질을 비교하는
것입니다. Run별 `output.txt`를 사용해야 Parser별 결과와 Fasoo 결과의 연결이
명확합니다.

### Q. 왜 공유 NAS가 필요한가요?

현재 Fasoo 연동은 파일 업로드 API가 아니라 서버가 접근 가능한 `inputPath`,
`outputPath`, `maskedPath`를 전달하는 경로 기반 API입니다. 따라서 양쪽이 같은
파일을 볼 수 있는 공유 NAS가 필요합니다.

### Q. SQLite를 NAS에 직접 두지 않은 이유는 무엇인가요?

NFS 위 SQLite는 파일 잠금과 일관성 문제가 생길 수 있습니다. 실행 DB는 Pod의
`emptyDir`에 두고, 종료 시 SQLite Backup API로 만든 일관된 Snapshot만 NAS에
저장합니다.

### Q. Pod가 갑자기 죽으면 어떻게 되나요?

프로세스 내부 작업은 사라지고, 다음 시작 때 DB의 RUNNING 상태를 INTERRUPTED로
바꿉니다. 시연용 SQLite는 `preStop`이 생략된 장애에서는 마지막 정상 Snapshot
이후 데이터가 유실될 수 있습니다. 운영에서는 외부 DB와 Durable Queue가
필요합니다.

### Q. 지금 여러 Pod로 확장할 수 있나요?

현재 상태로는 안전하지 않습니다. Task Registry와 Semaphore가 프로세스 내부이고
시연 DB가 SQLite이기 때문입니다. PostgreSQL, 작업 Lease/Queue, Idempotency를
도입한 뒤 수평 확장해야 합니다.

### Q. 보안상 가장 먼저 보강할 부분은 무엇인가요?

Generic HTTP Connector의 SSRF 방어, 파일 Magic Byte/악성 문서 검사, Rate Limit,
Refresh Token/HttpOnly Cookie, 감사 Log가 우선순위입니다.

## 19. 시연 체크리스트

### 시연 전

- `/parselab/health`와 `/parselab/docs` 확인
- Synap Box/Chat Connector의 Health Check
- Fasoo `/piiapi/configuration` Health Check
- 개인정보가 없는 작은 문서로 End-to-End 1회 실행
- `output.txt`가 비어 있지 않은지 확인
- Fasoo NAS staging과 최종 masked Artifact 확인
- 실패 Run의 재실행 버튼과 상태 전이 확인

### 시연 중 보여줄 순서

1. 문서 업로드
2. Parser 두 개 이상 선택
3. 비식별화 옵션을 켜고 Experiment 생성
4. `202` 응답과 Run별 상태 변화
5. Parser별 Text/Canonical/Table 결과 비교
6. Parsing 성공과 Fasoo 상태가 분리되어 보이는 화면
7. 가능하면 Diff, 수동 평가, CSV Export

### 시연 중 피해야 할 표현

- “Kubernetes에서도 PostgreSQL을 사용합니다.”  
  → 현재 시연 Manifest는 SQLite입니다.
- “작업 Queue가 있어서 재시작해도 자동 복구됩니다.”  
  → 현재는 프로세스 내부 TaskManager이며 중단 상태 기록과 수동 재실행 방식입니다.
- “SQLite Snapshot이 모든 장애에서 데이터를 보장합니다.”  
  → 정상 종료와 Rollout 보존용이며 비정상 노드 장애에는 한계가 있습니다.
- “Kubernetes Manifest가 Frontend까지 배포합니다.”  
  → 현재 `k8s/`는 Backend만 배포합니다.
- “Fasoo 실패 시 Parser도 실패합니다.”  
  → 두 상태는 의도적으로 분리되어 있습니다.

## 20. 코드 근거 빠른 지도

- 앱 시작과 재시작 상태 복구: `backend/app/main.py`
- API Router와 인증 의존성: `backend/app/api`
- Experiment Transaction과 재실행: `backend/app/services/experiment_service.py`
- Task 동시성 제한: `backend/app/task_manager/manager.py`
- Parsing/Fasoo 상태 경계: `backend/app/task_manager/pipeline.py`
- Parser Adapter Registry: `backend/app/adapters/parsers/registry.py`
- Synap 제출·Polling·정리: `backend/app/adapters/parsers/synap_http.py`
- Synap Canonical 변환: `backend/app/normalizers/synap_normalizer.py`
- Fasoo NAS 경로·인증·Artifact 처리: `backend/app/adapters/deidentifiers/fasoo_http.py`
- Canonical 계약: `backend/app/schemas/canonical_document.py`
- 안전한 파일 저장: `backend/app/services/storage_service.py`
- React Routing/API Client: `frontend/src/App.tsx`, `frontend/src/lib/api.ts`
- 시연 배포: `k8s/deployment.yaml`, `k8s/configmap.yaml`
- SQLite Snapshot: `backend/app/sqlite_snapshot.py`

## 마지막으로 기억할 다섯 문장

1. ParseLab은 여러 Parser를 같은 기준으로 비교하는 실험 플랫폼입니다.
2. Adapter가 호출 차이를, Canonical Format이 결과 차이를 흡수합니다.
3. Experiment 아래 Parser별 Run을 두어 부분 실패와 재실행을 격리합니다.
4. Parsing 성공을 먼저 Commit하므로 Fasoo 실패가 Parser 결과를 없애지 않습니다.
5. 현재 SQLite+NAS Snapshot은 시연용이며, 운영 확장은 PostgreSQL+Durable
   Queue+Object Storage가 핵심입니다.
