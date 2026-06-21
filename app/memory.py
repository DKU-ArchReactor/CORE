"""
메모리 접근 모듈.

Virtual memory 구조를 dictionary로 지원한다.
"""

from __future__ import annotations


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
