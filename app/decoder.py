"""
명령어 디코더 모듈.

어셈블리 문자열을 파싱하여 opcode, 레지스터 번호, 즉시값 등을 추출한다.
Non-Pipeline의 ID 단계에 해당하며, Pipeline 확장 시 stage_id()에서도 재사용한다.
"""

# 레지스터 이름 → 번호 매핑 (x0~x31 및 ABI 이름)
_REG_MAP = {f"x{i}": i for i in range(32)}
_REG_MAP.update({
    "zero": 0, "ra": 1, "sp": 2, "gp": 3, "tp": 4,
    "t0": 5, "t1": 6, "t2": 7,
    "s0": 8, "fp": 8, "s1": 9,
    "a0": 10, "a1": 11, "a2": 12, "a3": 13,
    "a4": 14, "a5": 15, "a6": 16, "a7": 17,
    "s2": 18, "s3": 19, "s4": 20, "s5": 21,
    "s6": 22, "s7": 23, "s8": 24, "s9": 25,
    "s10": 26, "s11": 27,
    "t3": 28, "t4": 29, "t5": 30, "t6": 31,
})


def _parse_reg(token: str) -> int:
    """레지스터 토큰을 번호로 변환한다."""
    token = token.strip().rstrip(",")
    if token not in _REG_MAP:
        raise ValueError(f"알 수 없는 레지스터: {token}")
    return _REG_MAP[token]


def _parse_imm(token: str) -> int:
    """즉시값 토큰을 정수로 변환한다 (10진수, 16진수 지원)."""
    token = token.strip().rstrip(",")
    return int(token, 0)


def _parse_mem(token: str) -> tuple[int, int]:
    """메모리 오퍼랜드 'imm(rs)' 형태를 파싱한다."""
    token = token.strip()
    imm_str, rest = token.split("(")
    rs_str = rest.rstrip(")")
    return _parse_imm(imm_str), _parse_reg(rs_str)


def decode(instr: str) -> dict:
    """
    어셈블리 명령어 문자열을 해석하여 필드별로 분리한다.

    Args:
        instr: 어셈블리 명령어 (예: "addi x1, x0, 10")

    Returns:
        dict: op, rd, rs1, rs2, imm, reg_write, mem_read, mem_write, branch 등
    """
    parts = instr.strip().split()
    op = parts[0].lower()

    result = {
        "op": op,
        "rd": 0,
        "rs1": 0,
        "rs2": 0,
        "imm": 0,
        "reg_write": False,
        "mem_read": False,
        "mem_write": False,
        "branch": False,
    }

    # R-type: add, sub, and, or, xor, sll, srl, sra, slt, sltu
    if op in ("add", "sub", "and", "or", "xor", "sll", "srl", "sra", "slt", "sltu"):
        result["rd"] = _parse_reg(parts[1])
        result["rs1"] = _parse_reg(parts[2])
        result["rs2"] = _parse_reg(parts[3])
        result["reg_write"] = True

    # I-type 산술: addi, andi, ori, xori, slti, sltiu, slli, srli, srai
    elif op in ("addi", "andi", "ori", "xori", "slti", "sltiu", "slli", "srli", "srai"):
        result["rd"] = _parse_reg(parts[1])
        result["rs1"] = _parse_reg(parts[2])
        result["imm"] = _parse_imm(parts[3])
        result["reg_write"] = True

    # Load: lw rd, imm(rs1)
    elif op == "lw":
        result["rd"] = _parse_reg(parts[1])
        imm, rs1 = _parse_mem(parts[2])
        result["rs1"] = rs1
        result["imm"] = imm
        result["reg_write"] = True
        result["mem_read"] = True

    # Store: sw rs2, imm(rs1)
    elif op == "sw":
        result["rs2"] = _parse_reg(parts[1])
        imm, rs1 = _parse_mem(parts[2])
        result["rs1"] = rs1
        result["imm"] = imm
        result["mem_write"] = True

    # Branch: beq, bne, blt, bge, bltu, bgeu
    elif op in ("beq", "bne", "blt", "bge", "bltu", "bgeu"):
        result["rs1"] = _parse_reg(parts[1])
        result["rs2"] = _parse_reg(parts[2])
        result["imm"] = _parse_imm(parts[3])
        result["branch"] = True

    # lui rd, imm
    elif op == "lui":
        result["rd"] = _parse_reg(parts[1])
        result["imm"] = _parse_imm(parts[2])
        result["reg_write"] = True

    # jal rd, imm
    elif op == "jal":
        result["rd"] = _parse_reg(parts[1])
        result["imm"] = _parse_imm(parts[2])
        result["reg_write"] = True
        result["branch"] = True

    # jalr rd, rs1, imm
    elif op == "jalr":
        result["rd"] = _parse_reg(parts[1])
        result["rs1"] = _parse_reg(parts[2])
        result["imm"] = _parse_imm(parts[3])
        result["reg_write"] = True
        result["branch"] = True

    else:
        raise ValueError(f"지원하지 않는 명령어: {op}")

    return result
