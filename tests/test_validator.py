"""
validator 모듈 테스트.
실행 전 instruction 지원 범위 검증을 확인한다.
"""

import pytest

from app.state import create_state
from app.validator import ProgramValidationError, validate_program


def test_validate_program_accepts_supported_raw_program():
    program = b"".join(
        word.to_bytes(4, "little")
        for word in (
            0x00100293,  # addi x5, zero, 1
            0x00000073,  # ecall
        )
    )

    assert validate_program(program) == []


def test_validate_program_reports_unsupported_instruction_address_and_word():
    errors = validate_program((0x00000000).to_bytes(4, "little"))

    assert len(errors) == 1
    assert errors[0].to_dict()["code"] == "UNSUPPORTED_INSTRUCTION"
    assert errors[0].to_dict()["address"] == "0x00000000"
    assert errors[0].to_dict()["raw_word"] == "0x00000000"
    assert errors[0].to_dict()["message"] == errors[0].reason
    assert "지원하지 않는 명령어" in errors[0].reason


def test_create_state_rejects_unsupported_program_before_execution():
    with pytest.raises(ProgramValidationError) as exc_info:
        create_state("bad", (0x00000000).to_bytes(4, "little"))

    assert len(exc_info.value.errors) == 1
