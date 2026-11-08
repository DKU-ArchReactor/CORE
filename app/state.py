"""
글로벌 딕셔너리 (Single Source of Truth) 관리 모듈.

모든 사용자 상태(가상 CPU)를 GLOBAL_DICT에서 관리한다.
user_id 하나 = 가상 CPU 한 대.
Backend에서 직접 함수 호출로 접근하므로 직렬화 오버헤드가 없다.
"""

from io import BytesIO
from hashlib import sha256
from typing import Optional

from elftools.elf.elffile import ELFFile

from app.validator import validate_program
from app.decoder import decode

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
    if mode not in ("single", "pipeline"):
        raise ValueError(f"Unsupported simulation mode: {mode}")
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

    # Preserve the pre-execution state and loaded ELF layout for consumers.
    state["initial_state"] = {
        "current_pc": f"0x{entry_point:08X}",
        "registers": {f"x{i}": f"0x{value:08X}" for i, value in enumerate(state["regs"])},
        "memory_snapshot": {f"0x{addr:08X}": f"0x{value:08X}" for addr, value in dmem.items()},
        "console_output": "",
        "metrics": {"accumulated_instructions": 0, "accumulated_stalls": 0, "accumulated_forwards": 0},
    }
    state["program_metadata"] = {
        "fingerprint": sha256(elf_bytes).hexdigest(),
        "instructions": [
            {"pc": f"0x{pc:08X}", "raw_instruction": f"0x{raw:08X}", "assembly": decode(raw)["assembly"]}
            for pc, raw in sorted(imem.items())
        ] if validate else [],
        "code_mapping": {
            f"0x{pc:08X}": {
                "assembly": decode(raw)["assembly"],
                "raw_instruction": f"0x{raw:08X}",
            }
            for pc, raw in sorted(imem.items())
        } if validate else {},
        "memory_regions": [],
        "initial_stack_pointer": f"0x{DEFAULT_STACK_POINTER:08X}",
    }
    if elf_bytes.startswith(b"\x7fELF"):
        elf = ELFFile(BytesIO(elf_bytes))
        for section in elf.iter_sections():
            if section["sh_flags"] & 2 and section["sh_size"]:
                start = section["sh_addr"]
                state["program_metadata"]["memory_regions"].append({
                    "name": section.name,
                    "start": f"0x{start:08X}",
                    "end_exclusive": f"0x{start + section['sh_size']:08X}",
                    "kind": "code" if section["sh_flags"] & 4 else ("bss" if section["sh_type"] == "SHT_NOBITS" else "data"),
                })
        if elf.has_dwarf_info():
            try:
                dwarfinfo = elf.get_dwarf_info()
                for cu in dwarfinfo.iter_CUs():
                    lineprog = dwarfinfo.line_program_for_CU(cu)
                    if lineprog is None:
                        continue
                    file_entries = lineprog["file_entry"] if "file_entry" in lineprog.header else []
                    entries = lineprog.get_entries()
                    prev_state = None
                    for entry in entries:
                        st = entry.state
                        if st is None:
                            continue
                        if prev_state and not prev_state.end_sequence and prev_state.line > 0:
                            is_source_c = False
                            try:
                                file_idx = prev_state.file - 1
                                if 0 <= file_idx < len(file_entries):
                                    f_entry = file_entries[file_idx]
                                    fname = f_entry.name.decode("utf-8", errors="ignore") if hasattr(f_entry, "name") else str(f_entry)
                                    if "source.c" in fname:
                                        is_source_c = True
                                elif not file_entries:
                                    is_source_c = True
                            except Exception:
                                is_source_c = True
                            if is_source_c:
                                curr_addr = prev_state.address
                                end_addr = st.address if st.address > curr_addr else curr_addr + 4
                                while curr_addr < end_addr:
                                    pc_key = f"0x{curr_addr & 0xFFFFFFFF:08X}"
                                    if pc_key in state["program_metadata"]["code_mapping"]:
                                        state["program_metadata"]["code_mapping"][pc_key]["source_line"] = prev_state.line
                                    curr_addr += 4
                        prev_state = st
            except Exception:
                pass

    state["program_metadata"]["memory_layout"] = _build_memory_layout(
        state["program_metadata"]["memory_regions"],
        state["program_metadata"]["code_mapping"],
        entry_point,
    )

    GLOBAL_DICT[user_id] = state
    return state


def _build_memory_layout(sections: list[dict], code_mapping: dict, entry_point: int) -> dict:
    """ELF 섹션과 DWARF 심볼을 종합하여 6대 가상 메모리 레이아웃 단일 진실 공급원(SSOT)을 구축한다."""
    code_sec = next((s for s in sections if s.get("kind") == "code"), None)
    data_sec = next((s for s in sections if s.get("kind") == "data"), None)
    bss_sec = next((s for s in sections if s.get("kind") == "bss"), None)

    code_start = code_sec["start"] if code_sec else "0x00010000"
    code_end = code_sec["end_exclusive"] if code_sec else "0x00010000"
    code_size = (int(code_end, 16) - int(code_start, 16)) if code_sec else 0

    data_start = data_sec["start"] if data_sec else "0x10000000"
    data_end = data_sec["end_exclusive"] if data_sec else data_start
    data_size = (int(data_end, 16) - int(data_start, 16)) if data_sec else 0

    bss_start = bss_sec["start"] if bss_sec else data_end
    bss_end = bss_sec["end_exclusive"] if bss_sec else bss_start
    bss_size = (int(bss_end, 16) - int(bss_start, 16)) if bss_sec else 0

    user_pcs = [
        pc for pc, info in sorted(code_mapping.items(), key=lambda kv: int(kv[0], 16))
        if info.get("source_line") is not None
    ]
    startup_pcs = [
        pc for pc, info in sorted(code_mapping.items(), key=lambda kv: int(kv[0], 16))
        if info.get("source_line") is None
    ]

    if user_pcs:
        user_start = user_pcs[0]
        user_end = user_pcs[-1]
        user_end_exclusive = f"0x{int(user_end, 16) + 4:08X}"
        user_count = len(user_pcs)
        entry_pt = user_start
    else:
        user_start = f"0x{entry_point:08X}"
        user_end = code_end
        user_end_exclusive = code_end
        user_count = len(code_mapping)
        entry_pt = user_start

    if startup_pcs and user_pcs:
        startup_start = startup_pcs[0]
        startup_end = startup_pcs[-1]
        startup_end_exclusive = f"0x{int(startup_end, 16) + 4:08X}"
        startup_count = len(startup_pcs)
    elif startup_pcs and not user_pcs:
        startup_start = startup_pcs[0]
        startup_end = startup_pcs[-1]
        startup_end_exclusive = f"0x{int(startup_end, 16) + 4:08X}"
        startup_count = len(startup_pcs)
    else:
        startup_start = "0x00010000"
        startup_end = "0x00010014"
        startup_end_exclusive = "0x00010014"
        startup_count = 0

    return {
        "stack": {
            "name": "Stack",
            "base": f"0x{DEFAULT_STACK_POINTER:08X}",
            "limit": "0x10008000",
            "growth": "down",
        },
        "heap": {
            "name": "Heap",
            "base": "0x10004000",
            "limit": "0x10008000",
            "growth": "up",
        },
        "bss": {
            "name": "BSS",
            "start": bss_start,
            "end_exclusive": bss_end,
            "size_bytes": bss_size,
        },
        "data": {
            "name": "Data",
            "start": data_start,
            "end_exclusive": data_end,
            "size_bytes": data_size,
        },
        "code": {
            "name": "Code",
            "start": code_start,
            "end_exclusive": code_end,
            "size_bytes": code_size,
            "runtime_startup": {
                "name": "System Runtime Startup (_start)",
                "start": startup_start,
                "end": startup_end,
                "end_exclusive": startup_end_exclusive,
                "instruction_count": startup_count,
            },
            "user_program": {
                "name": "User Program (main)",
                "start": user_start,
                "end": user_end,
                "end_exclusive": user_end_exclusive,
                "instruction_count": user_count,
                "entry_point": entry_pt,
            },
        },
        "reserved": {
            "name": "NULL",
            "start": "0x00000000",
            "end_exclusive": "0x00010000",
            "size_bytes": 65536,
            "desc": "NULL Pointer Guard (접근 금지 보호 구역)",
        },
        "boundary_dividers": [
            "0x10008000",
            "0x10004000",
            bss_start if bss_size > 0 else "0x10000000",
            data_start if data_size > 0 else "0x10000000",
            "0x00010000",
            "0x00000000",
        ],
    }


def get_state(user_id: str) -> Optional[dict]:
    """사용자 상태를 조회한다."""
    return GLOBAL_DICT.get(user_id)


def delete_state(user_id: str) -> bool:
    """사용자 상태를 삭제한다 (세션 종료)."""
    if user_id in GLOBAL_DICT:
        del GLOBAL_DICT[user_id]
        return True
    return False
