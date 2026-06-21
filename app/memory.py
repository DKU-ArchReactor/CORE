"""
메모리 접근 모듈.

Virtual memory 구조를 dictionary로 지원한다.
"""

from __future__ import annotations


def _word_addr(addr: int) -> int:
    return addr & ~0x3


def _aligned_addr(addr: int) -> int:
    if addr % 4 != 0:
        raise ValueError(f"메모리 주소가 4바이트 워드 정렬되지 않음: {addr:#010x}")
    return addr


def load_word(mem: dict, addr: int) -> int:
    addr = _aligned_addr(addr)
    return mem.get(addr, 0)


def store_word(mem: dict, addr: int, value: int) -> None:
    addr = _aligned_addr(addr)
    mem[addr] = value & 0xFFFFFFFF


def load_byte(mem: dict, addr: int, signed: bool = True) -> int:
    word = mem.get(_word_addr(addr), 0)
    value = (word >> ((addr & 0x3) * 8)) & 0xFF
    return value - 0x100 if signed and value & 0x80 else value


def load_halfword(mem: dict, addr: int, signed: bool = True) -> int:
    if addr % 2 != 0:
        raise ValueError(f"메모리 주소가 2바이트 하프워드 정렬되지 않음: {addr:#010x}")
    word = mem.get(_word_addr(addr), 0)
    value = (word >> ((addr & 0x2) * 8)) & 0xFFFF
    return value - 0x10000 if signed and value & 0x8000 else value


def store_byte(mem: dict, addr: int, value: int) -> None:
    word_addr = _word_addr(addr)
    shift = (addr & 0x3) * 8
    word = mem.get(word_addr, 0)
    word &= ~(0xFF << shift)
    word |= (value & 0xFF) << shift
    mem[word_addr] = word & 0xFFFFFFFF


def store_halfword(mem: dict, addr: int, value: int) -> None:
    if addr % 2 != 0:
        raise ValueError(f"메모리 주소가 2바이트 하프워드 정렬되지 않음: {addr:#010x}")
    word_addr = _word_addr(addr)
    shift = (addr & 0x2) * 8
    word = mem.get(word_addr, 0)
    word &= ~(0xFFFF << shift)
    word |= (value & 0xFFFF) << shift
    mem[word_addr] = word & 0xFFFFFFFF


def read_string(mem: dict, addr: int) -> str:
    output = []
    cur = addr
    while True:
        word = load_word(mem, cur)
        for i in range(4):
            ch = (word >> (i * 8)) & 0xFF
            if ch == 0:
                return "".join(output)
            output.append(chr(ch))
        cur += 4
