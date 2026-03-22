# Core는 독립 서버가 아니라 Python 패키지로 BE에서 import하여 사용.
# 이 Dockerfile은 테스트 실행 및 CI/CD 파이프라인용.

FROM python:3.12-slim

WORKDIR /core

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["pytest", "tests/", "-v"]
