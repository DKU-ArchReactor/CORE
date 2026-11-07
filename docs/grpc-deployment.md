# CORE 독립 gRPC 서비스

BE의 `archreactor-core` Beanstalk 환경은 BE core 브랜치 환경이다.
이 서비스는 **archreactor-simulator** ECS 서비스이며 서로 다른 배포 단위다.
계정 `242925688392`, 서울 `ap-northeast-2`만 사용한다.

## 계약과 실행

- 서비스: `archreactor.v1.Simulator/RunSimulation` (unary).
- 입력: request_id, ELF bytes, SINGLE/PIPELINE, max_cycles.
- 출력: request_id, 서버가 생성한 execution_id, 실행 상태, CORE 버전,
  결과 스키마 버전, 기존 `run_simulation()` 결과를 담은 UTF-8 `result_json`.
  JSON의 summary/history/console_output/program/simulator는 기존 규격을 유지한다.
- RPC 실패: INVALID_ARGUMENT(지원하지 않는 ELF/명령), RESOURCE_EXHAUSTED(크기/동시성),
  DEADLINE_EXCEEDED, INTERNAL. 정상 반환 중 COMPLETED/CYCLE_LIMIT/SIMULATION_ERROR를 구분한다.
- ELF 256 KiB, 로드할 메모리 64 KiB, 최대 2,000 cycles, 결과 8 MiB,
  계산 10초, 태스크당 동시 2개. 초과 요청은 대기열 없이 거절한다.
- 각 요청은 별도 Python 프로세스에서 create_state → run_simulation → delete_state.
  클라이언트 취소/기한 초과 시 프로세스 SIGTERM 후 최대 250ms 뒤 SIGKILL.
  강제 종료도 프로세스 메모리 전체를 회수한다. Linux 워커 메모리 384 MiB, CPU 11/12초.
- 업로드 ELF는 시뮬레이터가 해석하며 네이티브 실행하지 않는다.
- RPC 계약은 `proto/archreactor/v1/simulation.proto`; 생성 코드는 저장소에 고정한다.
  재생성: requirements-contract.txt 설치 후 `sh scripts/generate-contract.sh`.
  `python scripts/check-contract.py`는 생성 코드와 고정 v1 descriptor를 비교한다.
- BE는 계약 생성 코드만 자체 저장소에 복사해 고정한다. CORE 구현에 대한 패키지 의존성이 없다.
  v1은 기존 필드 번호/타입/의미 유지, 필드 추가만 허용한다. baseline 변경으로 검사를 우회하지 않는다.
  JSON 1.x도 기존 필드의 이름/타입/의미를 유지한다. 파괴적 변경은 v2를 병행 제공하고 BE를 별도 이전한다.

## 실행 환경

기존 VPC의 public subnet에서 Fargate 0.5 vCPU / 1 GiB 태스크 1개를 실행한다.
공인 IPv4는 ECR 이미지 다운로드/CloudWatch 전송에만 쓰며 인바운드는 BE 보안 그룹의
TCP 50051만 허용한다. BE 연결 주소는 `simulator.archreactor.internal:50051`.
Cloud Map은 private task IP만 등록한다. h2c gRPC는 프록시 없이 VPC 내부에서 직접 연결한다.
TLS/mTLS는 초기 구성에 포함하지 않으며 보안 그룹을 서비스 신뢰 경계로 사용한다.

기존 private subnet에는 NAT가 없다. 별도 NAT/ALB/NLB 비용과 운영을 줄이기 위해 이 구성을 선택했다.
추가 비용은 Fargate CPU/메모리 실행시간, 공인 IPv4, Cloud Map/Route53 private zone 및 DNS,
ECR 저장·스캔, CodeBuild, CloudWatch 로그(14일 보존)이다. 배포 중에는 태스크가 일시적으로 2개다.
기본 ephemeral storage 외 별도 디스크·DB는 없다. 단일 AZ/태스크이므로 고가용성 구성은 아니다.

컨테이너는 비root, read-only root filesystem, Linux capabilities 제거, AWS task role 없음.
헬스체크는 실제 grpc.health.v1 서비스 호출. ECS rolling 100/200과 circuit breaker rollback을 사용한다.
새 요청마다 BE가 DNS 채널을 열어 교체 태스크를 찾으며, TTL 10초 동안 짧은 재연결 실패가 가능하다.
자동 재시도는 중복 계산 방지를 위해 끈다. 입력/프로그램 출력/인증값은 CORE 로그에 기록하지 않는다.

## 자동 배포

`develop`에 push 또는 PR 병합이 발생하면 `.github/workflows/deploy.yml`이 실행된다.
PR에서는 `.github/workflows/test.yml`로 계약 검사, pytest, 실제 컨테이너의 single/pipeline gRPC 실행을 검증한다.
배포 workflow도 같은 CI를 먼저 통과해야 한다.

1. GitHub OIDC로 `archreactor-core-github-deploy` 역할을 1시간 동안 사용한다.
   저장소에 AWS 액세스 키를 등록할 필요가 없다. 신뢰 조건은
   `repo:DKU-ArchReactor/CORE:ref:refs/heads/develop`와 `sts.amazonaws.com`으로 고정한다.
2. STS 계정 `242925688392`를 확인하고 Git에 추적된 허용 파일만 ZIP으로 묶는다.
   `.env*`, 심볼릭 링크, 미추적 파일은 제외한다. CI는 체크아웃한 커밋을 배포한다.
3. 기존 `archreactor-core-image-build` CodeBuild가 테스트, 컨테이너 검사 후 ECR에 업로드한다.
   이미지 태그는 `core-<git SHA 12자>-<ZIP SHA256 16자>`이고 ECR 태그는 변경 불가다.
4. `archreactor-simulator-service`의 이전 템플릿을 유지하고 `Image`만 새 digest로 바꾼다.
   Change set이 Task/Service 수정 이외를 포함하면 중단한다.
5. ECS 안정화, 태스크의 실제 digest, gRPC health를 확인한다.
6. 공개 BE API로 RV32IM 컴파일, single/pipeline 결과 42, cycle limit,
   배포 버전 및 두 모드의 최종 상태 일치를 확인한다.

동시 배포는 하나씩 실행하며 진행 중인 배포를 새 push로 취소하지 않는다.
GitHub의 동시성 대기열에서는 대기 중이던 오래된 커밋이 최신 커밋으로 교체될 수 있다.
실패 시 GitHub 실행이 실패로 표시된다. ECS 기동 실패는 circuit breaker가 되돌리며,
공개 API 검사 실패는 자동 롤백하지 않으므로 기록을 확인해 아래 절차로 복구한다.

각 Actions 실행의 Summary와 `core-deployment-*` 아티팩트에
`dist/deployment.json`(이전/새 digest, 소스 SHA, 빌드 ID) 및 공개 API 검사 결과를 30일 보관한다.
게스트 토큰은 기록하지 않는다. 장기간 보존할 롤백 기록은 별도로 내려받는다.

## 최초 AWS 연결

기존 인프라는 `infrastructure/build.yml`, `infrastructure/service.yml`에 정의돼 있다.
스택은 각각 `archreactor-simulator-build`, `archreactor-simulator-service`다.
ECR 저장소는 `capstone/archreactor-core`이고 CORE 배포는 BE 스택을 갱신하지 않는다.

관리자가 `infrastructure/github-oidc.yml`을 `archreactor-core-github-oidc` 스택으로 생성한다.
기존 `token.actions.githubusercontent.com` OIDC 공급자와 기존 Fargate 실행 역할을 재사용한다.
`CoreExecutionRoleArn`은 서비스 스택의 `ExecutionRole` 실제 ARN으로 지정한다.
배포 역할에는 이 역할의 PassRole만 허용하며 자체 IAM 수정 권한은 부여하지 않는다.
권한 검토 근거는 [iam-policy-review.md](iam-policy-review.md)를 참고한다.

로컬 관리 명령은 반드시 `--profile archreactor-new --region ap-northeast-2`를 사용하고,
변경 전에 `aws sts get-caller-identity`로 계정을 확인한다.
역할 설치와 코드 병합이 모두 완료되어야 자동 배포가 작동한다.

## 로컬 배포와 롤백

Python 3.12에서 다음을 실행한다. 로컬 스크립트는 `archreactor-new` 프로파일을 명시적으로 사용한다.

```sh
python -m pip install -r requirements-ci.txt
python scripts/check-contract.py
pytest -q
python scripts/deploy.py
```

Git 추적 파일의 로컬 수정도 ZIP 해시에 반영되므로 정규 배포는 Actions를 사용한다.
새 파일은 Git에 추가한 후에만 포함된다. 직접 배포할 때는 Actions 배포가 진행 중인지 먼저 확인한다.

이전 성공한 배포의 `previous_image` 또는 `image` 끝에 있는 `sha256:...` 값을 사용한다.

```sh
python scripts/deploy.py --rollback sha256:PREVIOUS_DIGEST
python scripts/verify-public-api.py --phase before --expected-version PREVIOUS_CORE_VERSION
```

롤백은 ECR에 남아 있고 CORE 버전 태그가 있는 digest만 허용한다.
워크플로가 기본 브랜치에도 존재하면 Actions의 `Deploy CORE to ECS` → Run workflow에서
**develop**을 선택하고 `rollback_digest`를 입력해 같은 작업을 실행할 수 있다.
기본 브랜치가 `main`이고 워크플로가 `develop`에만 있는 동안은 이 수동 실행 메뉴가 없으므로
로컬 롤백을 사용한다. `develop` push 자동 배포에는 영향이 없다.

CloudFormation이 UPDATE_ROLLBACK 중이면 완료까지 기다린 후 재배포한다.
ECR은 tagged 이미지를 자동 삭제하지 않고 untagged만 14일 후 정리한다.
현재/롤백 digest를 제외한 오래된 tagged 버전은 운영자가 정리한다.

## BE 프로그램 규칙

BE `compile_profile=rv32im`이 기본이다. RV32IM/ILP32, freestanding, 표준 라이브러리 없음,
고정 linker script로 `.text` 0x10000, C는 `_start → main → ecall 10`으로 종료한다.
ASM은 `_start`를 직접 정의한다. syscall 1(정수), 4(문자열), 10(종료)만 지원한다.
기존 native 빌드는 계속 다운로드할 수 있지만 CORE 호출 시 422로 거절한다.
`compile_profile=native`는 호스트 ELF가 필요한 기존 용도로만 선택한다.
단계별 세션, 스트리밍, 디스크에 결과 영속 저장, mTLS, 멀티 AZ는 초기 범위 밖이다.

## 기존 서비스 이관 범위

이 변경은 기존에 수동 배포하던 gRPC 서비스, 계약, 컨테이너와 인프라 정의를 CORE 저장소에 포함하고
같은 배포 경로를 GitHub Actions에 연결한다. `app/`의 시뮬레이터 엔진은 변경하지 않는다.
현재 실행 버전은 고정된 문서 값 대신 마지막 성공한 Actions 아티팩트 또는 ECS task definition에서 확인한다.
