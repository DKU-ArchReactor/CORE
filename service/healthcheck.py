import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc


def main():
    with grpc.insecure_channel('127.0.0.1:50051') as channel:
        response = health_pb2_grpc.HealthStub(channel).Check(
            health_pb2.HealthCheckRequest(service='archreactor.v1.Simulator'), timeout=2)
        if response.status != health_pb2.HealthCheckResponse.SERVING:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
