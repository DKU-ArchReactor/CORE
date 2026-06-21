import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.state import create_state
from app.simulator import run_simulation
from app.validator import ProgramValidationError


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the ArchReactor RV32IM simulator on an ELF input file."
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=Path("tests/program.elf"),
        help="Path to the input ELF file to simulate.",
    )
    parser.add_argument(
        "--max-clocks",
        "--max-cycles",
        "-m",
        dest="max_clocks",
        type=int,
        default=2000,
        help="Maximum number of clocks to run before stopping.",
    )
    parser.add_argument(
        "--mode",
        "-o",
        choices=["single", "pipeline"],
        default="single",
        help="Simulation mode to use when creating state.",
    )
    parser.add_argument(
        "--history",
        "-H",
        action="store_true",
        help="Print clock-by-clock history snapshots.",
    )
    parser.add_argument(
        "--history-json",
        action="store_true",
        help="Print history as JSON.",
    )
    parser.add_argument(
        "--output-dir",
        "-d",
        type=Path,
        default=Path("results"),
        help="Directory to create and save JSON output files.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"Input file not found: {args.input}")

    elf_bytes = args.input.read_bytes()
    try:
        create_state("prog", elf_bytes, mode=args.mode)
    except ProgramValidationError as exc:
        print("status: validation_error")
        print("Unsupported instructions:")
        for error in exc.errors:
            item = error.to_dict()
            print(f"- [{item['code']}] {item['address']} {item['raw_word']}: {item['message']}")
        raise SystemExit(1)

    result = run_simulation("prog", max_cycles=args.max_clocks)

    print(f"status: {result.get('status')}")
    print(f"console_output:\n{result.get('console_output', '')}")
    print(f"clocks: {len(result.get('history', []))}")

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = args.output_dir / "simulation_result.json"
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"Saved JSON result to: {output_path}")
    elif args.history_json:
        print(json.dumps(result, indent=2))
    elif args.history:
        for cycle in result.get("history", []):
            print(f"--- clock {cycle['clock']} ---")
            print("BUFFERS:")
            for stage_name, stage_buffer in cycle.get("buffers", {}).items():
                if stage_buffer is None:
                    print(f"  {stage_name}: bubble")
                else:
                    print(f"  {stage_name}: {stage_buffer['assembly']} ({stage_buffer['status']}) flush={stage_buffer['flush_info']}")
            print("IF:", cycle["if_stage"]["assembly"], cycle["if_stage"]["status"], cycle["if_stage"]["flush_info"])
            print("ID:", cycle["id_stage"]["assembly"], cycle["id_stage"]["status"])
            print("EX:", cycle["ex_stage"]["assembly"], cycle["ex_stage"]["status"])
            print("MEM:", cycle["mem_stage"]["assembly"], cycle["mem_stage"]["status"])
            print("WB:", cycle["wb_stage"]["assembly"], cycle["wb_stage"]["status"])
            print()


if __name__ == "__main__":
    main()
