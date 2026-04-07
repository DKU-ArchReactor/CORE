"""
메모리 접근 모듈.

Data Memory(dmem)에 대한 Load/Store 연산을 수행한다.
Non-Pipeline의 MEM 단계에 해당하며, Pipeline 확장 시 stage_mem()에서도 재사용한다.
"""


def memory_access(dmem: list, decoded: dict, alu_result: int, rs2_val: int) -> int | None:
    """
    메모리 Load/Store를 수행한다.

    Args:
        dmem: Data Memory 리스트
        decoded: 디코딩된 명령어 정보
        alu_result: ALU 연산 결과 (메모리 주소로 사용)
        rs2_val: rs2 레지스터 값 (Store 시 쓸 데이터)

    Returns:
        int | None: Load 시 읽은 값, Store나 메모리 미접근 시 None
    """
    if decoded["mem_read"]:
        # lw: word 단위 주소 (4바이트 정렬)
        addr = alu_result // 4
        if addr < 0 or addr >= len(dmem):
            raise IndexError(f"메모리 읽기 범위 초과: addr={alu_result} (index={addr})")
        return dmem[addr]

    if decoded["mem_write"]:
        # sw: word 단위 주소 (4바이트 정렬)
        addr = alu_result // 4
        if addr < 0 or addr >= len(dmem):
            raise IndexError(f"메모리 쓰기 범위 초과: addr={alu_result} (index={addr})")
        dmem[addr] = rs2_val
        return None

    return None
