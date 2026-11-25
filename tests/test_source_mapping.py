from types import SimpleNamespace
import pytest
from app.source_mapping import enrich_source_mapping


@pytest.mark.parametrize('version', [4, 5])
def test_runtime_invalid_files_and_zero_length_ranges_are_not_user_c(version):
    class Header(dict):
        pass
    header = Header(file_entry=[SimpleNamespace(name=b'start.S'), SimpleNamespace(name=b'/tmp/source.c'), SimpleNamespace(name=b'not-source.c')])
    header.version = version
    offset = 0 if version == 5 else 1
    def state(address, line, file, end=False):
        return SimpleNamespace(address=address, line=line, column=2, file=file, end_sequence=end)
    states = [state(0x10000, 1, offset), state(0x10004, 99, 1 + offset),
              state(0x10004, 2, 1 + offset), state(0x10008, 1, 2 + offset),
              state(0x1000c, 3, 999), state(0x10010, 0, 0, True)]
    class Lines:
        def __init__(self): self.header = header
        def get_entries(self): return [SimpleNamespace(state=s) for s in states]
    class Dwarf:
        def iter_CUs(self): return [None]
        def line_program_for_CU(self, unit): return Lines()
    class Elf:
        def get_section_by_name(self, name): return None
        def has_dwarf_info(self): return True
        def get_dwarf_info(self): return Dwarf()
    mapping = {f'0x{address:08X}': {} for address in range(0x10000, 0x10014, 4)}
    enrich_source_mapping(Elf(), mapping)
    assert mapping['0x00010000']['source_file'] == 'start.S'
    assert mapping['0x00010000']['source_line'] is None
    assert mapping['0x00010000']['external_source_line'] == 1
    assert mapping['0x00010004']['source_line'] == 2
    assert mapping['0x00010008']['source_line'] is None
    assert 'source_line' not in mapping['0x0001000C']
    assert 'source_line' not in mapping['0x00010010']
