"""
executor 모듈 테스트.
ALU 연산이 RV32IM 규격에 따라 올바르게 동작하는지 검증한다.
"""

from app.executor import execute


def test_add_wraps_32bit():
    result = execute({"op": "add"}, 0x7FFFFFFF, 1)
    assert result["alu_result"] == -2147483648


def test_mul_signed():
    result = execute({"op": "mul"}, -2, 3)
    assert result["alu_result"] == -6


def test_mul_high_variants():
    assert execute({"op": "mulh"}, -2, 3)["alu_result"] == -1
    assert execute({"op": "mulhsu"}, -2, 3)["alu_result"] == -1
    assert execute({"op": "mulhu"}, 0xFFFFFFFF, 2)["alu_result"] == 1


def test_div_by_zero_returns_minus_one():
    result = execute({"op": "div"}, 5, 0)
    assert result["alu_result"] == -1


def test_rem_by_zero_returns_dividend():
    result = execute({"op": "rem"}, 5, 0)
    assert result["alu_result"] == 5


def test_div_negative():
    result = execute({"op": "div"}, -7, 2)
    assert result["alu_result"] == -3


def test_rem_negative():
    result = execute({"op": "rem"}, -7, 2)
    assert result["alu_result"] == -1


def test_branch_compares_32bit_bit_patterns():
    assert execute({"op": "beq"}, 0xFFFFFFFF, -1)["alu_result"] == 1
    assert execute({"op": "bne"}, 0xFFFFFFFF, -1)["alu_result"] == 0
