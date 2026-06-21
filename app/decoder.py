"""
명령어 디코더 모듈.

ELF raw machine code 32비트 워드를 해석하여 RV32IM 명령어 필드를 반환한다.
"""

from __future__ import annotations

from typing import Dict

_REG_NAMES = [
    "zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2",
    "s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5",
    "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
    "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6",
]


def _bits(value: int, start: int, end: int) -> int:
    mask = (1 << (end - start + 1)) - 1
    return (value >> start) & mask


def _sign_extend(value: int, bits: int) -> int:
    sign_bit = 1 << (bits - 1)
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & sign_bit else value


def _register_name(reg_num: int) -> str:
    return _REG_NAMES[reg_num] if 0 <= reg_num < len(_REG_NAMES) else f"x{reg_num}"


def decode(raw_word: int) -> Dict[str, object]:
    opcode = _bits(raw_word, 0, 6)
    rd = _bits(raw_word, 7, 11)
    funct3 = _bits(raw_word, 12, 14)
    rs1 = _bits(raw_word, 15, 19)
    rs2 = _bits(raw_word, 20, 24)
    funct7 = _bits(raw_word, 25, 31)

    imm_i = _sign_extend(_bits(raw_word, 20, 31), 12)
    imm_s = _sign_extend((_bits(raw_word, 25, 31) << 5) | _bits(raw_word, 7, 11), 12)
    imm_b = _sign_extend(
        (_bits(raw_word, 31, 31) << 12)
        | (_bits(raw_word, 7, 7) << 11)
        | (_bits(raw_word, 25, 30) << 5)
        | (_bits(raw_word, 8, 11) << 1),
        13,
    )
    imm_u = _sign_extend(_bits(raw_word, 12, 31), 20) << 12
    imm_j = _sign_extend(
        (_bits(raw_word, 31, 31) << 20)
        | (_bits(raw_word, 12, 19) << 12)
        | (_bits(raw_word, 20, 20) << 11)
        | (_bits(raw_word, 21, 30) << 1),
        21,
    )

    result = {
        "raw": raw_word,
        "op": "unknown",
        "rd": rd,
        "rs1": rs1,
        "rs2": rs2,
        "imm": 0,
        "reg_write": False,
        "mem_read": False,
        "mem_write": False,
        "branch": False,
        "jump": False,
        "assembly": "unknown",
    }

    if opcode == 0b0110011:
        if funct7 == 0b0000000 and funct3 == 0b000:
            result["op"] = "add"
        elif funct7 == 0b0100000 and funct3 == 0b000:
            result["op"] = "sub"
        elif funct7 == 0b0000000 and funct3 == 0b111:
            result["op"] = "and"
        elif funct7 == 0b0000000 and funct3 == 0b110:
            result["op"] = "or"
        elif funct7 == 0b0000000 and funct3 == 0b100:
            result["op"] = "xor"
        elif funct7 == 0b0000000 and funct3 == 0b001:
            result["op"] = "sll"
        elif funct7 == 0b0000000 and funct3 == 0b101:
            result["op"] = "srl"
        elif funct7 == 0b0100000 and funct3 == 0b101:
            result["op"] = "sra"
        elif funct7 == 0b0000000 and funct3 == 0b010:
            result["op"] = "slt"
        elif funct7 == 0b0000000 and funct3 == 0b011:
            result["op"] = "sltu"
        elif funct7 == 0b0000001 and funct3 == 0b000:
            result["op"] = "mul"
        elif funct7 == 0b0000001 and funct3 == 0b001:
            result["op"] = "mulh"
        elif funct7 == 0b0000001 and funct3 == 0b100:
            result["op"] = "div"
        elif funct7 == 0b0000001 and funct3 == 0b101:
            result["op"] = "divu"
        elif funct7 == 0b0000001 and funct3 == 0b110:
            result["op"] = "rem"
        elif funct7 == 0b0000001 and funct3 == 0b111:
            result["op"] = "remu"
        else:
            raise ValueError(f"지원하지 않는 R-type 명령어: funct7={funct7:07b}, funct3={funct3:03b}")
        result["reg_write"] = True
        result["assembly"] = f"{result['op']} {_register_name(rd)}, {_register_name(rs1)}, {_register_name(rs2)}"

    elif opcode == 0b0010011:
        if funct3 == 0b000:
            result["op"] = "addi"
        elif funct3 == 0b111:
            result["op"] = "andi"
        elif funct3 == 0b110:
            result["op"] = "ori"
        elif funct3 == 0b100:
            result["op"] = "xori"
        elif funct3 == 0b010:
            result["op"] = "slti"
        elif funct3 == 0b011:
            result["op"] = "sltiu"
        elif funct3 == 0b001 and funct7 == 0b0000000:
            result["op"] = "slli"
        elif funct3 == 0b101 and funct7 == 0b0000000:
            result["op"] = "srli"
        elif funct3 == 0b101 and funct7 == 0b0100000:
            result["op"] = "srai"
        else:
            raise ValueError(f"지원하지 않는 I-type 명령어: funct7={funct7:07b}, funct3={funct3:03b}")
        result["imm"] = imm_i
        result["reg_write"] = True
        result["assembly"] = f"{result['op']} {_register_name(rd)}, {_register_name(rs1)}, {imm_i}"

    elif opcode == 0b0000011 and funct3 == 0b010:
        result["op"] = "lw"
        result["imm"] = imm_i
        result["rs1"] = rs1
        result["reg_write"] = True
        result["mem_read"] = True
        result["assembly"] = f"lw {_register_name(rd)}, {imm_i}({_register_name(rs1)})"

    elif opcode == 0b0100011 and funct3 == 0b010:
        result["op"] = "sw"
        result["imm"] = imm_s
        result["rs1"] = rs1
        result["rs2"] = rs2
        result["mem_write"] = True
        result["assembly"] = f"sw {_register_name(rs2)}, {imm_s}({_register_name(rs1)})"

    elif opcode == 0b1100011:
        branch_ops = {
            0b000: "beq",
            0b001: "bne",
            0b100: "blt",
            0b101: "bge",
            0b110: "bltu",
            0b111: "bgeu",
        }
        if funct3 not in branch_ops:
            raise ValueError(f"지원하지 않는 Branch 명령어: funct3={funct3:03b}")
        result["op"] = branch_ops[funct3]
        result["imm"] = imm_b
        result["branch"] = True
        result["assembly"] = f"{result['op']} {_register_name(rs1)}, {_register_name(rs2)}, {imm_b}"

    elif opcode == 0b0110111:
        result["op"] = "lui"
        result["imm"] = imm_u
        result["reg_write"] = True
        result["assembly"] = f"lui {_register_name(rd)}, {imm_u}"

    elif opcode == 0b0010111:
        result["op"] = "auipc"
        result["imm"] = imm_u
        result["reg_write"] = True
        result["assembly"] = f"auipc {_register_name(rd)}, {imm_u}"

    elif opcode == 0b1101111:
        result["op"] = "jal"
        result["imm"] = imm_j
        result["reg_write"] = True
        result["branch"] = True
        result["jump"] = True
        result["assembly"] = f"jal {_register_name(rd)}, {imm_j}"

    elif opcode == 0b1100111 and funct3 == 0b000:
        result["op"] = "jalr"
        result["imm"] = imm_i
        result["rs1"] = rs1
        result["reg_write"] = True
        result["branch"] = True
        result["jump"] = True
        result["assembly"] = f"jalr {_register_name(rd)}, {_register_name(rs1)}, {imm_i}"

    elif opcode == 0b1110011 and funct3 == 0b000 and raw_word == 0x00000073:
        result["op"] = "ecall"
        result["assembly"] = "ecall"

    else:
        raise ValueError(f"지원하지 않는 명령어: opcode={opcode:07b}, funct3={funct3:03b}, funct7={funct7:07b}")

    return result
