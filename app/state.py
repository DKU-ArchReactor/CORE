"""
글로벌 딕셔너리 (Single Source of Truth) 관리 모듈.

모든 사용자 상태(가상 CPU)를 GLOBAL_DICT에서 관리한다.
user_id 하나 = 가상 CPU 한 대.
Backend에서 직접 함수 호출로 접근하므로 직렬화 오버헤드가 없다.
"""

from io import BytesIO
from typing import Optional

from elftools.elf.elffile import ELFFile

from app.validator import validate_program

# 모든 사용자의 CPU 상태를 담는 단일 진실 소스
GLOBAL_DICT = {}
DEFAULT_STACK_POINTER = 0x7FFFEFFC

REG_ALIASES = {
    0: "zero", 1: "ra", 2: "sp", 3: "gp", 4: "tp",
    5: "t0", 6: "t1", 7: "t2",
    8: "s0", 9: "s1", 10: "a0", 11: "a1", 12: "a2", 13: "a3", 14: "a4", 15: "a5",
    16: "a6", 17: "a7", 18: "s2", 19: "s3", 20: "s4", 21: "s5", 22: "s6", 23: "s7",
    24: "s8", 25: "s9", 26: "s10", 27: "s11", 28: "t3", 29: "t4", 30: "t5", 31: "t6",
}

REG_NAMES = [REG_ALIASES.get(i, f"x{i}") for i in range(32)]


def register_name(reg_num: int) -> str:
    return REG_NAMES[reg_num] if 0 <= reg_num < len(REG_NAMES) else f"x{reg_num}"


def _load_section_data(elf, section_name: str) -> dict:
    section = elf.get_section_by_name(section_name)
    if section is None:
        return {}

    raw_data = section.data()
    base_addr = section["sh_addr"]
    result = {}
    for offset in range(0, len(raw_data), 4):
        chunk = raw_data[offset : offset + 4]
        if len(chunk) < 4:
            chunk = chunk.ljust(4, b"\x00")
        result[base_addr + offset] = int.from_bytes(chunk, "little", signed=False)
    return result


def _load_zero_section(elf, section_name: str) -> dict:
    section = elf.get_section_by_name(section_name)
    if section is None:
        return {}

    base_addr = section["sh_addr"]
    size = section["sh_size"]
    result = {}
    for offset in range(0, size, 4):
        result[base_addr + offset] = 0
    return result


def _load_elf_sections(elf_bytes: bytes) -> tuple[int, dict, dict]:
    stream = BytesIO(elf_bytes)
    elf = ELFFile(stream)
    entry_point = elf.header["e_entry"]

    imem = _load_section_data(elf, ".text")
    if not imem:
        raise ValueError("ELF에 .text 섹션이 없습니다.")

    dmem = {}
    dmem.update(_load_section_data(elf, ".rodata"))
    dmem.update(_load_section_data(elf, ".data"))
    dmem.update(_load_section_data(elf, ".sdata"))
    dmem.update(_load_zero_section(elf, ".bss"))
    dmem.update(_load_zero_section(elf, ".sbss"))
    return entry_point, imem, dmem


def create_state(user_id: str, elf_bytes: bytes, mode: str = "single", validate: bool = True) -> dict:
    """
    새로운 사용자 상태(가상 CPU)를 초기화한다.

    Args:
        user_id: 사용자 고유 식별자
        elf_bytes: ELF 바이너리 데이터
        mode: 실행 모드 ("single" | "pipeline")
        validate: 실행 전 instruction 지원 범위 검증 여부
    """
    if validate:
        validate_program(elf_bytes, raise_on_error=True)

    try:
        entry_point, imem, dmem = _load_elf_sections(elf_bytes)
    except Exception:
        entry_point = 0
        imem = {}
        dmem = {}
        for offset in range(0, len(elf_bytes), 4):
            chunk = elf_bytes[offset : offset + 4]
            if len(chunk) < 4:
                chunk = chunk.ljust(4, b"\x00")
            imem[offset] = int.from_bytes(chunk, "little", signed=False)

    state = {
        "mode": mode,
        "entry_point": entry_point,
        "pc": entry_point,
        "imem": imem,
        "dmem": dmem,
        "regs": [0, 0, DEFAULT_STACK_POINTER, *([0] * 29)],
        "status": "ready",
        "halt_requested": False,
        "console_output": "",
        "forwarding_enabled": True,
        "recent_rds": [],
        "stats": {
            "total_cycles": 0,
            "instructions_executed": 0,
            "data_hazards": 0,
            "control_hazards": 0,
            "stalls": 0,
            "forwards": 0,
        },
        "history": [],
        "pipeline_regs": {
            "IF": None,
            "ID": None,
            "EX": None,
            "MEM": None,
            "WB": None,
        },
    }

    GLOBAL_DICT[user_id] = state
    return state


def get_state(user_id: str) -> Optional[dict]:
    """사용자 상태를 조회한다."""
    return GLOBAL_DICT.get(user_id)


def delete_state(user_id: str) -> bool:
    """사용자 상태를 삭제한다 (세션 종료)."""
    if user_id in GLOBAL_DICT:
        del GLOBAL_DICT[user_id]
        return True
    return False
