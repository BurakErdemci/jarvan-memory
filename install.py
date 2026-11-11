"""Install jarvan-memory. Run with Python 3.9+:  python install.py --help"""
import os
import sys

if sys.version_info < (3, 9):
    sys.exit("jarvan-memory needs Python 3.9 or newer; this is " + sys.version.split()[0])
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jarvan_memory import installer  # noqa: E402

if __name__ == "__main__":
    sys.exit(installer.main(sys.argv[1:]))
