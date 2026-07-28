# ParseLab 프로젝트 완벽 이해 가이드

이 문서는 ParseLab을 단순히 실행하는 수준을 넘어, **요청 한 건이 Frontend에서
FastAPI, PostgreSQL, Parser, 비식별화, 파일 저장소를 거쳐 다시 화면에 표시되는
과정**을 코드로 설명할 수 있게 만드는 학습 가이드입니다.

메인 [README](../README.md)는 전체 설계와 운영 원칙을 설명합니다. 이 문서는 실제
코드를 어떤 순서로 읽고, 어디에 Breakpoint를 걸고, 무엇을 직접 바꿔보면 되는지
안내하는 실습서입니다.

## 1. 이 프로젝트를 이해했다는 기준

다음 질문에 코드를 가리키며 답할 수 있으면 프로젝트를 제대로 이해한 것입니다.

1. FastAPI 애플리케이션은 언제 생성되고 시작·종료 시 어떤 작업을 하는가?
2. `user: CurrentUser` 한 줄로 JWT 검증과 사용자 조회가 어떻게 실행되는가?
3. 요청용 `AsyncSession`과 백그라운드 Run용 Session은 왜 분리되어 있는가?
4. 문서 원본은 왜 PostgreSQL이 아니라 파일 저장소에 저장되는가?
5. Experiment와 Run의 차이는 무엇이며 왜 각각 별도 Table인가?
6. Experiment API가 왜 `201`이 아닌 `202`를 반환하는가?
7. Parser 3개를 선택했을 때 어떤 Row와 Task가 몇 개 생성되는가?
8. Parser Connector, Adapter, Preset, Config Snapshot은 각각 무엇인가?
9. 서로 다른 Parser 결과를 어떻게 같은 화면에서 비교할 수 있는가?
10. Parsing 성공 후 Fasoo가 실패해도 Parsing 상태가 성공으로 남는 이유는 무엇인가?
11. 실패한 비식별화만 재실행할 때 어떤 Artifact를 재사용하는가?
12. 서버 재시작 시 `RUNNING` Run이 왜 `INTERRUPTED`로 바뀌는가?
13. `MAX_CONCURRENT_RUNS`가 여러 Uvicorn Worker에서 전역 제한이 아닌 이유는 무엇인가?
14. `response_model`이 문서화 외에 어떤 보안 역할을 하는가?
15. Service와 Repository를 분리한 이유와 분리하지 않아도 되는 경우는 무엇인가?
16. 외부 API 호출과 DB Transaction의 경계를 어디에 두어야 하는가?
17. `async def` 안에서 Blocking 파일 I/O를 실행하면 무슨 일이 생기는가?
18. Frontend는 언제 Polling을 시작하고 어떤 상태에서 중단하는가?
19. 다른 사용자의 Run을 조회할 수 없도록 어느 계층에서 검사하는가?
20. 현재 MVP를 다중 Worker 운영 구조로 바꾸려면 무엇이 달라져야 하는가?

처음부터 모든 답을 외우려고 하지 마세요. 아래 순서대로 실제 요청을 한 번 추적한
뒤 질문으로 돌아오면 대부분 자연스럽게 연결됩니다.

## 2. 먼저 기억할 다섯 문장

ParseLab의 전체 구조는 다음 다섯 문장으로 요약할 수 있습니다.

1. **FastAPI Router는 HTTP를 해석하고 Service에 전달한다.**
2. **Service는 업무 규칙과 Transaction 순서를 결정한다.**
3. **Repository는 SQLAlchemy를 이용해 데이터를 조회하고 변경한다.**
4. **Task Pipeline은 Parser와 비식별화를 실행하고 상태를 단계별로 저장한다.**
5. **PostgreSQL은 메타데이터를, StorageService는 큰 Artifact를 저장한다.**

코드를 읽다가 길을 잃으면 현재 코드가 이 다섯 역할 중 어디에 속하는지 먼저
판단하세요.

## 3. 핵심 객체의 관계

```text
User
│
├─ Document
│  │
│  └─ Experiment
│     │
│     ├─ ExperimentRun ─ RunResult
│     │                 └ raw.json
│     │                 └ canonical.json
│     │                 └ output.md
│     │                 └ output.txt
│     │
│     ├─ ExperimentRun ─ DeidentificationResult
│     │                 └ deidentified.json
│     │
│     └─ ExperimentRun ─ ManualEvaluation
│
└─ ParserConnector
   └─ ParserPreset
```

`Experiment`는 비교 작업 전체이고 `ExperimentRun`은 Parser 하나의 실행입니다.
문서 하나를 Parser 3개로 비교하면 Experiment Row는 1개, Run Row는 3개입니다.

`RunResult`는 결과 파일 자체가 아니라 결과 파일의 상대 경로와 Page 수, Text 길이,
처리시간 같은 요약을 저장합니다. 실제 큰 내용은 파일 저장소에 있습니다.

## 4. 전체 요청 경로

```text
Browser
  │
  ▼
React Page
  │ fetch + JWT
  ▼
FastAPI Middleware
  │
  ▼
APIRouter Endpoint
  │
  ├─ Pydantic 입력 검증
  ├─ AsyncSession Dependency
  ├─ CurrentUser Dependency
  └─ StorageService Dependency
  │
  ▼
Service
  │
  ├─ Repository → PostgreSQL
  ├─ StorageService → data/
  └─ TaskManager → Pipeline → Adapter
  │
  ▼
Pydantic Response Model
  │
  ▼
JSON 또는 FileResponse
  │
  ▼
React Query Cache → 화면
```

이 경로를 가입, 업로드, Experiment 실행, 결과 비교 순으로 직접 따라가겠습니다.

## 5. 학습 환경 준비

### Docker로 전체 실행

프로젝트 루트에서 실행합니다.

```bash
cp .env.example .env
docker compose up --build
```

기본 주소:

| 대상 | 주소 |
|---|---|
| Frontend | <http://localhost:5173> |
| Backend 상태 | <http://localhost:8000/health> |
| Swagger UI | <http://localhost:8000/docs> |
| OpenAPI JSON | <http://localhost:8000/openapi.json> |
| PostgreSQL | `localhost:5432` |

포트를 변경했다면 `.env`의 `FRONTEND_PORT`, `BACKEND_PORT`,
`POSTGRES_PORT`, `VITE_API_URL`, `CORS_ORIGINS`를 기준으로 읽습니다.

### 코드를 디버깅하기 좋은 로컬 실행

PostgreSQL만 Docker로 실행합니다.

```bash
docker compose up -d postgres
```

Backend:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

`--reload`는 파일 변경 시 개발 서버를 재시작합니다. 실행 중인 In-Process Task도
재시작의 영향을 받으므로, Run 실행 중 코드를 저장하면 `INTERRUPTED` 상태를 볼 수
있습니다.

## 6. 1단계: 애플리케이션 시작 이해하기

첫 번째로 읽을 파일은 [`backend/app/main.py`](../backend/app/main.py)입니다.

### 코드 조립 순서

```text
Settings 읽기
→ FastAPI Instance 생성
→ CORS Middleware 등록
→ 공통 Exception Handler 등록
→ /api/v1 Router 등록
→ /health Endpoint 등록
```

FastAPI의 `lifespan`은 프로세스 자원의 수명을 관리합니다.

시작 전반부:

1. `DATA_ROOT` 디렉터리를 만듭니다.
2. `AUTO_CREATE_TABLES=true`이면 개발 편의를 위해 Table을 생성합니다.
3. 이전 프로세스에서 `RUNNING`이던 Parsing과 비식별화를 `INTERRUPTED`로 바꿉니다.
4. `TaskManager`를 생성해 `app.state.task_manager`에 저장합니다.

종료 후반부:

1. TaskManager가 소유한 Task를 취소합니다.
2. 취소된 Task들이 끝날 때까지 기다립니다.
3. SQLAlchemy Engine과 Connection Pool을 정리합니다.

### 확인 실습

```bash
curl http://localhost:8000/health
```

예상 응답:

```json
{"status":"ok"}
```

### 이해 포인트

- Module Import 시점에는 `app`이 조립됩니다.
- 실제 자원 준비는 ASGI Server가 Lifespan을 시작할 때 실행됩니다.
- `app.state`는 같은 프로세스의 요청들이 공유하는 애플리케이션 상태입니다.
- Worker가 여러 개면 Worker마다 별도의 `app.state`와 TaskManager가 생깁니다.

### Breakpoint

- `lifespan()` 첫 줄
- `yield`
- `TaskManager.shutdown()`

`yield` 이전은 시작 단계이고 이후는 종료 단계입니다.

## 7. 2단계: Router와 Dependency 이해하기

읽을 파일:

1. [`backend/app/api/v1/router.py`](../backend/app/api/v1/router.py)
2. [`backend/app/api/dependencies.py`](../backend/app/api/dependencies.py)
3. [`backend/app/db/session.py`](../backend/app/db/session.py)

### Router 조립

최상위 `api_router`에 `/api/v1` Prefix가 있고 기능 Router가 다시 `/auth`,
`/documents`, `/experiments` 같은 Prefix를 가집니다.

```text
/api/v1 + /documents + /{document_id}
= /api/v1/documents/{document_id}
```

### Dependency Graph

```python
SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[StorageService, Depends(get_storage)]
CurrentUser = Annotated[User, Depends(get_current_user)]
```

Endpoint가 다음처럼 선언되면:

```python
async def list_documents(
    user: CurrentUser,
    session: SessionDep,
) -> list[DocumentResponse]:
    ...
```

FastAPI는 Endpoint를 호출하기 전에:

1. `get_session()`으로 요청 전용 Session을 만듭니다.
2. `HTTPBearer`로 Authorization Header를 읽습니다.
3. JWT를 검증해 User ID를 얻습니다.
4. 같은 요청 Session으로 User를 조회합니다.
5. 활성 사용자면 Endpoint를 호출합니다.
6. 응답이 끝나면 Session Context를 닫습니다.

### Dependency Cache 이해

같은 요청에서 `CurrentUser`와 `SessionDep`가 모두 Session을 요구해도 FastAPI는
기본적으로 동일 Dependency 결과를 요청 범위에서 재사용합니다.

`get_storage()`는 추가로 `lru_cache`가 적용되어 프로세스 수명 동안
`StorageService`를 재사용합니다. StorageService는 설정값만 가지고 가변 요청
상태를 가지지 않으므로 재사용할 수 있습니다.

반면 `AsyncSession`은 요청마다 새로 만들어야 합니다.

### 확인 실습

Token 없이 호출:

```bash
curl -i http://localhost:8000/api/v1/documents
```

잘못된 Token:

```bash
curl -i \
  -H 'Authorization: Bearer invalid-token' \
  http://localhost:8000/api/v1/documents
```

두 요청이 `AUTHENTICATION_REQUIRED`와 `INVALID_TOKEN` 중 어느 오류가 되는지
확인합니다.

## 8. 3단계: 회원가입과 로그인 추적

읽을 순서:

1. [`api/v1/auth.py`](../backend/app/api/v1/auth.py)
2. [`schemas/auth.py`](../backend/app/schemas/auth.py)
3. [`services/auth_service.py`](../backend/app/services/auth_service.py)
4. [`repositories/user_repository.py`](../backend/app/repositories/user_repository.py)
5. [`core/security.py`](../backend/app/core/security.py)

### 회원가입 흐름

```text
POST /auth/signup
→ SignupRequest 검증
→ Email 중복 조회
→ 전체 User 수 조회
→ 첫 사용자면 ADMIN, 아니면 USER
→ Password Hash
→ User INSERT
→ 첫 사용자면 Mock Parser 2개 INSERT
→ COMMIT
→ UserResponse
```

첫 사용자와 Mock Parser가 같은 Commit에 포함되므로 Parser 초기화가 실패하면
회원가입도 함께 확정되지 않습니다.

### 로그인 흐름

```text
POST /auth/login
→ Email로 User 조회
→ Password Hash 검증
→ 비활성 사용자 확인
→ sub, iat, exp를 가진 JWT 생성
→ access_token 반환
```

JWT Payload의 `sub`에는 User UUID가 들어갑니다. Token은 사용자 정보를 암호화한
것이 아니라 서명된 값이므로 민감한 정보를 Payload에 넣으면 안 됩니다.

### Breakpoint

- `AuthService.signup()`
- `AuthService._seed_mock_parsers()`
- `hash_password()`
- `AuthService.login()`
- `create_access_token()`

### 이해도 확인

- 첫 가입자 결정에 동시에 두 Signup이 들어오면 경쟁 조건이 생길 수 있는가?
- Email Unique Constraint가 Service의 사전 조회와 별도로 필요한 이유는 무엇인가?
- `password_hash`가 `UserResponse`에 노출되지 않는 이유는 무엇인가?

전문가 답변의 핵심은 “애플리케이션 조회만으로 동시성을 완전히 막을 수 없으며 DB
제약조건과 오류 처리가 함께 필요하다”입니다.

## 9. 4단계: 문서 업로드 추적

읽을 순서:

1. [`frontend/src/pages/DocumentsPage.tsx`](../frontend/src/pages/DocumentsPage.tsx)
2. [`api/v1/documents.py`](../backend/app/api/v1/documents.py)
3. [`services/document_service.py`](../backend/app/services/document_service.py)
4. [`services/storage_service.py`](../backend/app/services/storage_service.py)
5. [`repositories/document_repository.py`](../backend/app/repositories/document_repository.py)
6. [`db/models/document.py`](../backend/app/db/models/document.py)

### Frontend

Browser의 `File`을 `FormData`에 `file`이라는 이름으로 넣습니다.

```text
input[type=file]
→ FormData
→ POST /documents
→ 성공 시 ["documents"] Query Cache 무효화
→ 목록 자동 재조회
```

`FormData`를 보낼 때 API Client가 `Content-Type: application/json`을 강제로 넣지
않습니다. Browser가 Multipart Boundary를 포함한 Header를 직접 만들어야 하기
때문입니다.

### Backend

```text
UploadFile
→ 안전한 원본 파일명 생성
→ 확장자·MIME 확인
→ documents/{UUID}/original.ext 경로 생성
→ 1 MiB Chunk 단위 읽기
→ 크기 제한과 SHA-256 계산
→ 파일 저장
→ Document Row INSERT
→ COMMIT
```

파일 저장에 성공했지만 DB 작업이 실패하면 `DocumentService`가 방금 저장한 파일을
삭제해 고아 Artifact를 줄입니다.

### `UploadFile`을 쓰는 이유

큰 파일 전체를 `bytes`로 받으면 요청 크기만큼 메모리를 사용합니다. `UploadFile`은
File-like Interface를 제공하며 Chunk 단위 처리가 가능합니다.

### 저장소 보안

`StorageService._safe_path()`는 최종 절대 경로가 `DATA_ROOT` 내부인지 확인합니다.
DB 또는 사용자 입력에 `../../secret` 같은 값이 들어가도 저장소 밖으로 나갈 수
없게 하는 마지막 방어선입니다.

### Breakpoint

- `upload_document()`
- `DocumentService.upload()`
- `StorageService.save_document()`의 Chunk Loop
- `DocumentRepository.create()`

다음 값을 관찰합니다.

- `upload.filename`
- `upload.content_type`
- 누적 `size`
- `digest.hexdigest()`
- DB에 저장되는 `storage_path`

## 10. 5단계: Parser Registry 이해하기

읽을 순서:

1. [`db/models/parser.py`](../backend/app/db/models/parser.py)
2. [`schemas/parser.py`](../backend/app/schemas/parser.py)
3. [`services/parser_service.py`](../backend/app/services/parser_service.py)
4. [`adapters/parsers/base.py`](../backend/app/adapters/parsers/base.py)
5. [`adapters/parsers/registry.py`](../backend/app/adapters/parsers/registry.py)

### 네 가지 개념 구분

| 개념 | 저장 위치 | 역할 |
|---|---|---|
| Connector | PostgreSQL | Parser 이름, URL, Command, 기본 설정 |
| Adapter | Python 코드 | 외부 Parser를 실제로 호출 |
| Preset | PostgreSQL | 재사용 가능한 Config |
| Config Snapshot | `experiment_runs` | 특정 Run에 실제 적용된 최종 Config |

### 실행 방식

| 실행 방식 | Adapter 예 | 특징 |
|---|---|---|
| `BUILTIN` | `MockParserAdapter` | 현재 Python 프로세스에서 실행 |
| `HTTP` | `SynapHttpAdapter` | HTTPX로 외부 서비스 호출 |
| `COMMAND` | `DoclingCommandAdapter` | 안전한 인수 배열로 subprocess 실행 |

Connector의 `execution_type`과 `adapter_key` 조합은
`ADAPTER_EXECUTION_TYPES`로 검증됩니다. 예를 들어 `synap_http`를 `COMMAND`로
등록할 수 없습니다.

### Config 우선순위

```text
Connector default_config
          ↓ 재귀 병합
Preset config
          ↓ 재귀 병합
Run config_override
          ↓
최종 config_snapshot
          ↓
JSON Schema 검증
```

뒤에 오는 값이 앞의 값을 덮어씁니다. 중첩 Dictionary는 재귀적으로 병합됩니다.

### Snapshot이 필요한 이유

실험이 끝난 뒤 관리자가 Connector 기본 설정을 바꾸더라도 과거 Run의 실제 실행
설정은 변하면 안 됩니다. `parser_snapshot`과 `config_snapshot`은 재현성을 위한
실행 당시 복사본입니다.

## 11. 6단계: Experiment 생성 추적

읽을 순서:

1. [`frontend/src/pages/NewExperimentPage.tsx`](../frontend/src/pages/NewExperimentPage.tsx)
2. [`api/v1/experiments.py`](../backend/app/api/v1/experiments.py)
3. [`schemas/experiment.py`](../backend/app/schemas/experiment.py)
4. [`services/experiment_service.py`](../backend/app/services/experiment_service.py)
5. [`repositories/experiment_repository.py`](../backend/app/repositories/experiment_repository.py)

### UI 정책과 API 계약의 차이

Frontend는 의미 있는 비교를 위해 Parser를 2개 이상 선택하도록 검사합니다.
Backend의 `ExperimentCreate.parser_runs`는 1~8개를 허용합니다.

```text
Frontend 정책: 비교 화면을 위한 2개 이상
Backend 계약: 단일 Parser 실행도 가능한 1~8개
```

이 차이는 현재 코드의 실제 동작입니다. Backend도 항상 비교 실험만 허용하려면
Schema의 `min_length`를 2로 바꾸고 테스트를 추가해야 합니다.

### 생성 흐름

```text
Document 소유권 확인
→ 같은 Parser 중복 선택 확인
→ Parser 존재·활성 상태 확인
→ 문서 확장자 지원 여부 확인
→ Preset 소속 확인
→ Config 병합과 JSON Schema 검증
→ Experiment 생성
→ flush()로 Experiment UUID 확보
→ Parser마다 ExperimentRun 생성
→ COMMIT
→ 각 Run을 TaskManager에 제출
→ 202 Accepted
```

### `flush()`와 `commit()` 차이

`flush()`는 현재 Transaction의 INSERT를 DB에 보내 ID를 확보하지만 Transaction을
끝내지 않습니다. 뒤의 Run 생성이 실패하면 Experiment INSERT도 함께 Rollback할
수 있습니다.

`commit()`은 Transaction을 확정해 다른 Session에서도 Run을 조회할 수 있게 합니다.
Task는 Commit 이후에 제출되어야 합니다.

### Breakpoint

- `create_experiment()`
- `ExperimentService.create()`
- `self.session.flush()`
- `self.session.commit()`
- `ExperimentService._submit()`
- `TaskManager.submit()`

`created_runs` 길이와 TaskManager의 `_tasks` Key를 비교합니다.

## 12. 7단계: TaskManager와 Parsing Pipeline 추적

읽을 순서:

1. [`task_manager/manager.py`](../backend/app/task_manager/manager.py)
2. [`task_manager/pipeline.py`](../backend/app/task_manager/pipeline.py)
3. [`adapters/parsers/mock.py`](../backend/app/adapters/parsers/mock.py)
4. [`normalizers/text_normalizer.py`](../backend/app/normalizers/text_normalizer.py)

### TaskManager

```text
Run 제출
→ 같은 Run ID가 Registry에 있으면 거절
→ asyncio.create_task()
→ Semaphore 획득 대기
→ job() 실행
→ 성공·실패·취소와 관계없이 Registry에서 제거
```

Semaphore는 동시에 Parser를 너무 많이 실행해 CPU, Memory, 외부 API를 과부하시키는
것을 막는 Backpressure 장치입니다.

### Parsing Pipeline

```text
PENDING 확인
→ RUNNING + started_at COMMIT
→ Connector와 Document 조회
→ Adapter 선택
→ Run Work Directory 준비
→ wait_for(Adapter.parse(), timeout)
→ Adapter.normalize()
→ raw/canonical/markdown/text 저장
→ 지표 계산
→ RunResult INSERT
→ SUCCEEDED + completed_at COMMIT
→ 비식별화 요청 여부 확인
```

### 성공 Artifact

```text
data/runs/{run_id}/
├── raw.json
├── canonical.json
├── output.md
└── output.txt
```

`work/`는 Command Adapter의 중간 결과를 위해 사용하고 실행 종료 시 정리합니다.

### 실패 처리

| 실패 | 오류 코드 예 | 최종 상태 |
|---|---|---|
| 업무 검증 오류 | `PARSER_DISABLED` | `FAILED` |
| Timeout | `PARSER_TIMEOUT` | `FAILED` |
| 예상하지 못한 오류 | `PARSER_EXECUTION_FAILED` | `FAILED` |
| Task 취소 | 별도 오류 대신 상태 기록 | `INTERRUPTED` |

오류 메시지는 DB에 저장하고 `error.log`에도 제한된 길이로 기록합니다.

### 중요한 Transaction 관찰

Pipeline은 `RUNNING`을 먼저 Commit하지만, 그 뒤 같은 Session으로 Connector와
Document를 조회합니다. SQLAlchemy의 `autobegin`으로 새 읽기 Transaction이 시작될
수 있고 외부 Parser 호출 동안 Session Context가 유지됩니다.

운영 수준에서는 다음 구조가 더 안전합니다.

```text
Session A: 상태 변경과 실행 Snapshot 조회 → COMMIT/CLOSE
외부 Parser 실행: DB Session 없음
Session B: 결과와 최종 상태 저장 → COMMIT/CLOSE
```

현재 구현과 개선 목표를 구분해서 이해해야 합니다.

### Breakpoint

- `TaskManager._execute()`
- `execute_run()`의 상태 변경 Commit
- `get_parser_adapter()`
- `adapter.parse()`
- `adapter.normalize()`
- `storage.save_parser_results()`
- 실패 처리 `except Exception`
- `finally`의 Work Directory 정리

## 13. 8단계: 비식별화 완벽히 이해하기

읽을 순서:

1. [`adapters/deidentifiers/base.py`](../backend/app/adapters/deidentifiers/base.py)
2. [`adapters/deidentifiers/registry.py`](../backend/app/adapters/deidentifiers/registry.py)
3. [`adapters/deidentifiers/mock.py`](../backend/app/adapters/deidentifiers/mock.py)
4. [`adapters/deidentifiers/fasoo_http.py`](../backend/app/adapters/deidentifiers/fasoo_http.py)
5. [`task_manager/pipeline.py`](../backend/app/task_manager/pipeline.py)의
   `execute_deidentification()`
6. [`db/models/result.py`](../backend/app/db/models/result.py)의
   `DeidentificationResult`

### Adapter 선택

```text
FASOO_ENABLED=false → MockDeidentifierAdapter
FASOO_ENABLED=true  → FasooHttpDeidentifierAdapter
```

Mock Adapter는 외부 서버 없이 Email, 전화번호, 주민등록번호 패턴을 마스킹하므로
개발과 통합 테스트에 사용됩니다.

### 입력 종류

`FASOO_INPUT_TYPE`에 따라 이미 저장된 Artifact 중 하나를 선택합니다.

| 설정 | 입력 |
|---|---|
| `ORIGINAL_FILE` | 업로드 원본 |
| `TEXT` | `output.txt` |
| `MARKDOWN` | `output.md` |
| `CANONICAL_JSON` | `canonical.json` |

해당 Artifact가 없으면 Parsing 상태를 바꾸지 않고 비식별화만 실패합니다.

### 상태 흐름

```text
NOT_REQUESTED

또는

PENDING → RUNNING → SUCCEEDED
                  └→ FAILED

PENDING/RUNNING → 취소·재시작 → INTERRUPTED
```

Parsing과 비식별화 상태를 분리한 것이 핵심입니다.

```text
parse_status = SUCCEEDED
deidentification_status = FAILED
```

이 상태는 모순이 아닙니다. Parser 결과는 정상이고 후속 개인정보 처리만 실패했다는
정확한 표현입니다.

### 비식별화 저장 데이터

PostgreSQL:

- Provider
- 입력 종류
- `deidentified.json` 상대 경로
- 탐지 Entity 수
- 마스킹 Entity 수
- 처리 지표
- 오류 메시지

파일 저장소:

```text
data/runs/{run_id}/deidentified.json
```

### 재실행

Parsing이 이미 `SUCCEEDED`이고 비식별화가 `FAILED` 또는 `INTERRUPTED`이면
`ExperimentService.retry()`는 Parsing을 다시 실행하지 않습니다.

```text
기존 output.txt 또는 선택된 Artifact 재사용
→ deidentification_status=PENDING
→ execute_deidentification()만 제출
```

### Fasoo 연동 경계

`build_fasoo_request()`와 `parse_fasoo_response()`가 제품별 요청·응답 Mapping을
격리합니다. 실제 사내 Fasoo 계약이 달라지면 이 함수와 Adapter를 수정하고 Pipeline
계약은 유지하는 것이 목표입니다.

### 보안 확인

- API Key를 Log에 기록하지 않습니다.
- 원문 전체를 오류 메시지에 포함하지 않습니다.
- Mock 결과의 Entity 정보에도 실제 개인정보 값을 보존하지 않습니다.
- Timeout을 적용합니다.
- 응답에 비식별화 Text가 없으면 명시적 실패로 처리합니다.

### Breakpoint

- `_deidentification_input_path()`
- `get_deidentifier_adapter()`
- `adapter.deidentify()`
- `save_deidentification_result()`
- 실패 분기의 `parse_status`와 `deidentification_status`

실패 Adapter를 주입한 통합 테스트에서 Parsing 상태가 실제로 유지되는지 확인합니다.

## 14. 9단계: 결과 비교와 평가 이해하기

읽을 순서:

1. [`services/comparison_service.py`](../backend/app/services/comparison_service.py)
2. [`utils/text_diff.py`](../backend/app/utils/text_diff.py)
3. [`services/evaluation_service.py`](../backend/app/services/evaluation_service.py)
4. [`frontend/src/pages/ComparePage.tsx`](../frontend/src/pages/ComparePage.tsx)

### 비교 응답 조립

`ComparisonService`는 두 저장소의 데이터를 합칩니다.

```text
PostgreSQL
├─ Run 상태
├─ 처리 시간
├─ 개수 지표
├─ 비식별화 요약
└─ 사용자 평가

파일 저장소
├─ Text
├─ Markdown
├─ Canonical JSON
└─ 비식별화 Text

         ↓ 결합

ComparisonResponse
```

Canonical JSON의 Table Block은 화면에서 사용하기 쉬운 Table 구조로 투영하고,
Page별 Text 길이와 전체 Artifact 크기를 계산합니다.

### Text Diff

두 Run이 같은 Experiment에 속하고 현재 사용자가 그 Experiment를 소유하는지 먼저
검사합니다. 공백 정규화 옵션을 적용한 뒤 유사도, 추가 문자, 제거 문자와 Diff
조각을 반환합니다.

### 수동 평가

각 사용자는 Run마다 하나의 평가를 가질 수 있습니다.

- 본문 점수
- 표 구조 점수
- 읽기 순서 점수
- 비식별화 점수
- 메모
- 선호 Parser 여부

같은 Experiment에서 새 Run을 선호 결과로 지정하면 기존 선호 Run은 해제됩니다.
이 규칙은 UI 상태가 아니라 DB를 변경하는 Service 규칙입니다.

### CSV 보안

CSV Cell이 `=`, `+`, `-`, `@`로 시작하면 Spreadsheet가 수식으로 실행할 수
있습니다. `csv_safe()`는 앞에 작은따옴표를 붙여 Formula Injection을 방지합니다.

## 15. 10단계: Frontend 데이터 흐름 이해하기

읽을 순서:

1. [`frontend/src/main.tsx`](../frontend/src/main.tsx)
2. [`frontend/src/App.tsx`](../frontend/src/App.tsx)
3. [`frontend/src/lib/api.ts`](../frontend/src/lib/api.ts)
4. [`frontend/src/types.ts`](../frontend/src/types.ts)
5. 각 [`pages`](../frontend/src/pages)

### 애플리케이션 조립

```text
main.tsx
→ QueryClientProvider
→ BrowserRouter
→ App
→ Protected Route
→ Layout
→ Page
```

### API Client

`api<T>()`는:

1. `localStorage`에서 JWT를 읽습니다.
2. Authorization Header를 추가합니다.
3. JSON Body에만 Content-Type을 설정합니다.
4. 공통 오류 응답을 `ApiError`로 바꿉니다.
5. 성공 JSON을 Generic Type `T`로 반환합니다.

TypeScript의 `T`는 Runtime 검증이 아닙니다. Backend 응답이 Type과 다르더라도
Browser에서 자동으로 거절하지 않습니다. 더 강한 Client가 필요하면 OpenAPI Code
Generation 또는 Zod 같은 Runtime Schema를 검토할 수 있습니다.

### Polling

[`ExperimentPage`](../frontend/src/pages/ExperimentPage.tsx)는 TanStack Query의
`refetchInterval`을 사용합니다.

```text
PENDING/RUNNING → 2초마다 GET /experiments/{id}
COMPLETED/PARTIALLY_COMPLETED/FAILED → Polling 중단
```

Run 재실행이 성공하면 해당 Experiment Query를 무효화해 즉시 다시 조회합니다.

### Query Key

```text
["documents"]
["parsers"]
["parser-presets", parserId]
["experiment", experimentId]
["comparison", experimentId]
```

Query Key는 Server State의 주소입니다. Mutation 후 관련 Key를 무효화해야 화면이
최신 상태를 다시 가져옵니다.

## 16. 실제 데이터 한 건 따라가기

TXT 문서 하나를 Mock Parser 2개와 비식별화로 실행했다고 가정합니다.

### 생성되는 DB 데이터

```text
users                         1 Row
parser_connectors             첫 가입 시 2 Row
documents                     1 Row
experiments                   1 Row
experiment_runs               2 Row
run_results                   성공 시 2 Row
deidentification_results      성공 또는 실패 기록 2 Row
manual_evaluations            평가할 때 최대 Run별 1 Row
```

### 생성되는 파일

```text
data/
├── documents/{document_id}/original.txt
└── runs/
    ├── {run_id_1}/
    │   ├── raw.json
    │   ├── canonical.json
    │   ├── output.md
    │   ├── output.txt
    │   └── deidentified.json
    └── {run_id_2}/
        ├── raw.json
        ├── canonical.json
        ├── output.md
        ├── output.txt
        └── deidentified.json
```

### ID 연결

```text
documents.id
    ├─ experiments.document_id
    └─ experiment_runs.document_id

experiments.id
    └─ experiment_runs.experiment_id

parser_connectors.id
    └─ experiment_runs.parser_connector_id

experiment_runs.id
    ├─ run_results.run_id
    ├─ deidentification_results.run_id
    └─ manual_evaluations.run_id
```

이 관계를 직접 종이에 그려보면 API와 Table 구조가 빠르게 정리됩니다.

## 17. 디버깅 실습

### 실습 A: HTTP 요청 한 건 추적

`POST /documents`에 다음 순서로 Breakpoint를 겁니다.

```text
upload_document
→ get_current_user
→ DocumentService.upload
→ StorageService.save_document
→ DocumentRepository.create
→ response_model 직렬화
```

확인할 질문:

- Pydantic 검증은 Endpoint 호출 전과 후 중 언제 일어나는가?
- 동일 요청에서 User 조회와 문서 저장이 같은 Session을 쓰는가?
- 원본 파일과 DB Row 중 무엇이 먼저 만들어지는가?
- DB 실패 시 파일은 어떻게 정리되는가?

### 실습 B: 백그라운드 경계 추적

`POST /experiments`에 다음 Breakpoint를 겁니다.

```text
ExperimentService.create
→ commit
→ TaskManager.submit
→ HTTP 202 응답
→ TaskManager._execute
→ execute_run
```

HTTP 응답과 Background Task Breakpoint 중 어느 것이 먼저 보이는지 관찰합니다.
Task Scheduling 순서 때문에 매우 빠른 Mock 작업에서는 실행이 응답과 거의 동시에
진행될 수 있지만 Client 계약상 응답은 완료를 의미하지 않습니다.

### 실습 C: 부분 실패 만들기

통합 테스트의 `FailingDeidentifier`처럼 비식별화 Adapter가 `AppError`를 발생시키게
합니다.

예상 결과:

```text
parse_status = SUCCEEDED
deidentification_status = FAILED
raw/canonical/markdown/text = 유지
deidentified.json = 없음
DeidentificationResult.error_message = 기록
```

그 뒤 Retry를 호출해 Parsing Adapter가 다시 실행되지 않고 비식별화만 실행되는지
확인합니다.

### 실습 D: 동시성 제한 확인

`.env`:

```env
MAX_CONCURRENT_RUNS=1
```

지연이 있는 Parser로 Run 여러 개를 만들고 한 번에 `RUNNING`인 실제 작업 수를
관찰합니다. DB의 상태 전이 시점과 Semaphore 획득 시점의 차이도 확인합니다.

현재 TaskManager는 Semaphore를 획득한 뒤 `job()`을 호출하므로, Semaphore를
기다리는 Task의 DB 상태는 `PENDING`입니다.

## 18. 테스트를 설계 문서처럼 읽기

가장 먼저 읽을 테스트는
[`test_vertical_slice.py`](../backend/tests/integration/test_vertical_slice.py)입니다.

이 테스트는 다음 흐름을 코드로 증명합니다.

```text
가입
→ 로그인
→ 문서 업로드
→ Mock Parser 자동 등록
→ Preset 생성·수정
→ Experiment 생성
→ Parser 2개 실행
→ 비식별화
→ Artifact 확인
→ 비교
→ Text Diff
→ 평가와 선호 Parser
→ CSV
→ Command Adapter
→ 비식별화 실패
→ 비식별화만 재실행
```

테스트 읽기 순서:

1. 통합 테스트로 전체 이야기를 파악합니다.
2. 이해되지 않는 단계의 단위 테스트를 찾습니다.
3. 단위 테스트에서 대상 구현으로 이동합니다.
4. 성공 테스트와 실패 테스트를 한 쌍으로 읽습니다.

대표 연결:

| 궁금한 내용 | 테스트 |
|---|---|
| 동시 실행 제한 | `test_task_manager.py` |
| HTTP Adapter | `test_http_adapter.py` |
| Command 보안 | `test_command_adapter.py` |
| 비식별화 Mapping | `test_deidentifier_adapter.py` |
| Config 병합·검증 | `test_config.py`, `test_config_validation.py` |
| 상태 계산 | `test_experiment_status.py` |
| Text Diff | `test_text_diff.py` |
| 저장소 경로 | `test_storage.py` |

## 19. 자주 혼동하는 부분

### `async def`이면 모든 코드가 Non-Blocking인가?

아닙니다. 함수 안에서 호출하는 작업도 비동기여야 합니다. 동기 파일 I/O는
`asyncio.to_thread()`로 보내고, CPU 집약 작업은 별도 Process나 Worker를
검토해야 합니다.

### `create_task()`는 작업 Queue인가?

프로세스 메모리 안의 Task Registry일 뿐입니다. 재시작 복구, 여러 Worker 간 분배,
영속적인 재시도 기능은 없습니다.

### `commit()`하면 Session이 닫히는가?

아닙니다. Transaction은 끝나지만 Session은 계속 사용할 수 있습니다. 다음 조회가
`autobegin`으로 새 Transaction을 시작할 수 있습니다.

### Pydantic Model과 ORM Model은 같은가?

아닙니다. Pydantic은 외부 계약과 데이터 검증, ORM은 DB 영속 구조를 담당합니다.

### `DELETE /parsers/{id}`는 Row를 삭제하는가?

아닙니다. 과거 Run의 참조와 이력을 보존하기 위해 `is_active=false`로 바꾸는
Soft Delete입니다.

### 비식별화가 실패하면 Experiment도 실패인가?

모든 Parser가 성공해도 요청된 비식별화 일부가 실패하면 전체 계산 상태는
`PARTIALLY_COMPLETED`가 될 수 있습니다. 세부 원인은 각 Run의 두 상태를 함께
봐야 합니다.

### Frontend TypeScript 타입이 Backend 응답을 검증하는가?

아닙니다. Compile Time 도움만 제공합니다. Runtime 계약의 기준은 FastAPI OpenAPI와
실제 응답입니다.

## 20. 현재 설계에서 찾아야 할 고급 개선점

아래 항목은 프로젝트를 이해한 뒤 도전할 과제입니다.

### Transaction과 동시성

- 첫 관리자 동시 가입 경쟁
- 같은 Run에 대한 동시 Retry
- Experiment Commit과 Task 제출 사이의 프로세스 종료
- 외부 호출 중 열린 읽기 Transaction
- 평가의 선호 Parser 동시 수정

### 작업 실행

- `PENDING` Run Scanner
- DB Lease와 Heartbeat
- Idempotency Key
- Durable Queue와 Worker 분리
- 여러 Worker의 전역 동시성 제한

### API 계약

- Pydantic 검증 오류와 `AppError` 형식 통일
- Cursor Pagination
- API Version 호환성 정책
- OpenAPI 기반 TypeScript Client 생성
- Idempotent Experiment 생성 API

### 보안

- Generic HTTP Parser SSRF 방어
- Magic Byte와 악성 문서 검사
- Rate Limit
- Refresh Token 회전
- HttpOnly Cookie와 CSRF 정책
- Audit Log

### 관측 가능성

- Request ID
- 구조화 JSON Log
- Parser별 성공률과 지연시간 Metric
- HTTP 요청부터 외부 Parser까지 분산 Trace
- Readiness와 Liveness 분리

## 21. 직접 구현할 단계별 과제

### 초급

1. `/api/v1/system/info` 읽기 전용 Endpoint를 추가합니다.
2. 새 요청·응답 Schema를 만들고 `response_model`을 적용합니다.
3. 테스트에서 정상 입력과 잘못된 입력을 검증합니다.
4. OpenAPI 문서에서 Schema가 어떻게 보이는지 확인합니다.

### 중급

1. 문서 목록에 확장자와 파일명 검색 Query를 추가합니다.
2. Router가 아니라 Repository에 조회 조건을 구현합니다.
3. 현재 사용자 소유권을 유지합니다.
4. Pagination과 정렬을 추가합니다.
5. PostgreSQL Query와 Index 필요성을 설명합니다.

### 고급

1. `RequestValidationError`를 공통 오류 계약으로 변환합니다.
2. Request ID Middleware를 추가합니다.
3. 오류 응답과 Log에 같은 Request ID를 넣습니다.
4. 단위·통합 테스트를 작성합니다.
5. 개인정보가 Log에 들어가지 않는지 확인합니다.

### 전문가

1. DB 기반 Run Lease를 설계합니다.
2. Worker가 Run을 원자적으로 Claim하도록 구현합니다.
3. Lease 만료 시 다른 Worker가 복구할 수 있게 합니다.
4. 같은 Run이 중복 실행되어도 결과가 일관적인 Idempotency를 보장합니다.
5. 서버 강제 종료, 네트워크 Timeout, DB Deadlock을 주입한 테스트를 작성합니다.
6. 기존 API 계약을 깨지 않고 TaskManager를 교체합니다.

## 22. 최종 이해도 점검

### 구조

- Router, Service, Repository, Adapter의 책임을 예시로 설명할 수 있는가?
- FastAPI Dependency Graph를 그림으로 그릴 수 있는가?
- 요청 Session과 Background Session의 수명 차이를 설명할 수 있는가?

### 데이터

- Experiment 하나를 실행했을 때 생성되는 Row와 파일을 나열할 수 있는가?
- Parser와 Config Snapshot이 필요한 이유를 설명할 수 있는가?
- DB와 파일 저장소 사이의 원자성 문제를 설명할 수 있는가?

### 비동기

- Coroutine, Task, Semaphore, Cancellation의 차이를 설명할 수 있는가?
- `202 Accepted` 이후 Client가 해야 할 일을 설명할 수 있는가?
- 프로세스 재시작과 다중 Worker에서 현재 TaskManager의 한계를 설명할 수 있는가?

### 비식별화

- 네 가지 입력 종류의 실제 Artifact 경로를 말할 수 있는가?
- Parsing과 비식별화가 별도 Commit인 이유를 설명할 수 있는가?
- 비식별화만 재실행되는 조건과 과정을 설명할 수 있는가?

### 보안

- 경로 이탈, Command Injection, SSRF, CSV Injection의 방어 위치를 찾을 수 있는가?
- JWT 인증과 Resource 소유권 검사가 왜 모두 필요한지 설명할 수 있는가?
- 현재 MVP에서 운영 전에 바꿔야 할 Secret과 Token 전략을 말할 수 있는가?

### 테스트

- 전체 Vertical Slice를 검증하는 테스트를 찾을 수 있는가?
- 부분 실패와 재시작 시나리오의 테스트를 설계할 수 있는가?
- SQLite 테스트만으로 PostgreSQL 동작을 완전히 보장할 수 없는 이유를 설명할 수
  있는가?

모든 질문에 답할 수 있고, 새 기능을 어느 계층에 넣어야 하는지 설명한 뒤 테스트까지
작성할 수 있다면 ParseLab을 충분히 이해한 것입니다.

## 23. 추천 학습 일정

| 일차 | 목표 | 결과물 |
|---|---|---|
| 1일차 | 실행, UI, Swagger, 전체 구조 | 직접 그린 요청 흐름 |
| 2일차 | Router, Schema, Dependency, 인증 | 인증 요청 추적 메모 |
| 3일차 | AsyncSession, Model, Repository, Transaction | Table 관계도 |
| 4일차 | Parser Registry, Config, Adapter | 새 Mock Adapter |
| 5일차 | TaskManager, Pipeline, 상태 머신 | 실패·취소 실험 기록 |
| 6일차 | 비식별화, 비교, 평가, Frontend Polling | End-to-End 흐름 설명 |
| 7일차 | 테스트, 보안, 운영 한계 | 개선 설계 문서와 테스트 |

하루에 많은 파일을 읽는 것보다 요청 하나를 처음부터 끝까지 추적하는 편이 훨씬
효과적입니다.

## 24. 마지막 원칙

전문가 수준의 이해는 코드를 외우는 것이 아닙니다.

- 왜 이 경계에서 Commit했는지 설명합니다.
- 어떤 실패가 발생할 수 있는지 먼저 생각합니다.
- 프로세스와 요청, Transaction과 객체의 수명을 구분합니다.
- 보안상 신뢰할 수 없는 입력이 어디서 들어오는지 찾습니다.
- 현재 규모에 맞는 단순한 설계와 확장 시 필요한 설계를 구분합니다.
- 변경 후 성공 경로뿐 아니라 실패와 경쟁 조건을 테스트합니다.

이 원칙으로 ParseLab의 요청 하나를 끝까지 설명할 수 있다면 다른 FastAPI
프로젝트에서도 같은 방식으로 구조를 빠르게 파악할 수 있습니다.
