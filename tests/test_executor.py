"""
executor 모듈 테스트.
ALU 연산이 올바른 결과를 반환하는지 검증한다.
"""

from app.executor import execute


def test_add():
    assert execute("add", 10, 20, 0) == 30


def test_sub():
    assert execute("sub", 30, 10, 0) == 20


def test_addi():
    assert execute("addi", 5, 0, 15) == 20


def test_and():
    assert execute("and", 0b1100, 0b1010, 0) == 0b1000


def test_or():
    assert execute("or", 0b1100, 0b1010, 0) == 0b1110


def test_slt_true():
    assert execute("slt", -1, 1, 0) == 1


def test_slt_false():
    assert execute("slt", 10, 5, 0) == 0


def test_lw_address():
    assert execute("lw", 100, 0, 8) == 108


def test_lui():
    assert execute("lui", 0, 0, 5) == 5 << 12


def test_overflow_wraps():
    """32비트 오버플로우가 올바르게 래핑되는지 확인."""
    result = execute("add", 0x7FFFFFFF, 1, 0)
    assert result == -2147483648  # signed 32-bit min
