<!-- ParseLab 실행 방법, 아키텍처, API 예시, FastAPI 학습 및 검증 안내서. -->
# ParseLab

ParseLab은 동일한 문서를 여러 Parser Adapter로 처리하고 원본 결과, Canonical JSON,
텍스트와 Markdown을 나란히 비교하는 내부 테스트 플랫폼입니다.

현재 구현은 설계서의 **Phase 1~4 MVP**입니다.

- 이메일/비밀번호 회원가입, 로그인, JWT 인증
- 첫 가입자를 ADMIN으로 생성하고 내장 Mock Parser 2개 자동 등록
- PDF, Office, TXT, Markdown 업로드와 SHA-256 계산
- PostgreSQL에는 메타데이터·상태·지표 저장
- 로컬 파일 시스템에는 원본·raw.json·canonical.json·Markdown·텍스트 저장
- `asyncio.create_task()`와 Semaphore를 이용한 최대 동시 실행 수 제한
- 서버 시작 시 `RUNNING` Run을 `INTERRUPTED`로 전환
- 실험 생성 즉시 `202 Accepted` 응답, React에서 2초 Polling
- Run 재실행·취소, 결과 파일 다운로드, 텍스트 Diff, 수동 평가 API
- React에서 실행 상태와 Parser 결과를 나란히 비교
- Synap/Generic HTTP Adapter와 Docling/Generic Command Adapter
- `shell=True` 없는 Command 실행, 허용 실행파일·Template 변수 검증
- Parser 수정·비활성화, Config JSON Schema 검증, Preset CRUD
- HTTP/Command Health Check, Timeout 및 표준 오류 코드, `error.log`
- Mock Fasoo와 Fasoo HTTP 비식별화 Adapter
- 파싱과 독립된 비식별화 상태·오류·지표 및 `deidentified.json`
- 비식별화 실패 시 성공한 파싱 결과 유지, 실패한 비식별화만 재실행
- React에서 원본 Text/Markdown과 비식별화 결과 전환 비교
- 기준·대상 Run 선택과 공백 정규화를 지원하는 Text Diff
- Canonical JSON Viewer, 표 셀·병합 구조 비교, 페이지별 텍스트 길이 지표
- Run별 1~5점 수동 평가, 메모와 실험별 단일 선호 Parser 표시
- 운영 지표·비식별화·평가를 포함한 UTF-8 CSV 내보내기

Synap API 계약과 Docling CLI 출력의 일반적인 형태를 지원하며, 사내 실제 계약에 맞춘
세부 매핑은 환경별 설정으로 조정할 수 있습니다. Fasoo API 계약은 요청·응답 매핑
함수로 격리했으며 실제 엔드포인트 계약에 맞춰 조정할 수 있습니다. MinerU와 Ground
Truth Dataset은 MVP 이후 범위입니다.

## 이 README를 활용하는 방법

이 프로젝트는 FastAPI 문법을 구경하는 예제가 아니라, 작은 서비스를 실제로
설계하고 운영할 때 필요한 개념을 한 흐름에서 학습할 수 있는 예제입니다.

실제 코드를 순서대로 따라가며 학습하려면
**[ParseLab 프로젝트 완벽 이해 가이드](docs/PROJECT_UNDERSTANDING_GUIDE.md)**를
먼저 사용하세요. 요청 추적 순서, Breakpoint, 비식별화 상세 흐름, 실습 과제와
이해도 점검표가 포함되어 있습니다.

처음 읽는다면 다음 순서가 가장 이해하기 쉽습니다.

1. 아래의 **한눈에 보는 설계**에서 전체 흐름을 파악합니다.
2. **요청 한 건의 이동 경로**를 읽으며 Router, Dependency, Service, Repository의
   책임을 구분합니다.
3. 서버를 실행하고 `/docs`에서 API를 직접 호출합니다.
4. `POST /experiments`가 `202 Accepted`를 반환한 뒤 백그라운드에서 Run을 실행하는
   과정을 디버거로 따라갑니다.
5. 마지막의 **FastAPI 전문가 학습 로드맵**에 있는 실습을 직접 구현합니다.


- 요청마다 DB Session을 왜 새로 만들고 언제 닫는가?
- `async def` 안에서 일반 파일 I/O를 그대로 호출하면 왜 위험한가?
- 외부 API 호출 전후로 DB Commit을 어디에서 해야 하는가?
- `201 Created`, `202 Accepted`, `204 No Content`, `409 Conflict`를 언제 쓰는가?
- 프로세스가 재시작되면 `asyncio.create_task()`로 만든 작업은 어떻게 되는가?
- Pydantic Schema와 SQLAlchemy Model을 왜 분리하는가?
- 사용자가 보낸 경로, 파일명, URL, Command를 어디까지 신뢰할 수 있는가?

ParseLab의 코드는 이 질문들에 대한 하나의 실용적인 답을 제공합니다. 동시에 현재
MVP의 한계도 함께 설명하므로, “동작하는 코드”와 “운영 가능한 코드”의 차이를 학습할
수 있습니다.

## 한눈에 보는 프로젝트 설계

ParseLab의 핵심 아이디어는 간단합니다.

> 동일한 문서를 여러 Parser로 실행하고, 서로 다른 결과를 공통 Canonical Format으로
> 변환한 뒤, 품질과 속도를 같은 기준으로 비교한다.

주요 용어는 다음과 같습니다.

| 용어 | 의미 | 예시 |
|---|---|---|
| Document | 사용자가 업로드한 원본 문서 | PDF, DOCX, TXT |
| Parser Connector | Parser를 실행하기 위한 등록 정보 | Synap HTTP, Docling Command |
| Parser Adapter | 서로 다른 Parser 호출 방식을 감싸는 Python 구현 | `SynapHttpAdapter` |
| Experiment | 하나의 문서를 여러 Parser로 비교하는 작업 묶음 | “계약서 Parser 비교” |
| Run | Experiment 안에서 Parser 하나를 실행한 단위 | Docling Run |
| Canonical Document | Parser마다 다른 결과를 비교 가능한 공통 구조로 바꾼 문서 | Page, Block, TableCell |
| Deidentification | 파싱 결과에서 개인정보를 탐지하고 마스킹하는 후속 단계 | Fasoo 또는 Mock Fasoo |
| Artifact | 실행 과정에서 생성된 실제 결과 파일 | `raw.json`, `output.md` |

전체 데이터 흐름은 다음과 같습니다.

```text
┌──────────────────────────────────────────────────────────────────┐
│ React                                                            │
│ 문서 업로드 · Parser 등록 · Experiment 실행 · Polling · 결과 비교 │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTP/JSON, multipart/form-data
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│ FastAPI                                                          │
│                                                                  │
│ Middleware → Router → Dependency → Service → Repository          │
│                                      │                           │
│                                      ├─ PostgreSQL               │
│                                      ├─ StorageService           │
│                                      └─ TaskManager              │
└──────────────────────────────────────┬───────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────┐
│ 실행 Pipeline                                                    │
│ Parser Adapter → Canonical 정규화 → Artifact 저장 → 비식별화      │
└──────────────────────┬──────────────────────────┬────────────────┘
                       │                          │
                       ▼                          ▼
              PostgreSQL 메타데이터       로컬 파일 저장소
              상태·지표·평가              원본·JSON·MD·TXT
```

이 구조에서 가장 중요한 원칙은 **HTTP 처리, 비즈니스 규칙, DB 접근, 외부 시스템
호출, 파일 저장을 서로 다른 책임으로 분리하는 것**입니다. 덕분에 Router를 바꾸지
않고 새 Parser를 추가하거나, 향후 로컬 저장소를 S3로 교체할 수 있습니다.

## Backend 계층과 각 계층의 책임

```text
backend/app/
├── main.py                 # FastAPI 생성, Middleware, Lifespan
├── api/
│   ├── dependencies.py     # DB, 인증 사용자, 저장소 의존성
│   └── v1/                 # HTTP Route와 상태 코드
├── schemas/                # Pydantic 요청·응답·Canonical 모델
├── services/               # 업무 규칙과 Transaction 경계
├── repositories/           # SQLAlchemy 조회문
├── db/
│   ├── models/             # 영속 데이터 모델
│   └── session.py          # Async Engine과 Session 생성
├── adapters/               # Parser·비식별화 외부 연동
├── normalizers/            # 외부 결과를 Canonical 구조로 변환
├── task_manager/           # 프로세스 내부 비동기 작업과 Pipeline
├── core/                   # 환경설정, 보안, 공통 예외
└── utils/                  # Config 검증과 Text Diff
```

| 계층 | 해야 하는 일 | 넣지 않아야 하는 일 | 대표 파일 |
|---|---|---|---|
| Router | 입력 선언, 의존성 요청, 상태 코드, 응답 모델 | 긴 업무 로직, 직접 SQL 작성 | [`experiments.py`](backend/app/api/v1/experiments.py) |
| Schema | 외부 데이터 검증과 직렬화 | DB Commit, 외부 API 호출 | [`experiment.py`](backend/app/schemas/experiment.py) |
| Service | 업무 규칙, 권한 확인, Transaction 조정 | HTTP Header 생성, FastAPI 전용 응답 | [`experiment_service.py`](backend/app/services/experiment_service.py) |
| Repository | 반복되는 조회와 영속성 접근 | HTTP 상태 코드 결정, 파일 저장 | [`experiment_repository.py`](backend/app/repositories/experiment_repository.py) |
| ORM Model | Table, Column, FK, 제약조건 | API 전용 표시 형식 | [`db/models`](backend/app/db/models) |
| Adapter | 외부 Parser 또는 비식별화 제품의 차이 흡수 | 사용자 권한, Experiment 생성 | [`adapters`](backend/app/adapters) |
| Storage | 안전한 경로 처리와 파일 읽기·쓰기 | Parser별 결과 해석 | [`storage_service.py`](backend/app/services/storage_service.py) |
| Task/Pipeline | 실행 순서, 상태 전이, 실패 격리 | HTTP 요청 객체에 의존 | [`pipeline.py`](backend/app/task_manager/pipeline.py) |

이 분리는 파일을 많이 만들기 위한 형식이 아닙니다. 변경 이유가 다른 코드를 분리해
테스트 범위와 장애 범위를 줄이기 위한 설계입니다. 예를 들어 Fasoo 응답 형식이
바뀌면 Adapter만 수정하고, Experiment 생성 규칙이나 HTTP Route는 그대로 유지하는
것이 목표입니다.

## 요청 한 건의 이동 경로

`POST /api/v1/experiments`를 예로 들면 다음 순서로 처리됩니다.

```text
1. Uvicorn이 HTTP 요청을 ASGI 메시지로 FastAPI에 전달
2. CORS Middleware가 Origin 관련 Header 처리
3. APIRouter가 Method와 Path로 Endpoint 선택
4. FastAPI가 Pydantic으로 JSON Body 검증
5. Dependency Graph 실행
   ├─ get_session()       → 요청 전용 AsyncSession
   ├─ get_current_user()  → Bearer JWT 검증 및 사용자 조회
   └─ get_storage()       → 재사용되는 StorageService
6. ExperimentService.create() 실행
7. 소유권·Parser·지원 확장자·Config 검증
8. Experiment와 Run을 하나의 Transaction으로 Commit
9. TaskManager에 각 Run 제출
10. 202 Accepted와 experiment_id 반환
11. React가 2초마다 Experiment 상태 조회
12. Pipeline이 별도 Session으로 Parser와 비식별화 실행
```

여기서 중요한 점은 HTTP 요청용 Session을 백그라운드 작업이 계속 사용하지 않는다는
것입니다. 요청이 끝나면 `get_session()`의 Context Manager가 Session을 닫습니다.
따라서 Pipeline은 [`async_session_factory`](backend/app/db/session.py)를 받아 작업
수명에 맞는 새 Session을 생성합니다.

이 원칙을 지키지 않으면 이미 닫힌 Session 사용, 동시에 같은 Session을 사용하는
문제, 예측하기 어려운 Transaction 상태가 발생할 수 있습니다. `AsyncSession`은
여러 Task가 동시에 공유하도록 설계된 객체가 아닙니다.

## FastAPI 핵심 개념을 이 프로젝트로 이해하기

### 1. 애플리케이션 생성과 Lifespan

[`main.py`](backend/app/main.py)는 애플리케이션의 조립 지점입니다.

```python
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)
```

`lifespan`은 서버 프로세스 시작과 종료에 맞춰 자원을 준비하고 정리합니다.

시작 시:

- 저장소 루트 디렉터리를 준비합니다.
- 로컬 개발 설정이면 Table을 자동 생성합니다.
- 재시작 전에 `RUNNING`이던 작업을 `INTERRUPTED`로 변경합니다.
- 최대 동시 실행 수를 적용한 `TaskManager`를 `app.state`에 등록합니다.

종료 시:

- 프로세스 내부 Task를 취소하고 기다립니다.
- SQLAlchemy Engine의 Connection Pool을 정리합니다.

전문가 관점에서 Lifespan은 단순 초기화 함수가 아닙니다. 애플리케이션이 소유한
자원의 수명을 명확히 표현하는 경계입니다. DB Engine, HTTP Client, Queue Consumer
같은 자원은 생성과 정리를 한 쌍으로 설계해야 합니다.

### 2. APIRouter와 API Versioning

[`api/v1/router.py`](backend/app/api/v1/router.py)는 모든 기능 Router를
`/api/v1` 아래에 조립합니다.

```python
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(documents.router)
api_router.include_router(experiments.router)
```

기능별 Router를 분리하면 다음 장점이 있습니다.

- 인증, 문서, Parser, Experiment의 변경 범위가 분리됩니다.
- OpenAPI 문서가 Tag별로 정리됩니다.
- `/api/v2`를 만들 때 기존 계약을 유지할 수 있습니다.
- 각 Router를 독립적으로 테스트하기 쉬워집니다.

Endpoint 함수는 가능한 한 얇게 유지합니다. HTTP 입력을 받고 Service를 호출한 뒤
응답하는 정도가 이상적입니다.

### 3. 타입 선언이 곧 입력 검증과 API 문서

FastAPI는 함수 Signature를 실행 계약으로 사용합니다.

```python
async def text_diff(
    experiment_id: UUID,
    base_run_id: UUID,
    normalize_whitespace: bool = Query(default=True),
    user: CurrentUser,
) -> TextDiffResponse:
    ...
```

이 선언만으로 FastAPI는 다음을 처리합니다.

- Path와 Query String을 Python 타입으로 변환
- 잘못된 UUID와 Boolean 입력을 `422`로 거절
- 필수값과 기본값 판단
- OpenAPI Schema 생성
- Swagger UI 입력 화면 생성

요청·응답 모델은 [`schemas`](backend/app/schemas)에, DB 모델은
[`db/models`](backend/app/db/models)에 따로 둡니다. API 계약은 Client와의 약속이고
ORM 모델은 DB 저장 구조이므로 변경 이유가 다르기 때문입니다.

`response_model`은 문서화 기능만 제공하는 것이 아닙니다. 반환 데이터를 선언한
Schema로 검증·직렬화하고, Schema에 없는 내부 필드가 응답에 섞이는 것을 막습니다.
예를 들어 `User` ORM 모델의 `password_hash`는 `UserResponse`에 없으므로 노출되지
않습니다.

### 4. Dependency Injection

[`dependencies.py`](backend/app/api/dependencies.py)는 반복되는 준비 작업을 타입
별칭으로 표현합니다.

```python
SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[StorageService, Depends(get_storage)]
CurrentUser = Annotated[User, Depends(get_current_user)]
```

Endpoint에서 `user: CurrentUser`를 선언하면 FastAPI는 다음 Dependency Graph를
자동으로 해결합니다.

```text
CurrentUser
├─ HTTPBearer: Authorization Header 읽기
└─ SessionDep
   └─ get_session: AsyncSession 생성과 종료
```

Dependency Injection의 핵심 가치는 코드를 짧게 만드는 것이 아니라, **자원 생성과
정리, 인증, 공통 검증을 Endpoint 밖으로 이동하고 테스트에서 교체할 수 있게 하는
것**입니다. 테스트에서는 `app.dependency_overrides`를 사용해 PostgreSQL Session을
임시 SQLite Session으로 바꾸는 식의 구성이 가능합니다.

`get_storage()`에는 `lru_cache`가 적용되어 프로세스 안에서 같은
`StorageService`를 재사용합니다. 반대로 DB Session은 요청 사이에 공유하면 안 되므로
요청마다 새로 생성합니다. 어떤 Dependency를 Cache할지는 객체의 상태와 수명에 따라
결정해야 합니다.

### 5. Async SQLAlchemy와 Session 수명

[`db/session.py`](backend/app/db/session.py)의 핵심 구성은 다음과 같습니다.

```python
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
```

- `Engine`은 프로세스 단위로 Connection Pool을 관리합니다.
- `Session`은 하나의 작업 단위와 ORM 상태를 관리합니다.
- `pool_pre_ping=True`는 Pool에서 꺼낸 연결이 유효한지 사용 전에 확인합니다.
- `expire_on_commit=False`는 Commit 직후 ORM 속성을 읽기 위해 불필요한 재조회가
  발생하는 것을 줄입니다.

중요한 규칙은 다음과 같습니다.

- 하나의 `AsyncSession`을 여러 동시 Task에서 공유하지 않습니다.
- Repository가 제멋대로 Commit하지 않고 Service가 업무 단위의 Commit 시점을
  결정합니다.
- 외부 Parser를 수 분 동안 기다리는 동안 DB Transaction을 계속 열어두지 않는 것을
  목표로 합니다.
- 실패할 수 있는 단계 사이에는 복구 가능한 영속성 경계를 둡니다.

현재 Service는 필요한 지점에서 명시적으로 `commit()`합니다. 다만 Pipeline은
`RUNNING`을 Commit한 뒤 같은 Session으로 Connector와 Document를 조회합니다.
SQLAlchemy의 `autobegin` 때문에 이 조회가 새 읽기 Transaction을 시작하고, 외부
Parser 호출이 끝날 때까지 Session Context가 유지될 수 있습니다. 운영 수준으로
개선하려면 필요한 값을 먼저 Snapshot으로 복사한 뒤 Session과 Transaction을 닫고
외부 호출을 실행하고, 결과 저장용 Session을 새로 여는 구조가 더 안전합니다.

더 복잡한 업무에서는 `async with session.begin():`을 사용한 Unit of Work, 재시도
전략, Deadlock 처리, Idempotency까지 함께 설계해야 합니다.

### 6. Service와 Repository

Router에서 SQL을 직접 작성하면 처음에는 빠르지만 인증, 상태 검사, Commit 규칙이
Endpoint마다 복제됩니다. ParseLab은 다음과 같이 책임을 나눕니다.

```text
Router
  “HTTP 요청을 어떤 Service에 전달할까?”
        │
        ▼
Service
  “이 사용자가 이 작업을 수행할 수 있는가?”
  “어떤 순서로 검증하고 언제 Commit할까?”
        │
        ▼
Repository
  “이 조건으로 어떤 SQLAlchemy Query를 실행할까?”
```

Repository Pattern을 모든 단순 조회에 기계적으로 적용할 필요는 없습니다. 중요한
기준은 조회가 재사용되는지, 업무 의미가 있는지, 테스트 대역이 필요한지입니다.
ParseLab의 Service 일부가 간단한 `session.get()`을 직접 사용하는 이유도 이
균형점에 있습니다.

### 7. HTTP 상태 코드와 비동기 작업

Experiment 생성은 `201`이 아니라 `202 Accepted`를 반환합니다.

```python
@router.post(
    "",
    response_model=ExperimentCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
```

DB에 Experiment와 Run은 생성됐지만 Parser 실행은 아직 끝나지 않았기 때문입니다.
Client는 응답을 작업 완료로 해석하면 안 되며, 반환된 ID로 상태를 조회해야 합니다.

이 프로젝트에서 사용하는 대표 상태 코드는 다음과 같습니다.

| 상태 코드 | 의미 | 사용 예 |
|---|---|---|
| `200 OK` | 조회·수정이 정상 완료됨 | 로그인, 목록, 평가 수정 |
| `201 Created` | 새 Resource 생성 완료 | 회원가입, 문서, Parser |
| `202 Accepted` | 요청은 접수됐고 처리는 계속 진행됨 | Experiment 생성 |
| `204 No Content` | 처리 성공, 응답 Body 없음 | Parser 비활성화, Preset 삭제 |
| `401 Unauthorized` | 인증 정보가 없거나 유효하지 않음 | JWT 누락·만료 |
| `403 Forbidden` | 인증됐지만 권한이 없음 | 일반 사용자의 관리자 기능 |
| `404 Not Found` | Resource가 없거나 소유하지 않음 | 다른 사용자의 Run 조회 |
| `409 Conflict` | 현재 Resource 상태와 요청이 충돌함 | 실행 중이 아닌 Run 취소 |
| `413 Content Too Large` | 업로드 크기 제한 초과 | 대용량 문서 |
| `415 Unsupported Media Type` | 지원하지 않는 파일 형식 | 허용되지 않은 확장자 |
| `422 Unprocessable Content` | 타입·Schema 또는 업무 검증 실패 | 잘못된 UUID, Config |

다른 사용자의 Resource에도 `404`를 반환하는 것은 해당 ID의 존재 여부를 노출하지
않기 위한 일반적인 보안 선택입니다.

### 8. 공통 오류 계약

업무 오류는 [`AppError`](backend/app/core/exceptions.py)로 표현합니다.

```json
{
  "error": {
    "code": "PARSER_DISABLED",
    "message": "Parser connector is disabled.",
    "details": {}
  }
}
```

`code`는 Frontend가 분기할 수 있는 안정적인 값이고, `message`는 사람이 읽는
설명입니다. HTTP 상태 코드만으로는 “Parser가 없음”과 “Parser가 비활성화됨” 같은
세부 원인을 충분히 표현하기 어렵습니다.

현재 Pydantic 입력 검증 오류는 FastAPI 기본 `422` 형식을 사용하고, `AppError`만
위 형식을 사용합니다. 운영 API에서 완전히 일관된 오류 계약이 필요하다면
`RequestValidationError`, 예상하지 못한 Exception, Request ID까지 공통 Handler로
통합하는 것이 다음 단계입니다.

### 9. 이벤트 루프와 Blocking I/O

`async def`라고 해서 함수 내부의 모든 코드가 자동으로 비동기가 되는 것은 아닙니다.
일반 `Path.write_text()`, 큰 파일 Hash 계산, CPU 집약 작업을 Event Loop에서 직접
실행하면 다른 요청까지 멈출 수 있습니다.

[`StorageService`](backend/app/services/storage_service.py)는 동기 파일 작업을
`asyncio.to_thread()`로 넘깁니다.

```python
await asyncio.to_thread(path.write_text, content, "utf-8")
```

판단 기준은 다음과 같습니다.

- HTTP, asyncpg처럼 비동기 API가 있으면 해당 API를 `await`합니다.
- 짧은 동기 파일 작업은 `to_thread()`로 Event Loop 밖에서 실행합니다.
- 무거운 CPU 작업은 Thread가 아니라 Process Pool 또는 별도 Worker를 검토합니다.
- 외부 실행에는 반드시 Timeout과 취소 전략을 둡니다.

### 10. TaskManager와 `asyncio.create_task()`

[`TaskManager`](backend/app/task_manager/manager.py)는 Run ID와 `asyncio.Task`를
연결하고 `Semaphore`로 동시 실행 수를 제한합니다.

```text
submit(run_id)
→ asyncio.create_task()
→ Semaphore 자리 대기
→ Pipeline 실행
→ 완료 또는 취소
→ Registry에서 제거
```

FastAPI의 `BackgroundTasks`도 응답 뒤에 함수를 실행할 수 있지만, ParseLab은 Run별
취소, 실행 여부 확인, 동시성 제한이 필요하므로 별도 TaskManager를 사용합니다.

다만 둘 다 **프로세스 내부 실행**이라는 한계가 있습니다.

- 서버가 종료되면 Task도 사라집니다.
- 여러 Uvicorn Worker를 사용하면 각 Worker의 Registry와 Semaphore가 따로 생깁니다.
- `MAX_CONCURRENT_RUNS=2`는 Worker가 3개면 전체 최대 6개가 될 수 있습니다.
- DB Commit 직후 Task 제출 전에 프로세스가 죽으면 `PENDING` Run이 남을 수 있습니다.

따라서 현재 MVP는 Uvicorn Worker 1개를 전제로 합니다. 운영 규모로 확장할 때는
Durable Queue, 별도 Worker, Outbox Pattern, Lease/Heartbeat, Idempotent 실행을
도입해야 합니다. Redis/Celery가 무조건 정답인 것은 아니지만, 작업을 프로세스
수명과 분리할 필요가 생기는 시점을 판단할 수 있어야 합니다.

## Transaction과 상태 전이 설계

### Experiment 생성 Transaction

Experiment 생성 시 Service는 다음 순서를 지킵니다.

```text
문서 소유권 확인
→ Parser 중복·활성·지원 확장자 확인
→ Preset과 Override 병합
→ JSON Schema 검증
→ Experiment INSERT
→ flush()로 ID 확보
→ Parser별 ExperimentRun INSERT
→ commit()
→ TaskManager submit()
```

`flush()`는 SQL을 DB에 보내 ID와 제약조건을 확인하지만 Transaction을 끝내지는
않습니다. 따라서 뒤의 Run 생성이 실패하면 Experiment까지 함께 Rollback할 수
있습니다. `commit()` 이후에만 백그라운드 Task를 제출해, 아직 확정되지 않은 Run을
Task가 조회하는 경쟁 상태를 방지합니다.

### Parser 상태 머신

```text
                  ┌─────────────┐
                  │   PENDING   │
                  └──────┬──────┘
                         │ 실행 시작
                         ▼
                  ┌─────────────┐
             ┌────│   RUNNING   │────┐
             │    └─────────────┘    │
             │ 성공                  │ 오류
             ▼                       ▼
      ┌─────────────┐         ┌─────────────┐
      │  SUCCEEDED  │         │   FAILED    │
      └─────────────┘         └──────┬──────┘
                                    │ 재실행
                                    └──→ PENDING

PENDING 또는 RUNNING에서 취소·서버 재시작 → INTERRUPTED → 재실행 → PENDING
```

Pipeline은 외부 Parser를 호출하기 전에 `RUNNING`을 Commit합니다. 그래서 Frontend
Polling과 다른 프로세스가 실제 상태를 볼 수 있습니다. 성공 시 Artifact 경로와
운영 지표를 저장하고 `SUCCEEDED`를 Commit합니다.

여기서 `RUNNING` Commit은 이전 쓰기 Transaction을 끝낸다는 의미이지, 이후
Transaction이 절대 열리지 않는다는 뜻은 아닙니다. 같은 Session에서 ORM 조회를
수행하면 `autobegin`으로 새 Transaction이 시작될 수 있습니다. 이 차이를 이해하고
외부 I/O 구간과 DB Transaction 구간을 물리적으로 분리하는 것이 고급 개선
과제입니다.

### Parsing과 비식별화의 실패 격리

비식별화는 Parsing의 후속 단계이지만 같은 성공·실패 값으로 합치지 않습니다.

```text
parse_status                  deidentification_status
────────────                  ─────────────────────────
SUCCEEDED                     SUCCEEDED
SUCCEEDED                     FAILED
FAILED                        INTERRUPTED
SUCCEEDED                     NOT_REQUESTED
```

Parser 결과를 성공적으로 얻은 뒤 Fasoo 호출이 실패했다고 해서 Parser 결과까지
Rollback하면 비싼 작업을 다시 실행해야 하고 원인도 불명확해집니다. 그래서
[`pipeline.py`](backend/app/task_manager/pipeline.py)는 다음 영속성 경계를 둡니다.

```text
Parser 실행·정규화·저장
→ parse_status=SUCCEEDED
→ COMMIT                 ← Parser 결과 보존
→ 비식별화 실행
→ deidentification_status 기록
→ COMMIT
```

비식별화만 실패한 Run은 기존 Parser Artifact를 재사용해 비식별화 단계만 다시
실행합니다. 이것이 단계별 상태와 재시도를 따로 설계한 이유입니다.

## 데이터베이스 설계

PostgreSQL은 검색과 상태 관리에 적합한 메타데이터를 저장하고, 큰 Artifact는 파일
저장소에 둡니다.

```text
User
├─ Document
│  └─ Experiment
│     └─ ExperimentRun
│        ├─ RunResult
│        ├─ DeidentificationResult
│        └─ ManualEvaluation
└─ ParserConnector
   └─ ParserPreset
```

| Table | 역할 | 중요한 설계 |
|---|---|---|
| `users` | 계정과 역할 | Email Unique, Password Hash만 저장 |
| `documents` | 원본 문서 메타데이터 | SHA-256, 크기, 상대 저장 경로 |
| `parser_connectors` | 실행 가능한 Parser 등록 정보 | Adapter Key, 실행 방식, 기본 Config |
| `parser_presets` | 재사용 Config | Connector별 설정 묶음 |
| `experiments` | 비교 작업의 상위 단위 | 문서, 생성자, 비식별화 여부 |
| `experiment_runs` | Parser별 실행 상태 | Parser·Config Snapshot, 상태, 시간, 오류 |
| `run_results` | Parser 결과 요약 | Artifact 경로, Page·Block·Table 지표 |
| `deidentification_results` | 비식별화 결과 요약 | Provider, 입력 종류, 마스킹 수 |
| `manual_evaluations` | 사용자 수동 평가 | Run·평가자 Unique, 점수 1~5 Check |

모든 주요 PK는 UUID입니다. 외부 API에 순차 정수 ID를 노출하지 않고 여러 생성
주체에서 충돌 없이 ID를 만들기 쉽다는 장점이 있습니다. 다만 UUID Index 크기와
정렬 지역성 비용이 있으므로 대규모 환경에서는 UUIDv7 같은 선택도 검토할 수
있습니다.

`ExperimentRun`에는 `parser_snapshot`과 `config_snapshot`을 저장합니다. Parser
등록 정보가 나중에 수정되어도 과거 실험이 어떤 이름, Version, Config로 실행됐는지
재현하기 위해서입니다. 실행 이력이 중요한 시스템에서는 “현재 설정을 FK로
참조하는 것”만으로 충분하지 않습니다.

SQLAlchemy Model은 `Mapped[...]`와 `mapped_column()`을 사용하는 2.x Typed
Declarative Style입니다. 공통 UUID와 생성·수정 시각은 Mixin으로 재사용하며,
Alembic이 안정적인 Constraint 이름을 만들 수 있도록 Naming Convention을
설정했습니다.

로컬 개발에서는 편의를 위해 `AUTO_CREATE_TABLES=true`를 지원하지만, 운영에서는
반드시 `false`로 두고 Alembic Migration을 배포 과정에서 명시적으로 적용해야
합니다. `create_all()`은 기존 Column 변경이나 데이터 Migration 이력을 관리하지
못합니다.

## PostgreSQL과 파일 저장소를 나눈 이유

원본 PDF와 큰 JSON을 DB Row에 직접 넣으면 Backup, Query, Connection 사용량이
무거워질 수 있습니다. 반대로 모든 정보를 파일명에만 의존하면 상태 검색과 권한
검사가 어렵습니다.

따라서 역할을 다음처럼 나눕니다.

| PostgreSQL | 파일 저장소 |
|---|---|
| 사용자와 소유권 | 원본 문서 |
| 상태와 오류 코드 | Parser Raw 결과 |
| 실행 시간과 개수 지표 | Canonical JSON |
| Artifact 상대 경로 | Markdown과 Text |
| 수동 평가 | 비식별화 결과와 오류 로그 |

DB와 파일 저장소를 함께 사용하는 구조에는 원자성 문제가 있습니다. 파일 저장은
성공했지만 DB Commit이 실패하거나 그 반대가 발생할 수 있습니다. 현재 MVP는
상태와 재실행으로 복구하지만, 운영 단계에서는 임시 파일 후 Atomic Rename,
Garbage Collector, Artifact 생성 상태, Checksum 검증을 추가하는 것이 좋습니다.

## Adapter와 Canonical Document

### Adapter가 필요한 이유

Parser마다 실행 방식과 응답 구조가 다릅니다.

```text
BUILTIN  → 현재 Python 프로세스에서 호출
HTTP     → 사내 또는 외부 REST API 호출
COMMAND  → 설치된 CLI를 안전한 subprocess로 실행
```

플랫폼 전체가 이 차이를 알게 만들면 Parser를 추가할 때 Service, DB, 화면을 모두
수정해야 합니다. 대신 모든 Parser가 같은 인터페이스를 구현합니다.

```python
class ParserAdapter(ABC):
    async def health_check(self) -> dict: ...
    async def parse(self, input_path, output_dir, config) -> ParserExecutionResult: ...
    async def normalize(self, execution_result, document_id, run_id) -> CanonicalDocument: ...
```

Registry는 DB의 `adapter_key`를 실제 Class로 바꿉니다. 임의의 Python Import 경로를
DB에서 실행하지 않고 명시적인 허용 목록만 사용하므로 보안과 배포 예측 가능성도
높아집니다.

### Canonical Format

[`canonical_document.py`](backend/app/schemas/canonical_document.py)의 구조는 다음과
같습니다.

```text
CanonicalDocument
├─ schema_version
├─ document_id, run_id
├─ parser_name, parser_version, parser_config
├─ full_text
├─ markdown
├─ pages[]
│  ├─ page_number, width, height, text
│  └─ blocks[]
│     ├─ type, text, bbox, confidence, html
│     └─ cells[]
│        ├─ row, column
│        ├─ row_span, column_span
│        └─ text, bbox
└─ metadata
```

정규화 덕분에 비교 화면은 Synap, Docling, Mock Parser의 원본 응답 구조를 몰라도
됩니다. Raw 결과는 디버깅과 재현을 위해 그대로 보존하고, 비교 기능은 Canonical
결과를 사용합니다.

새 Parser를 추가하는 순서는 다음과 같습니다.

1. `ParserAdapter`를 상속한 Adapter를 작성합니다.
2. `health_check()`, `parse()`, `normalize()`를 구현합니다.
3. `PARSER_ADAPTERS` Registry에 안전한 `adapter_key`를 등록합니다.
4. Connector의 `config_schema`로 설정 JSON을 검증합니다.
5. 정상 응답, Timeout, 잘못된 응답, 취소를 단위 테스트합니다.
6. 같은 Fixture를 기존 Parser와 실행해 Canonical 결과를 비교합니다.

Parser별 특수 필드를 Canonical 최상위에 계속 추가하는 것은 피합니다. 공통 의미가
있으면 Schema Version을 올려 정식 필드로 설계하고, Parser 전용 정보는
`metadata` 또는 Block의 `attributes`에 둡니다.

## 보안 설계와 운영 전 보강점

현재 구현된 방어:

- 비밀번호 원문 대신 권장 Password Hash를 저장합니다.
- JWT의 서명과 만료 시각을 검증합니다.
- 모든 사용자 Resource 조회에서 소유권을 확인합니다.
- 업로드 확장자, MIME Type, 최대 크기를 검증합니다.
- 저장 파일명에서 위험한 문자를 제거합니다.
- `DATA_ROOT` 밖으로 나가는 경로 이탈을 차단합니다.
- Command는 문자열 Shell이 아니라 인수 배열과
  `asyncio.create_subprocess_exec()`로 실행합니다.
- 실행 가능한 Command와 Template 변수를 허용 목록으로 제한합니다.
- Parser와 비식별화 호출에 Timeout을 적용합니다.
- API Key와 문서 원문을 애플리케이션 로그에 남기지 않습니다.
- CORS Origin을 환경변수의 명시적 목록으로 제한합니다.

운영 배포 전에 보강할 항목:

- 기본 `JWT_SECRET`, DB Password를 Secret Manager 값으로 교체
- HTTPS 강제와 Secure Cookie 또는 강화된 Token 저장 전략 검토
- Refresh Token 회전, 로그아웃·폐기 전략
- 로그인과 업로드 Rate Limit
- MIME 문자열뿐 아니라 Magic Byte 검사와 악성 파일 검사
- Generic HTTP Parser 목적지의 Host/IP 허용 목록으로 SSRF 방지
- 관리자 변경 Audit Log
- Request ID, 구조화 로그, Metric, Trace
- 예상하지 못한 오류에서 내부 정보가 노출되지 않는 공통 Handler
- DB·Artifact Backup과 복구 훈련
- Dependency 취약점 검사와 이미지 최소 권한 실행

Frontend는 현재 JWT를 `localStorage`에 저장하므로 XSS가 발생하면 Token이 노출될 수
있습니다. 사내 위협 모델과 배포 구조에 따라 CSP 강화, 짧은 만료 시간, Refresh
Token 회전, `HttpOnly`·`Secure` Cookie 사용을 검토해야 합니다.

## API 전체 지도

모든 업무 API Prefix는 `/api/v1`이며 `/health`만 별도입니다.

| 영역 | Method와 Path | 설명 |
|---|---|---|
| 상태 | `GET /health` | 프로세스 상태 확인 |
| 인증 | `POST /auth/signup` | 회원가입, 첫 사용자는 ADMIN |
| 인증 | `POST /auth/login` | JWT Access Token 발급 |
| 사용자 | `GET /users/me` | 현재 사용자 조회 |
| 문서 | `POST /documents` | `multipart/form-data` 업로드 |
| 문서 | `GET /documents` | 소유 문서 목록 |
| 문서 | `GET /documents/{id}` | 문서 메타데이터 |
| 문서 | `GET /documents/{id}/download` | 원본 다운로드 |
| Parser | `GET /parsers` | 활성 Parser 목록 |
| Parser | `POST /parsers` | Parser Connector 등록 |
| Parser | `GET /parsers/{id}` | Parser 상세 |
| Parser | `PATCH /parsers/{id}` | 일부 필드 수정 |
| Parser | `DELETE /parsers/{id}` | 실제 삭제 대신 비활성화 |
| Parser | `POST /parsers/{id}/health-check` | 연결 상태 확인 |
| Preset | `POST /parsers/{id}/presets` | Config Preset 생성 |
| Preset | `GET /parsers/{id}/presets` | Preset 목록 |
| Preset | `PATCH /parser-presets/{id}` | Preset 수정 |
| Preset | `DELETE /parser-presets/{id}` | Preset 삭제 |
| 실험 | `POST /experiments` | 비교 실험 접수, `202` |
| 실험 | `GET /experiments` | 내 실험 목록 |
| 실험 | `GET /experiments/{id}` | Run을 포함한 상세 상태 |
| 비교 | `GET /experiments/{id}/comparison` | 결과와 운영 지표 |
| 비교 | `GET /experiments/{id}/text-diff` | 두 Run의 Text Diff |
| 비교 | `GET /experiments/{id}/export.csv` | 비교 결과 CSV |
| Run | `GET /runs/{id}` | Run 상태 |
| Run | `POST /runs/{id}/retry` | 실패·중단 단계 재실행 |
| Run | `POST /runs/{id}/cancel` | 대기·실행 작업 취소 |
| Artifact | `GET /runs/{id}/raw` | 원본 Parser JSON |
| Artifact | `GET /runs/{id}/canonical` | Canonical JSON |
| Artifact | `GET /runs/{id}/markdown` | Markdown |
| Artifact | `GET /runs/{id}/text` | Text |
| Artifact | `GET /runs/{id}/deidentified` | 비식별화 JSON |
| 평가 | `GET /runs/{id}/evaluation` | 내 수동 평가 |
| 평가 | `PUT /runs/{id}/evaluation` | 평가 생성 또는 전체 갱신 |

실행 중인 서버의 정확한 Schema는 Swagger UI
<http://localhost:8000/docs>와 OpenAPI JSON
<http://localhost:8000/openapi.json>에서 확인할 수 있습니다. README보다 OpenAPI가
현재 코드의 API 계약에 더 가까운 Source of Truth입니다.

## 테스트 전략

테스트는 “함수 개수”가 아니라 장애 위험에 따라 나눕니다.

| 종류 | 검증 대상 | 예시 |
|---|---|---|
| 단위 테스트 | 순수 규칙과 Adapter 경계 | Config 병합, 상태 계산, Text Diff |
| Adapter 테스트 | 외부 연동 계약 | HTTP 성공·Timeout, Command 허용 목록 |
| Storage 테스트 | 경로와 Artifact | 경로 이탈 차단, 결과 저장 |
| TaskManager 테스트 | 동시성·취소 | Semaphore, Registry 정리 |
| 통합 테스트 | 계층을 통과하는 전체 흐름 | 가입부터 CSV 다운로드까지 |

특히 다음 실패 경로를 성공 경로만큼 중요하게 다룹니다.

- Parser Timeout과 비정상 응답
- Command 실패와 허용되지 않은 실행파일
- 서버 중단 상태
- 비식별화 실패 후 Parsing 성공 보존
- 존재하지 않거나 다른 사용자가 소유한 Resource
- 잘못된 Config Schema

운영 DB는 PostgreSQL이지만 현재 통합 테스트는 빠르고 독립적인 실행을 위해 임시
SQLite를 사용합니다. 이 방식은 업무 흐름 검증에는 유용하지만 PostgreSQL의 Enum,
JSON, Lock, 격리 수준, SQL 문법 차이를 모두 잡지는 못합니다. 전문가 수준의
Test Suite로 확장하려면 Docker 기반 PostgreSQL 통합 테스트도 별도 계층으로
추가해야 합니다.

## 현재 MVP의 의도적인 한계

다음 항목은 실수로 빠진 것이 아니라 복잡도를 통제하기 위해 제외한 범위입니다.

- Redis, Celery, Kafka 같은 외부 Queue
- 서버 재시작 후 자동 작업 복구
- 여러 Backend Worker에 걸친 전역 동시성 제어
- S3 또는 MinIO Artifact 저장소
- Refresh Token과 조직 단위 멀티테넌시
- WebSocket 또는 Server-Sent Events
- Parser Worker의 별도 배포와 자원 Scheduling
- 완전한 Audit Log와 관측 가능성 Stack
- Ground Truth 기반 자동 품질 점수

전문가의 중요한 능력은 모든 기술을 넣는 것이 아니라 현재 요구사항에 필요한
복잡도만 선택하고, 확장 시 깨지는 경계를 명확히 기록하는 것입니다.

## FastAPI 전문가 학습 로드맵

### 1단계: 요청과 응답을 정확히 이해하기

읽을 파일:

1. [`main.py`](backend/app/main.py)
2. [`api/v1/router.py`](backend/app/api/v1/router.py)
3. [`api/v1/auth.py`](backend/app/api/v1/auth.py)
4. [`schemas/auth.py`](backend/app/schemas/auth.py)

직접 해볼 것:

- `/docs`에서 정상 요청과 잘못된 Email, 짧은 Password를 각각 보냅니다.
- `response_model`에서 필드 하나를 제거하고 응답이 어떻게 달라지는지 확인합니다.
- Path, Query, Body, Header 값이 OpenAPI에 어떻게 표현되는지 비교합니다.

도달 기준:

- FastAPI가 함수 Signature에서 Dependency Graph와 OpenAPI를 만드는 과정을 설명할
  수 있습니다.
- `422`가 발생하는 시점과 업무 오류 `409`가 발생하는 시점을 구분할 수 있습니다.

### 2단계: Dependency와 인증

읽을 파일:

1. [`api/dependencies.py`](backend/app/api/dependencies.py)
2. [`core/security.py`](backend/app/core/security.py)
3. [`services/auth_service.py`](backend/app/services/auth_service.py)

직접 해볼 것:

- 인증이 필요한 테스트에서 `dependency_overrides`로 가짜 사용자를 주입합니다.
- ADMIN 전용 Dependency를 별도로 만들어 Parser 변경 Endpoint에 적용합니다.
- 만료된 Token, 잘못된 서명, 비활성 사용자의 응답 차이를 테스트합니다.

도달 기준:

- 요청 범위 Dependency와 프로세스 범위 Singleton의 차이를 설명할 수 있습니다.
- 인증과 권한 부여가 왜 다른 단계인지 설명할 수 있습니다.

### 3단계: Async DB와 Transaction

읽을 파일:

1. [`db/session.py`](backend/app/db/session.py)
2. [`repositories`](backend/app/repositories)
3. [`services/experiment_service.py`](backend/app/services/experiment_service.py)
4. [`task_manager/pipeline.py`](backend/app/task_manager/pipeline.py)

직접 해볼 것:

- Experiment 생성 중 두 번째 Parser 검증을 실패시켜 첫 INSERT가 Rollback되는지
  확인합니다.
- Parser 실행 전후의 Commit을 옮겼을 때 Polling 상태와 DB 연결 사용 시간이 어떻게
  달라지는지 관찰합니다.
- 동시에 같은 Run을 두 번 재실행하는 경쟁 조건 테스트를 작성합니다.

도달 기준:

- `flush`, `commit`, `refresh`, `rollback`의 차이를 설명할 수 있습니다.
- 긴 외부 I/O 동안 Transaction을 열어두면 안 되는 이유를 설명할 수 있습니다.
- Lost Update, Unique Constraint 경쟁, Idempotency가 필요한 지점을 찾을 수 있습니다.

### 4단계: 비동기 실행과 장애 복구

읽을 파일:

1. [`task_manager/manager.py`](backend/app/task_manager/manager.py)
2. [`task_manager/pipeline.py`](backend/app/task_manager/pipeline.py)
3. [`main.py`](backend/app/main.py)의 Lifespan

직접 해볼 것:

- `MAX_CONCURRENT_RUNS=1`로 바꾸고 여러 Run의 상태 전이를 관찰합니다.
- 실행 중 Backend를 종료하고 재시작해 `INTERRUPTED` 전환을 확인합니다.
- 같은 Run의 중복 제출, 취소 직후 재실행, Timeout 경계 테스트를 추가합니다.
- `PENDING` Run Scanner 또는 DB Lease Prototype을 설계합니다.

도달 기준:

- Coroutine, Task, Event Loop, Semaphore, Cancellation을 구분할 수 있습니다.
- In-Process Background Task와 Durable Job Queue의 차이를 설명할 수 있습니다.

### 5단계: 외부 연동과 보안

읽을 파일:

1. [`adapters/parsers`](backend/app/adapters/parsers)
2. [`adapters/deidentifiers`](backend/app/adapters/deidentifiers)
3. [`services/storage_service.py`](backend/app/services/storage_service.py)
4. [`utils/config_validation.py`](backend/app/utils/config_validation.py)

직접 해볼 것:

- 새 Mock Adapter를 하나 추가하되 기존 Service와 Router는 수정하지 않습니다.
- HTTP Adapter의 Retry 가능한 오류와 불가능한 오류를 분리합니다.
- 파일명, 경로 이탈, 잘못된 MIME, 거대한 파일에 대한 보안 테스트를 추가합니다.
- Generic HTTP의 내부 IP 접근을 차단하는 URL Policy를 설계합니다.

도달 기준:

- Timeout, Retry, Backoff, Circuit Breaker, Idempotency의 적용 조건을 구분할 수
  있습니다.
- 외부 입력을 신뢰 경계별로 검증할 수 있습니다.

### 6단계: 운영 가능한 API로 확장

추천 실습:

- `RequestValidationError`를 공통 오류 규약으로 변환
- Request ID Middleware와 구조화 JSON Log
- Prometheus용 요청 시간·Run 시간·실패 수 Metric
- PostgreSQL 기반 통합 테스트
- Alembic Migration CI 검사
- Readiness와 Liveness 상태 API 분리
- Outbox Pattern을 이용한 작업 제출
- S3 호환 `StorageService` 구현
- Cursor Pagination과 목록 검색
- OpenTelemetry Trace로 HTTP 요청과 Parser 호출 연결

완료 기준은 기능을 많이 추가하는 것이 아닙니다. 각 기능에 대해 실패 모드, 자원
수명, Transaction 경계, 보안 영향, 테스트 방법을 먼저 설명하고 구현할 수 있다면
전문가 수준에 가까워진 것입니다.

## 코드 리뷰 때 사용할 전문가 체크리스트

새 Endpoint나 기능을 추가할 때 다음 항목을 확인합니다.

- 입력 타입과 길이, 허용값이 Schema에 선언되어 있는가?
- 인증과 Resource 소유권을 모두 확인하는가?
- 올바른 HTTP 상태 코드와 안정적인 오류 코드를 사용하는가?
- Router가 업무 로직과 SQL로 비대해지지 않았는가?
- DB Commit 범위가 하나의 업무 단위와 일치하는가?
- 외부 I/O 동안 불필요한 DB Transaction을 열어두지 않는가?
- Blocking I/O가 Event Loop에서 실행되지 않는가?
- Timeout, 취소, 부분 실패 후 상태가 일관적인가?
- 재요청이나 중복 실행에도 데이터가 망가지지 않는가?
- 사용자 입력이 파일 경로, URL, Command로 안전하게 전달되는가?
- Secret과 개인정보가 Log 또는 오류 응답에 포함되지 않는가?
- 성공 경로뿐 아니라 실패·경쟁·재시작 경로 테스트가 있는가?
- Migration과 이전 Version Client에 미치는 영향을 검토했는가?
- 운영자가 장애 원인을 찾을 Log, Metric, Trace가 있는가?

## 가장 빠른 실행

Docker Desktop이 실행 중인 상태에서:

```bash
cp .env.example .env
docker compose up --build
```

브라우저에서 <http://localhost:5173>을 열고 **관리자 계정 만들기**를 선택합니다.
첫 계정이 만들어질 때 다음 Mock Parser가 함께 등록됩니다.

1. `Mock Standard`: UTF-8 텍스트 구조 유지
2. `Mock Line Reader`: 줄 번호를 붙여 비교 가능한 차이 생성

이미 5432, 8000 또는 5173 포트를 사용 중이면 `.env`에서 포트를 변경할 수 있습니다.

```env
POSTGRES_PORT=55432
BACKEND_PORT=18000
FRONTEND_PORT=15173
VITE_API_URL=http://localhost:18000/api/v1
CORS_ORIGINS=http://localhost:15173
```

`VITE_API_URL`은 Frontend 빌드 시점 값이므로 변경 후 Frontend 이미지를 다시 빌드합니다.

Command Parser에서 실행 가능한 바이너리는 환경변수로 제한합니다.

```env
COMMAND_ALLOWED_EXECUTABLES=docling,uv,docker
```

허용되는 Command Template 변수는 `{input_path}`, `{output_dir}`, `{config_path}`뿐이며
명령은 `asyncio.create_subprocess_exec()`로 실행됩니다.

기본 비식별화 구현은 외부 서버가 필요 없는 Mock Fasoo입니다.

```env
FASOO_ENABLED=false
FASOO_INPUT_TYPE=TEXT
```

실제 Fasoo HTTP API를 사용하려면 다음 값을 설정합니다.

```env
FASOO_ENABLED=true
FASOO_BASE_URL=https://intra-dev.agentone.kr:18443
FASOO_TIMEOUT_SECONDS=300
FASOO_ARTIFACT_WAIT_SECONDS=5
FASOO_DETECT_PATH=/piiapi/detect/system/path
FASOO_CONFIGURATION_PATH=/piiapi/configuration
NAS_MOUNT_PATH=/app/data/dwp_comp
FASOO_NAS_PATH=/dwp_comp
FASOO_WORK_SUBDIR=parselab
FASOO_PATTERNS=8352e3cefcf841b8ae8eacbafc9dc2e8,470f4ac178d948f389d848e705306ddd,75a718ffe4d646008c606b0578ad2e78,68502af4bf7d4274997d3698243a7b69
FASOO_LABELS=SS_BRAND,AD_METRO,AD_CITY,AD_ADDRESS,AD_BRAND,AD_DETAIL,AD_POSTAL
FASOO_INPUT_TYPE=ORIGINAL_FILE
```

`FASOO_INPUT_TYPE`은 `ORIGINAL_FILE`, `TEXT`, `MARKDOWN`, `CANONICAL_JSON` 중 하나입니다.
마스킹된 원본 파일이 필요하면 `ORIGINAL_FILE`을 사용합니다. Adapter는 원본을
`NAS_MOUNT_PATH/parselab/{run_id}/input` 아래에 복사하고 마스킹 결과 공간을
`masked`로 분리한 뒤 다음 동기 계약을 호출합니다.

```text
POST /piiapi/detect/system/path
sync="true"
inputPath=/dwp_comp/parselab/{run_id}/input/input.{ext}
outputPath=/dwp_comp/parselab/{run_id}/masked/result.json
maskedPath=/dwp_comp/parselab/{run_id}/masked/masked.{ext}
```

`NAS_MOUNT_PATH`는 Backend Pod가 PVC를 보는 경로이고 `FASOO_NAS_PATH`는 파수
서버가 같은 공유 경로를 보는 이름입니다. Backend Pod에는 예를 들어
`dwp-nas-volume` PVC를 `/app/data/dwp_comp`에 Mount해야 합니다. 개발계 파수
주소로 나가는 Egress와 방화벽 허용도 별도로 필요합니다. 사설 CA를 사용하면
인증서 Bundle을 Pod에 Mount하고 `FASOO_CA_BUNDLE`에 파일 경로를 지정합니다.

정상 완료 시 결과 JSON은 `deidentified` 산출물로, 마스킹 파일은 `masked`
산출물로 다운로드할 수 있습니다. `FASOO_API_KEY`가 지정된 환경에서만 Bearer
Header를 전송하며, API Key와 문서 원문은 애플리케이션 로그에 기록하지 않습니다.
`patternOptions`, `labelOptions` 등 전체 정책을 그대로 지정해야 하는 환경에서는
`FASOO_RULE_JSON`에 `rule` 객체 전체를 JSON 한 줄로 설정하면 개별 Pattern/Label
환경변수보다 우선 적용됩니다.

## 로컬 개발

PostgreSQL만 Docker로 시작합니다.

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

기본값에서는 개발 편의를 위해 `AUTO_CREATE_TABLES=true`입니다. Alembic을 명시적으로
사용하려면 `AUTO_CREATE_TABLES=false`로 바꾸고 다음을 실행합니다.

```bash
cd backend
uv run alembic upgrade head
```

## 실행 흐름

1. 첫 관리자 계정을 생성합니다.
2. Documents에서 TXT 또는 지원 문서를 업로드합니다.
3. New experiment에서 문서와 Parser 2개 이상을 선택하고 Preset/Override 및 비식별화
   실행 여부를 설정합니다.
4. 생성 API는 DB에 Experiment/Run을 저장하고 즉시 반환합니다.
5. In-Process Task Manager가 파싱 후 선택적으로 비식별화를 실행합니다.
6. Experiment Detail에서 파싱·비식별화 상태와 Artifact를 각각 확인합니다.
7. 완료 후 결과 비교 화면에서 Text/Markdown/JSON/Tables/Deidentified를 나란히
   보고 Text Diff를 계산합니다.
8. Run별 점수·메모·선호 결과를 저장하고 비교 결과를 CSV로 내려받습니다.

결과 파일 구조:

```text
data/
├── documents/{document_id}/original.{ext}
└── runs/{run_id}/
    ├── raw.json
    ├── canonical.json
    ├── output.md
    ├── output.txt
    └── deidentified.json
```

## API 예시

Base URL은 `http://localhost:8000/api/v1`입니다.

회원가입:

```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"parselab123","name":"Admin"}'
```

로그인:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"parselab123"}'
```

응답의 `access_token`을 `TOKEN`에 넣은 뒤 문서를 업로드합니다.

```bash
curl -X POST http://localhost:8000/api/v1/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F 'file=@sample.txt'
```

Parser와 Document UUID를 조회합니다.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/parsers

curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/documents
```

실험 생성:

```bash
curl -X POST http://localhost:8000/api/v1/experiments \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Mock Parser 비교",
    "document_id": "DOCUMENT_UUID",
    "run_deidentification": true,
    "parser_runs": [
      {"parser_connector_id": "PARSER_UUID_1", "config_override": {}},
      {"parser_connector_id": "PARSER_UUID_2", "config_override": {}}
    ]
  }'
```

상태와 비교 결과:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/experiments/EXPERIMENT_UUID

curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/experiments/EXPERIMENT_UUID/comparison

curl -OJ -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/runs/RUN_UUID/deidentified
```

Text Diff:

```bash
curl -G -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "base_run_id=BASE_RUN_UUID" \
  --data-urlencode "target_run_id=TARGET_RUN_UUID" \
  --data-urlencode "normalize_whitespace=true" \
  http://localhost:8000/api/v1/experiments/EXPERIMENT_UUID/text-diff
```

수동 평가와 선호 Parser 지정:

```bash
curl -X PUT http://localhost:8000/api/v1/runs/RUN_UUID/evaluation \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "text_score": 5,
    "table_score": 4,
    "reading_order_score": 5,
    "deidentification_score": 4,
    "is_preferred": true,
    "notes": "본문과 읽기 순서가 가장 안정적"
  }'
```

한 사용자가 같은 실험에서 새 Run을 선호 결과로 지정하면 기존 선호 Run은 자동으로
해제됩니다.

```bash
curl -OJ -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/experiments/EXPERIMENT_UUID/export.csv
```

OpenAPI 문서는 <http://localhost:8000/docs>에서 볼 수 있습니다.

HTTP Parser 등록 예:

```json
{
  "name": "Synap Internal",
  "slug": "synap-internal",
  "execution_type": "HTTP",
  "adapter_key": "synap_http",
  "base_url": "http://synap.internal",
  "default_config": {
    "use_image_ocr": false,
    "poll_interval_seconds": 0.5
  },
  "supported_formats": ["pdf", "docx", "pptx"],
  "timeout_seconds": 300
}
```

`synap_http` Adapter는 DocuAnalyzer REST API의 실제 비동기 계약을 사용합니다.

```text
POST /da
→ POST /filestatus/{fid} Polling
→ POST /result/{fid} (페이지별 JSON)
→ POST /delete/{fid}
```

`SYNAP_API_KEY`는 명세에 따라 Bearer Header가 아니라 각 요청의 `api_key` 필드로
전송합니다. `GET /health-check`는 API Key 없이 엔진 상태를 확인합니다.

Docling Command 등록 예:

```json
{
  "name": "Docling Local",
  "slug": "docling-local",
  "execution_type": "COMMAND",
  "adapter_key": "docling_command",
  "command_template": [
    "docling",
    "{input_path}",
    "--output",
    "{output_dir}"
  ],
  "default_config": {},
  "supported_formats": ["pdf", "docx", "pptx"],
  "timeout_seconds": 300
}
```

## 검사

```bash
cd backend
uv run ruff check .
uv run pytest -q

cd ../frontend
npm run build
```

통합 테스트는 임시 SQLite DB를 이용해 다음 전체 흐름을 실제 실행합니다.

```text
회원가입 → 로그인 → Mock Parser 자동 등록 → 문서 업로드
→ Preset 생성 → Experiment 생성 → BUILTIN/COMMAND Run 완료
→ Mock Fasoo 비식별화 → 원본/비식별화 파일·비교 결과 검증
→ Text Diff·JSON·운영 지표 검증 → 단일 선호 평가 저장
→ CSV 내보내기 → 파수 실패 시 파싱 성공 유지 검증
```

애플리케이션의 운영 DB는 설계대로 PostgreSQL/asyncpg를 사용합니다.

## 주요 디렉터리

```text
backend/app/
├── api/v1/          # 얇은 Router
├── services/        # 비즈니스 흐름
├── repositories/    # DB 접근
├── adapters/        # Parser/Deidentifier Adapter와 Registry
├── task_manager/    # In-Process 실행 제어
├── db/models/       # SQLAlchemy 모델
└── schemas/         # Pydantic 입출력 모델

frontend/src/
├── pages/           # 업로드, 실험, 비교 화면
├── components/      # Layout, 상태 표시
└── lib/             # API client, format helper
```
