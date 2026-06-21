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


def test_div_by_zero_returns_zero():
    result = execute({"op": "div"}, 5, 0)
    assert result["alu_result"] == 0


def test_rem_by_zero_returns_zero():
    result = execute({"op": "rem"}, 5, 0)
    assert result["alu_result"] == 0


def test_div_negative():
    result = execute({"op": "div"}, -7, 2)
    assert result["alu_result"] == -3


def test_rem_negative():
    result = execute({"op": "rem"}, -7, 2)
    assert result["alu_result"] == -1
