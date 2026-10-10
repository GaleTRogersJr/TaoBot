"""Launch GR Software Subnet Watch."""
from subnet_watch.app import run
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-launch", help=argparse.SUPPRESS)
    args = parser.parse_args()
    run(verify_output=args.verify_launch)
