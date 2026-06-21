"""
ELF/raw instruction 검증 모듈.

시뮬레이션 전에 모든 instruction word를 decode하여 지원 범위를 확인한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Iterable, List, Optional
import argparse

from elftools.elf.elffile import ELFFile

from app.decoder import decode


@dataclass(frozen=True)
class InstructionValidationError:
    address: int
    raw_word: int
    reason: str
    code: str = "UNSUPPORTED_INSTRUCTION"

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "address": f"0x{self.address & 0xFFFFFFFF:08X}",
            "raw_word": f"0x{self.raw_word & 0xFFFFFFFF:08X}",
            "message": self.reason,
            "reason": self.reason,
        }


class ProgramValidationError(ValueError):
    def __init__(self, errors: List[InstructionValidationError]):
        self.errors = errors
        preview = "; ".join(
            f"{error.to_dict()['address']} {error.to_dict()['raw_word']}: {error.reason}"
            for error in errors[:5]
        )
        suffix = "" if len(errors) <= 5 else f"; ... {len(errors) - 5} more"
        super().__init__(f"지원하지 않는 명령어가 있습니다: {preview}{suffix}")


def _iter_words_from_bytes(data: bytes, base_addr: int = 0) -> Iterable[tuple[int, int]]:
    for offset in range(0, len(data), 4):
        chunk = data[offset : offset + 4]
        if len(chunk) < 4:
            chunk = chunk.ljust(4, b"\x00")
        yield base_addr + offset, int.from_bytes(chunk, "little", signed=False)


def _text_words_from_elf(program_bytes: bytes) -> Optional[List[tuple[int, int]]]:
    try:
        elf = ELFFile(BytesIO(program_bytes))
    except Exception:
        return None

    text = elf.get_section_by_name(".text")
    if text is None:
        return []
    return list(_iter_words_from_bytes(text.data(), text["sh_addr"]))


def validate_instruction_words(words: Iterable[tuple[int, int]]) -> List[InstructionValidationError]:
    errors = []
    for address, raw_word in words:
        try:
            decode(raw_word)
        except ValueError as exc:
            errors.append(
                InstructionValidationError(
                    address=address,
                    raw_word=raw_word,
                    reason=str(exc),
                )
            )
    return errors


def validate_program(program_bytes: bytes, *, raise_on_error: bool = False) -> List[InstructionValidationError]:
    words = _text_words_from_elf(program_bytes)
    if words is None:
        words = list(_iter_words_from_bytes(program_bytes))
    elif not words:
        errors = [
            InstructionValidationError(
                address=0,
                raw_word=0,
                reason="ELF에 .text 섹션이 없습니다.",
                code="MISSING_TEXT_SECTION",
            )
        ]
        if raise_on_error:
            raise ProgramValidationError(errors)
        return errors

    errors = validate_instruction_words(words)
    if errors and raise_on_error:
        raise ProgramValidationError(errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an ArchReactor RV32IM ELF or raw instruction file.")
    parser.add_argument("input", help="ELF or raw instruction file to validate.")
    args = parser.parse_args()

    with open(args.input, "rb") as f:
        errors = validate_program(f.read())

    if errors:
        print("status: validation_error")
        print("Unsupported instructions:")
        for error in errors:
            item = error.to_dict()
            print(f"- [{item['code']}] {item['address']} {item['raw_word']}: {item['message']}")
        return 1

    print("status: validation_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
