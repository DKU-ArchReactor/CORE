"""
memory 모듈 테스트.
byte/halfword/word 단위 가상 메모리 접근을 검증한다.
"""

from app.memory import (
    load_byte,
    load_halfword,
    load_word,
    store_byte,
    store_halfword,
    store_word,
)


def test_byte_access_preserves_neighbor_bytes():
    mem = {}
    store_word(mem, 0x1000, 0x11223344)
    store_byte(mem, 0x1001, 0xAA)

    assert load_word(mem, 0x1000) == 0x1122AA44
    assert load_byte(mem, 0x1001, signed=False) == 0xAA
    assert load_byte(mem, 0x1001, signed=True) == -86


def test_halfword_access_preserves_neighbor_halfword():
    mem = {}
    store_word(mem, 0x1000, 0x11223344)
    store_halfword(mem, 0x1002, 0xBEEF)

    assert load_word(mem, 0x1000) == 0xBEEF3344
    assert load_halfword(mem, 0x1002, signed=False) == 0xBEEF
    assert load_halfword(mem, 0x1002, signed=True) == -16657
