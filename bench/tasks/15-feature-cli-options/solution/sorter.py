import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sorter")
    parser.add_argument("items", nargs="*")
    parser.add_argument("--numeric", action="store_true", help="sort as numbers")
    parser.add_argument("--reverse", action="store_true", help="descending order")
    parser.add_argument("--unique", action="store_true", help="drop repeated lines")
    args = parser.parse_args(argv)
    key = float if args.numeric else str
    items = list(dict.fromkeys(args.items)) if args.unique else list(args.items)
    try:
        items = sorted(items, key=key, reverse=args.reverse)
    except ValueError:
        print("not a number", file=sys.stderr)
        return 2
    for item in items:
        print(item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
