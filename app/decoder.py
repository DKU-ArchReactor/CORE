"""
명령어 디코더 모듈.

어셈블리 문자열을 파싱하여 opcode, 레지스터 번호, 즉시값 등을 추출한다.
Non-Pipeline의 ID 단계에 해당하며, Pipeline 확장 시 stage_id()에서도 재사용한다.
"""


def decode(instr: str) -> dict:
    """
    어셈블리 명령어 문자열을 해석하여 필드별로 분리한다.

    Args:
        instr: 어셈블리 명령어 (예: "addi x1, x0, 10")

    Returns:
        dict: op, rd, rs1, rs2, imm, reg_write, mem_read, mem_write, branch 등
    """
    # TODO: RV32I 명령어 파싱 구현
    pass
