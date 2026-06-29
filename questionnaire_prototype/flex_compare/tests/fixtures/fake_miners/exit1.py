"""Fake miner that prints to stderr and exits with non-zero status."""
import sys

print("intentional failure", file=sys.stderr)
sys.exit(1)
