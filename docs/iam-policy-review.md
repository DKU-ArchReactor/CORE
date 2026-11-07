# CORE 자동 배포 권한

대상은 Blank Canvas `242925688392`, 서울 `ap-northeast-2`다.
`infrastructure/github-oidc.yml`은 기존 GitHub OIDC 공급자를 재사용하고
`DKU-ArchReactor/CORE`의 `develop` ref와 STS audience를 StringEquals로 확인한다.
PR이나 다른 브랜치는 역할을 사용할 수 없다. `environment`를 workflow에 추가하면
OIDC subject 형식이 달라지므로 신뢰 정책을 함께 검토해야 한다.

## 정책 생성과 검토

IAM Policy Autopilot 0.4.0으로 `scripts/deploy.py`의 SDK 호출 정책 초안을 생성했다.

```sh
uvx iam-policy-autopilot@0.4.0 generate-policies scripts/deploy.py \
  --region ap-northeast-2 --account 242925688392 \
  --service-hints s3 codebuild ecr cloudformation ecs sts --pretty
```

초안은 SDK 편의 함수 `upload_file`과 CloudFormation이 대신 호출하는 ECS 작업을
완전히 추론하지 못하므로 실제 호출과 AWS 권한 문서를 대조했다.
광범위한 ListStacks와 IAM PassRole 초안은 제외하고 아래 범위로 수정했다.

| 작업 | 허용 범위 |
| --- | --- |
| S3 업로드 | 기존 배포 버킷의 `core-source/*` |
| CodeBuild 실행·조회 | `archreactor-core-image-build` |
| ECR 이미지 조회 | `capstone/archreactor-core` |
| CloudFormation 변경안 생성·조회·실행 | 기존 `archreactor-simulator-service` 스택 |
| ECS 서비스 조회·갱신 | `archreactor-simulator` 서비스 |
| ECS 태스크 조회·목록 | CORE 클러스터 |
| 태스크 정의 등록·태그 | `archreactor-simulator:*` family |
| PassRole | 기존 CORE 실행 역할, `ecs-tasks.amazonaws.com` 대상만 |

`ecs:DescribeTaskDefinition`과 `ecs:DeregisterTaskDefinition`은 AWS의
[서비스 권한 표](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ecs.html)에서
리소스 수준 제어를 지원하지 않으므로 `Resource: '*'`가 필요하다. 서울 요청으로 제한했다.
Deregister 권한은 CloudFormation의 이전 revision 정리와 실패 복구에 사용한다.
이 예외로 다른 서울 태스크 정의의 등록 해제도 권한상 가능하므로 저장소 쓰기 권한을 제한해야 한다.
등록 해제는 이미 실행 중인 태스크를 정지시키지는 않는다.

IAM 수정, 시크릿 읽기, BE 배포, 네트워크 변경 권한은 없다.
배포 스크립트의 change set 검사와 IAM 제한은 함께 사용한다.
CodeBuild의 기존 빌드 역할과 ECS 실행 역할은 이 역할과 별개이며 변경하지 않는다.

## 검증

- `cfn-lint 1.60.0`과 `infrastructure/github-oidc.guard` 통과.
- IAM Access Analyzer: identity policy 지적 없음. Trust policy의 audience 단일값 관련
  일반 제안 1개는 qualifier 없는 StringEquals를 사용해 이미 준수한다. 오류·보안 경고 없음.
- GitHub Actions `actionlint 1.7.12` 통과.
- 실제 OIDC 교환과 배포의 최종 확인은 develop 워크플로 실행에서 수행한다.

참고: [CloudFormation 작업별 권한](https://docs.aws.amazon.com/service-authorization/latest/reference/list_cloudformation.html),
[AWS 인증 액션](https://github.com/aws-actions/configure-aws-credentials/tree/v5).
