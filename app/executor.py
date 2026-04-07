"""
ALU 실행 모듈.

디코딩된 명령어의 연산을 수행한다.
Non-Pipeline의 EX 단계에 해당하며, Pipeline 확장 시 stage_ex()에서도 재사용한다.
"""

# 32비트 마스크
_MASK32 = 0xFFFFFFFF


def _to_signed(val: int) -> int:
    """32비트 unsigned → signed 변환."""
    val &= _MASK32
    return val - (1 << 32) if val >= (1 << 31) else val


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
    # R-type 연산
    if op == "add":
        return _to_signed(val1 + val2)
    if op == "sub":
        return _to_signed(val1 - val2)
    if op == "and":
        return val1 & val2
    if op == "or":
        return val1 | val2
    if op == "xor":
        return val1 ^ val2
    if op == "sll":
        return _to_signed(val1 << (val2 & 0x1F))
    if op == "srl":
        return (val1 & _MASK32) >> (val2 & 0x1F)
    if op == "sra":
        return _to_signed(val1) >> (val2 & 0x1F)
    if op == "slt":
        return 1 if _to_signed(val1) < _to_signed(val2) else 0
    if op == "sltu":
        return 1 if (val1 & _MASK32) < (val2 & _MASK32) else 0

    # I-type 산술 연산
    if op == "addi":
        return _to_signed(val1 + imm)
    if op == "andi":
        return val1 & imm
    if op == "ori":
        return val1 | imm
    if op == "xori":
        return val1 ^ imm
    if op == "slti":
        return 1 if _to_signed(val1) < _to_signed(imm) else 0
    if op == "sltiu":
        return 1 if (val1 & _MASK32) < (imm & _MASK32) else 0
    if op == "slli":
        return _to_signed(val1 << (imm & 0x1F))
    if op == "srli":
        return (val1 & _MASK32) >> (imm & 0x1F)
    if op == "srai":
        return _to_signed(val1) >> (imm & 0x1F)

    # Load/Store: 주소 계산 (base + offset)
    if op in ("lw", "sw"):
        return _to_signed(val1 + imm)

    # lui: 상위 20비트 로드
    if op == "lui":
        return _to_signed(imm << 12)

    # jal / jalr: 주소 계산은 simulator에서 처리, ALU는 0 반환
    if op in ("jal", "jalr"):
        return 0

    # Branch: 비교 결과 반환 (1=taken, 0=not taken)
    if op == "beq":
        return 1 if val1 == val2 else 0
    if op == "bne":
        return 1 if val1 != val2 else 0
    if op == "blt":
        return 1 if _to_signed(val1) < _to_signed(val2) else 0
    if op == "bge":
        return 1 if _to_signed(val1) >= _to_signed(val2) else 0
    if op == "bltu":
        return 1 if (val1 & _MASK32) < (val2 & _MASK32) else 0
    if op == "bgeu":
        return 1 if (val1 & _MASK32) >= (val2 & _MASK32) else 0

    raise ValueError(f"ALU: 지원하지 않는 연산: {op}")
