"""VIRA command line entry point.

Currently exposes the first-run doctor::

    python -m vira doctor
"""
import sys

USAGE = """VIRA command line

Usage:
  python -m vira doctor [--json] [--url URL] [--config PATH] [--no-docker]
  python -m vira --help
"""


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    command, rest = args[0], args[1:]
    if command == "doctor":
        from vira.doctor import main as doctor_main

        return doctor_main(rest)
    print(f"Unknown command: {command}\n\n{USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
