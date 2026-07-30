# paserlab playground 배포

Synap/Fasoo 연동 확인용 Backend 1 Pod를 `playground` Namespace에 배포한다.
공용 개발기 Host의 `/paserlab/` 경로로 접근하며, PaddleOCR는 이미지 Build와
Runtime 모두 비활성화해 모델이 Pod에 포함되지 않는다.

## 사전 조건

- `playground` Namespace가 존재해야 한다.
- `playground`에 `dwp-nas-volume` PVC가 존재해야 한다.
- ParseLab 전용 PostgreSQL Database와 사용자를 준비해야 한다.
- Registry에 `registry.haiqv.ai/haiqv/paserlab:latest` 이미지를 Push해야 한다.

이미지는 PaddleOCR 없이 Build한다.

```bash
docker buildx build \
  --platform linux/amd64 \
  --build-arg INSTALL_PADDLEOCR=false \
  -t registry.haiqv.ai/haiqv/paserlab:latest \
  --push \
  backend
```

## Secret 생성

실제 Secret은 저장소에 Commit하지 않는다.

```bash
cp k8s/secret.env.example k8s/secret.env
```

`k8s/secret.env`에 개발기 DB, JWT, Synap/Fasoo 값을 입력한 뒤 Secret을 생성한다.
Database URL의 특수문자는 URL Encoding해야 한다.

```bash
kubectl -n playground create secret generic paserlab-secret \
  --from-env-file=k8s/secret.env \
  --dry-run=client -o yaml | kubectl apply -f -
```

## 배포와 확인

```bash
kubectl apply -k k8s
kubectl -n playground rollout status deployment/paserlab
kubectl -n playground get pod,service,ingress -l app.kubernetes.io/name=paserlab
```

개발기 URL:

```text
https://oasis-dev.agentone.kr/paserlab/
https://oasis-dev.agentone.kr/paserlab/health
https://oasis-dev.agentone.kr/paserlab/docs
```

기존 `playground` Ingress 전체를 이 저장소에서 관리하지 않는다. `paserlab` Ingress는
동일한 `oasis-dev.agentone.kr` Host와 `tls-agent-secret`을 사용하므로
Ingress Nginx가 기존 `/teams-bot/`, `/roltimate`, `/hallucinations/`, `/chat/`
경로와 `/paserlab/` 경로를 하나의 라우팅 설정으로 병합한다. 이렇게 하면 다른 팀
경로를 덮어쓰지 않으면서 `/paserlab`에만 rewrite 규칙을 적용할 수 있다.

Ingress를 거치지 않고 직접 확인해야 할 때는 Port Forward도 사용할 수 있다.

```bash
kubectl -n playground port-forward service/paserlab 18000:80
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
/dwp_comp/paserlab/fasoo-smoke/{run_id}/
```

처음에는 `/piiapi/configuration` Health Check를 확인한 다음 작은 파일 한 건을
Parser로 처리하고, 생성된 텍스트로 `/piiapi/detect/system/path`를 실행한다.

## 제거

Deployment와 Service만 제거하며 NAS 파일과 Secret은 자동 삭제하지 않는다.

```bash
kubectl delete -k k8s
```
