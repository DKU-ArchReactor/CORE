"""
ALU 실행 모듈.

디코딩된 명령어의 연산을 수행한다. RV32I + RV32M을 지원하고
32비트 signed wrapping을 보장한다.
"""

from __future__ import annotations

_MASK32 = 0xFFFFFFFF
_SIGN_BIT = 1 << 31


def _to_u32(value: int) -> int:
    return value & _MASK32


def _to_s32(value: int) -> int:
    value &= _MASK32
    return value - (1 << 32) if value & _SIGN_BIT else value


def execute(decoded: dict, rs1_val: int, rs2_val: int) -> dict:
    op = decoded["op"]
    imm = decoded.get("imm", 0)

    if op == "add":
        result = _to_s32(rs1_val + rs2_val)
    elif op == "sub":
        result = _to_s32(rs1_val - rs2_val)
    elif op == "and":
        result = _to_u32(rs1_val & rs2_val)
    elif op == "or":
        result = _to_u32(rs1_val | rs2_val)
    elif op == "xor":
        result = _to_u32(rs1_val ^ rs2_val)
    elif op == "sll":
        result = _to_s32(_to_u32(rs1_val) << (rs2_val & 0x1F))
    elif op == "srl":
        result = _to_u32(_to_u32(rs1_val) >> (rs2_val & 0x1F))
    elif op == "sra":
        result = _to_s32(_to_s32(rs1_val) >> (rs2_val & 0x1F))
    elif op == "slt":
        result = 1 if _to_s32(rs1_val) < _to_s32(rs2_val) else 0
    elif op == "sltu":
        result = 1 if _to_u32(rs1_val) < _to_u32(rs2_val) else 0
    elif op == "addi":
        result = _to_s32(rs1_val + imm)
    elif op == "andi":
        result = _to_u32(rs1_val & imm)
    elif op == "ori":
        result = _to_u32(rs1_val | imm)
    elif op == "xori":
        result = _to_u32(rs1_val ^ imm)
    elif op == "slti":
        result = 1 if _to_s32(rs1_val) < _to_s32(imm) else 0
    elif op == "sltiu":
        result = 1 if _to_u32(rs1_val) < _to_u32(imm) else 0
    elif op == "slli":
        result = _to_s32(_to_u32(rs1_val) << (imm & 0x1F))
    elif op == "srli":
        result = _to_u32(_to_u32(rs1_val) >> (imm & 0x1F))
    elif op == "srai":
        result = _to_s32(_to_s32(rs1_val) >> (imm & 0x1F))
    elif op in ("lb", "lh", "lw", "lbu", "lhu", "sb", "sh", "sw"):
        result = _to_s32(rs1_val + imm)
    elif op == "lui":
        result = _to_s32(imm)
    elif op == "auipc":
        result = _to_s32(rs1_val + imm)
    elif op in ("jal", "jalr"):
        result = 0
    elif op == "beq":
        result = 1 if _to_u32(rs1_val) == _to_u32(rs2_val) else 0
    elif op == "bne":
        result = 1 if _to_u32(rs1_val) != _to_u32(rs2_val) else 0
    elif op == "blt":
        result = 1 if _to_s32(rs1_val) < _to_s32(rs2_val) else 0
    elif op == "bge":
        result = 1 if _to_s32(rs1_val) >= _to_s32(rs2_val) else 0
    elif op == "bltu":
        result = 1 if _to_u32(rs1_val) < _to_u32(rs2_val) else 0
    elif op == "bgeu":
        result = 1 if _to_u32(rs1_val) >= _to_u32(rs2_val) else 0
    elif op == "mul":
        result = _to_s32(_to_s32(rs1_val) * _to_s32(rs2_val))
    elif op == "mulh":
        product = _to_s32(rs1_val) * _to_s32(rs2_val)
        result = _to_s32((product >> 32) & _MASK32)
    elif op == "mulhsu":
        product = _to_s32(rs1_val) * _to_u32(rs2_val)
        result = _to_s32((product >> 32) & _MASK32)
    elif op == "mulhu":
        product = _to_u32(rs1_val) * _to_u32(rs2_val)
        result = _to_s32((product >> 32) & _MASK32)
    elif op == "div":
        dividend = _to_s32(rs1_val)
        divisor = _to_s32(rs2_val)
        result = -1 if divisor == 0 else _to_s32(int(dividend / divisor))
    elif op == "divu":
        dividend = _to_u32(rs1_val)
        divisor = _to_u32(rs2_val)
        result = _MASK32 if divisor == 0 else _to_u32(dividend // divisor)
    elif op == "rem":
        dividend = _to_s32(rs1_val)
        divisor = _to_s32(rs2_val)
        if divisor == 0:
            result = dividend
        else:
            quotient = int(dividend / divisor)
            result = _to_s32(dividend - quotient * divisor)
    elif op == "remu":
        dividend = _to_u32(rs1_val)
        divisor = _to_u32(rs2_val)
        result = dividend if divisor == 0 else _to_u32(dividend % divisor)
    elif op == "ecall":
        result = 0
    else:
        raise ValueError(f"ALU: 지원하지 않는 연산: {op}")

    imm_ops = (
        "addi", "andi", "ori", "xori", "slti", "sltiu", "slli", "srli", "srai",
        "lb", "lh", "lw", "lbu", "lhu", "sb", "sh", "sw", "lui", "auipc",
    )
    operand2 = 0 if op == "ecall" else _to_u32(rs2_val if op not in imm_ops else imm)
    return {
        "alu_result": result,
        "alu_op": op,
        "operand1": _to_u32(rs1_val),
        "operand2": operand2,
    }
