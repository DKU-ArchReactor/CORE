"""
decoder 모듈 테스트.
명령어 파싱이 올바른 필드를 반환하는지 검증한다.
"""

from app.decoder import decode


def test_r_type_add():
    result = decode("add x3, x1, x2")
    assert result["op"] == "add"
    assert result["rd"] == 3
    assert result["rs1"] == 1
    assert result["rs2"] == 2
    assert result["reg_write"] is True
    assert result["branch"] is False


def test_i_type_addi():
    result = decode("addi x1, x0, 10")
    assert result["op"] == "addi"
    assert result["rd"] == 1
    assert result["rs1"] == 0
    assert result["imm"] == 10
    assert result["reg_write"] is True


def test_load_lw():
    result = decode("lw x5, 8(x2)")
    assert result["op"] == "lw"
    assert result["rd"] == 5
    assert result["rs1"] == 2
    assert result["imm"] == 8
    assert result["mem_read"] is True
    assert result["reg_write"] is True


def test_store_sw():
    result = decode("sw x5, 12(x2)")
    assert result["op"] == "sw"
    assert result["rs2"] == 5
    assert result["rs1"] == 2
    assert result["imm"] == 12
    assert result["mem_write"] is True
    assert result["reg_write"] is False


def test_branch_beq():
    result = decode("beq x1, x2, 8")
    assert result["op"] == "beq"
    assert result["rs1"] == 1
    assert result["rs2"] == 2
    assert result["imm"] == 8
    assert result["branch"] is True


def test_abi_register_names():
    result = decode("add a0, s0, t0")
    assert result["rd"] == 10
    assert result["rs1"] == 8
    assert result["rs2"] == 5
