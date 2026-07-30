# parselab oasis-be 배포

Synap/Fasoo 연동 확인용 Backend 1 Pod를 `oasis-be` Namespace에 배포한다.
공용 개발기 Host의 `/parselab/` 경로로 접근하며, PaddleOCR는 이미지 Build와
Runtime 모두 비활성화해 모델이 Pod에 포함되지 않는다.

## 사전 조건

- `oasis-be` Namespace가 존재해야 한다.
- `oasis-be`에 `dwp-nas-volume` PVC가 존재해야 한다.
- Registry에 `registry.haiqv.ai/haiqv/parselab:latest` 이미지를 Push해야 한다.

## 시연용 SQLite

공용 PostgreSQL을 변경하지 않도록 개발기 시연 배포는 Pod의 `emptyDir`에 SQLite
파일(`/app/sqlite/parselab.db`)을 만든다. 같은 Pod 안에서 Backend Container가
재시작될 때는 유지되지만 Deployment Rollout이나 Pod 재생성 시 DB가 초기화된다.
초기화 후에는 첫 사용자 가입과 Synap Connector 등록을 다시 해야 한다.

문서와 Fasoo 작업 파일은 기존 NAS 전용 경로에 남는다. SQLite 파일은 NAS에 두지
않으므로 NFS 파일 잠금 문제는 발생하지 않는다. 시연 이후 PostgreSQL로 전환할 때는
`DATABASE_URL`과 Deployment의 `sqlite-data` Mount만 교체하면 된다.

이미지는 PaddleOCR 없이 Build한다.

```bash
docker buildx build \
  --platform linux/amd64 \
  --build-arg INSTALL_PADDLEOCR=false \
  -t registry.haiqv.ai/haiqv/parselab:latest \
  --push \
  backend
```

## Secret 생성

실제 Secret은 저장소에 Commit하지 않는다.

```bash
cp k8s/secret.env.example k8s/secret.env
```

`k8s/secret.env`에 JWT, Synap API Key와 Fasoo 로그인 계정을 입력한 뒤 Secret을
생성한다. DB 연결 정보는 ConfigMap의 시연용 SQLite URL을 사용한다.

```dotenv
FASOO_USERNAME=admin
FASOO_PASSWORD=<실제 비밀번호>
FASOO_API_KEY=
```

`FASOO_API_KEY`는 비워 둔다. Backend가 ConfigMap의 `FASOO_AUTH_URL`로 로그인해
응답의 `access_token`을 Bearer Token으로 사용하고, `401`이면 한 번 재로그인한다.
수동 발급한 정적 Token을 긴급하게 사용할 때만 `FASOO_API_KEY`에 값을 넣는다.

```bash
kubectl -n oasis-be create secret generic parselab-secret \
  --from-env-file=k8s/secret.env \
  --dry-run=client -o yaml | kubectl apply -f -
```

## 배포와 확인

```bash
kubectl apply -k k8s
kubectl -n oasis-be rollout status deployment/parselab
kubectl -n oasis-be get pod,service,ingress -l app.kubernetes.io/name=parselab
```

개발기 URL:

```text
https://oasis-dev.agentone.kr/parselab/
https://oasis-dev.agentone.kr/parselab/health
https://oasis-dev.agentone.kr/parselab/docs
```

기존 `oasis-be` Ingress 전체를 이 저장소에서 관리하지 않는다. `parselab` Ingress는
동일한 `oasis-dev.agentone.kr` Host와 `tls-agent-secret`을 사용하므로
Ingress Nginx가 기존 `/teams-bot/`, `/roltimate`, `/hallucinations/`, `/chat/`
경로와 `/parselab/` 경로를 하나의 라우팅 설정으로 병합한다. 이렇게 하면 다른 팀
경로를 덮어쓰지 않으면서 `/parselab`에만 rewrite 규칙을 적용할 수 있다.

Ingress를 거치지 않고 직접 확인해야 할 때는 Port Forward도 사용할 수 있다.

```bash
kubectl -n oasis-be port-forward service/parselab 18000:80
curl http://localhost:18000/health
```

## Synap Connector

Synap URL은 환경변수가 아니라 Parser Connector의 `base_url`에 저장한다. 관리자
화면에서 `synap_http` Connector를 Box와 Chat 각각 하나씩 등록한다.

```text
Box:
http://docuanalyzer-service-box.docuanalyzer.svc.cluster.local/docuanalyzer-box

Chat:
http://docuanalyzer-service-chat.docuanalyzer.svc.cluster.local/docuanalyzer-chat
```

등록 후 Parser Health Check를 먼저 실행하고 개인정보가 없는 작은 파일 한 건만
처리한다.

## Fasoo 경로

Pod의 `/app/data/dwp_comp`와 Fasoo의 `/dwp_comp`가 동일한 NAS를 가리킨다.
`FASOO_INPUT_TYPE=TEXT`로 설정해 Synap, Docling, MinerU 등 선택한 각 Parser가
전처리를 완료한 뒤 생성한 `output.txt`를 Run별 파수 입력으로 사용한다. 원본
PDF/DOCX를 파수에 직접 전달하지 않는다.

검증 파일과 결과는 다음 전용 하위 경로에만 생성된다.

```text
/dwp_comp/parselab/fasoo-smoke/{run_id}/
```

처음에는 `/piiapi/configuration` Health Check를 확인한 다음 작은 파일 한 건을
Parser로 처리하고, 생성된 텍스트로 `/piiapi/detect/system/path`를 실행한다.

## 제거

Deployment와 Service만 제거하며 NAS 파일과 Secret은 자동 삭제하지 않는다.

```bash
kubectl delete -k k8s
```
