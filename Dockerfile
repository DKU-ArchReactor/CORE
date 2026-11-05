# 테스트 실행용 이미지. 독립 gRPC 서버 이미지는 Dockerfile.server를 사용한다.

FROM python:3.12-slim

WORKDIR /core

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["pytest", "tests/", "-v"]
