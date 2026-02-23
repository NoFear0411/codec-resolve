#!/usr/bin/env python3
"""
Launcher for codec_resolve.

Place this file NEXT TO the codec_resolve/ directory and run:
    python run.py [options]

Or use the module form directly:
    python -m codec_resolve [options]

Both do the same thing.
"""
import runpy
import sys
import os

# Ensure the directory containing this script is on sys.path
# so that `codec_resolve` is importable as a package.
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

runpy.run_module("codec_resolve", run_name="__main__", alter_sys=True)
