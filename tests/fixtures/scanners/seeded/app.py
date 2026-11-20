"""Seeded-vulnerability fixture for scanner tests. Never imported."""

import pickle
import subprocess


def run(cmd):
    return subprocess.call(cmd, shell=True)


def load(blob):
    return pickle.loads(blob)
