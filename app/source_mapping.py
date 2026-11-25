"""Attach source metadata only to instruction addresses covered by DWARF."""
from bisect import bisect_left
from pathlib import PurePosixPath


def enrich_source_mapping(elf, mapping):
    addresses = sorted(int(key, 16) for key in mapping)
    by_address = {int(key, 16): value for key, value in mapping.items()}
    symbols = elf.get_section_by_name('.symtab')
    if symbols:
        for symbol in symbols.iter_symbols():
            if symbol['st_info']['type'] != 'STT_FUNC' or not symbol['st_size']:
                continue
            start = symbol['st_value']
            end = start + symbol['st_size']
            for address in addresses[bisect_left(addresses, start):bisect_left(addresses, end)]:
                by_address[address]['function'] = symbol.name
    if not elf.has_dwarf_info():
        return
    dwarf = elf.get_dwarf_info()
    for unit in dwarf.iter_CUs():
        lines = dwarf.line_program_for_CU(unit)
        if lines is None:
            continue
        files = lines.header['file_entry']
        previous = None
        for entry in lines.get_entries():
            current = entry.state
            if current is None:
                continue
            if previous is not None and not previous.end_sequence and previous.line and previous.line > 0 and current.address > previous.address:
                index = previous.file if lines.header.version >= 5 else previous.file - 1
                if 0 <= index < len(files):
                    raw = files[index].name
                    name = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else str(raw)
                    user_source = PurePosixPath(name.replace('\\', '/')).name == 'source.c'
                    for address in addresses[bisect_left(addresses, previous.address):bisect_left(addresses, current.address)]:
                        by_address[address].update({
                            'source_file': name,
                            'source_line': previous.line if user_source else None,
                            'external_source_line': None if user_source else previous.line,
                            'source_column': previous.column or None,
                            'mapping_basis': 'elf_dwarf',
                        })
            previous = current
