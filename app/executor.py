"""
ALU 실행 모듈.

디코딩된 명령어의 연산을 수행한다.
Non-Pipeline의 EX 단계에 해당하며, Pipeline 확장 시 stage_ex()에서도 재사용한다.
"""


def execute(op: str, val1: int, val2: int, imm: int) -> int:
    """
    ALU 연산을 수행한다.

    Args:
        op: 연산 종류 (add, sub, and, or, slt 등)
        val1: rs1 레지스터 값
        val2: rs2 레지스터 값
        imm: 즉시값 (I-type 명령어용)

    Returns:
        int: 연산 결과
    """
    # TODO: RV32I ALU 연산 구현
    pass
