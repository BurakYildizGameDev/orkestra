import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sorter")
    parser.add_argument("items", nargs="*")
    parser.add_argument("--numeric", action="store_true", help="sort as numbers")
    args = parser.parse_args(argv)
    key = float if args.numeric else str
    try:
        items = sorted(args.items, key=key)
    except ValueError:
        print("not a number", file=sys.stderr)
        return 2
    for item in items:
        print(item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
