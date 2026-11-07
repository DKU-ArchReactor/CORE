"""Compare v1 with frozen BE baseline and verify checked-in generated stubs."""
import pathlib
import subprocess
import sys
import tempfile
from google.protobuf.descriptor_pb2 import FileDescriptorSet
ROOT = pathlib.Path(__file__).resolve().parents[1]


def assert_compatible(old, new):
    current = {f.name: f for f in new.file}
    for original in old.file:
        candidate = current[original.name]
        assert original.package == candidate.package
        for group in ('message_type', 'enum_type', 'service'):
            index = {item.name: item for item in getattr(candidate, group)}
            for item in getattr(original, group):
                other = index[item.name]
                if group == 'message_type':
                    fields = {f.number: f for f in other.field}
                    for field in item.field:
                        assert fields[field.number] == field, f'Breaking field: {item.name}.{field.name}'
                elif group == 'enum_type':
                    values = {v.name: v.number for v in other.value}
                    assert all(values.get(v.name) == v.number for v in item.value)
                else:
                    methods = {m.name: m for m in other.method}
                    assert all(methods.get(m.name) == m for m in item.method)


def main():
    old = FileDescriptorSet.FromString((ROOT / 'proto/v1-baseline.pb').read_bytes())
    new = FileDescriptorSet.FromString((ROOT / 'proto/contract.pb').read_bytes())
    assert_compatible(old, new)
    with tempfile.TemporaryDirectory() as folder:
        subprocess.run([sys.executable, '-m', 'grpc_tools.protoc', '-I' + str(ROOT / 'proto'),
            '--python_out=' + folder, '--grpc_python_out=' + folder,
            '--descriptor_set_out=' + folder + '/contract.pb', '--include_imports',
            str(ROOT / 'proto/archreactor/v1/simulation.proto')], check=True)
        assert pathlib.Path(folder, 'contract.pb').read_bytes() == (ROOT / 'proto/contract.pb').read_bytes()
        for suffix in ('_pb2.py', '_pb2_grpc.py'):
            generated = pathlib.Path(folder, 'archreactor/v1/simulation' + suffix).read_text()
            generated = generated.replace('from archreactor.v1 import', 'from archreactor_contract.v1 import')
            assert generated == (ROOT / 'archreactor_contract/v1' / ('simulation' + suffix)).read_text()
    print('v1 wire compatibility and generated code: PASS')


if __name__ == '__main__':
    main()
