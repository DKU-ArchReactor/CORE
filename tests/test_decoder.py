"""
decoder 모듈 테스트.
명령어 디코딩이 raw 32비트 워드에서 올바른 필드를 반환하는지 검증한다.
"""

from app.decoder import decode


def test_decode_add():
    raw = 0x00B50533  # add x10, x10, x11
    result = decode(raw)
    assert result["op"] == "add"
    assert result["rd"] == 10
    assert result["rs1"] == 10
    assert result["rs2"] == 11
    assert result["reg_write"] is True


def test_decode_mul():
    raw = 0x02B50533  # mul x10, x10, x11
    result = decode(raw)
    assert result["op"] == "mul"
    assert result["rd"] == 10
    assert result["rs1"] == 10
    assert result["rs2"] == 11
    assert result["reg_write"] is True


def test_decode_mul_high_variants():
    assert decode(0x02B51533)["op"] == "mulh"
    assert decode(0x02B52533)["op"] == "mulhsu"
    assert decode(0x02B53533)["op"] == "mulhu"


def test_decode_div_rem():
    raw_div = 0x02B54533  # div x10, x10, x11
    raw_rem = 0x02B56533  # rem x10, x10, x11
    assert decode(raw_div)["op"] == "div"
    assert decode(raw_rem)["op"] == "rem"


def test_decode_lw_sw():
    raw_lw = 0x0082A283  # lw x5, 8(x5)
    raw_sw = 0x00A2A423  # sw x10, 8(x5)
    assert decode(raw_lw)["op"] == "lw"
    assert decode(raw_sw)["op"] == "sw"


def test_decode_byte_halfword_load_store():
    assert decode(0x00130283)["op"] == "lb"   # lb x5, 1(x6)
    assert decode(0x00131283)["op"] == "lh"   # lh x5, 1(x6)
    assert decode(0x00134283)["op"] == "lbu"  # lbu x5, 1(x6)
    assert decode(0x00135283)["op"] == "lhu"  # lhu x5, 1(x6)
    assert decode(0x005300A3)["op"] == "sb"   # sb x5, 1(x6)
    assert decode(0x005310A3)["op"] == "sh"   # sh x5, 1(x6)


def test_decode_branch():
    raw = 0x00858663  # beq x11, x8, 8
    result = decode(raw)
    assert result["op"] == "beq"
    assert result["branch"] is True
