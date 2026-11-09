#!/usr/bin/env python3
# Copyright 2026 Johan Ubbink
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Cognitive complexity of ros_tui's own Python (complexipy), as a hotspot list or a ratchet.

    scripts/complexity.py              # list every function over the limit
    scripts/complexity.py --diff main  # fail on a changed function over the limit that is new
                                       # or got more complex than at the merge base with main

Runs on the host, not in the Docker image: it needs complexipy on PATH, or uv (it then runs
``uvx complexipy``). Tests and the vendored stack are not measured. See docs/agentic-dev.md.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 15  # complexipy's default
MEASURED = ('ros_tui/', 'scripts/', 'docker/')
SKIPPED = ('ros_tui/_vendor/',)


def complexipy():
    if shutil.which('complexipy'):
        return ['complexipy']
    if shutil.which('uvx'):
        return ['uvx', '--quiet', 'complexipy']
    sys.exit('complexity.py: needs complexipy on PATH, or uv (pip install complexipy)')


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


def measured(path):
    return path.endswith('.py') and path.startswith(MEASURED) and not path.startswith(SKIPPED)


def scores(paths, cwd):
    """{(path, function): cognitive complexity} for the repo-relative paths that exist under cwd."""
    paths = [p for p in paths if (cwd / p).exists()]
    if not paths:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / 'report.json'
        subprocess.run([*complexipy(), *paths, '--output-format', 'json',
                        '--output', str(report), '-q', '-i'],
                       cwd=cwd, check=True, capture_output=True)
        rows = json.loads(report.read_text())
    out = {}
    for row in rows:
        key = (row['path'], row['function_name'])
        out[key] = max(row['complexity'], out.get(key, 0))
    return out


def scores_at(commit, paths):
    """scores() of the paths as they were at commit; files that did not exist yet are absent."""
    with tempfile.TemporaryDirectory() as tmp:
        old_root = Path(tmp)
        for path in paths:
            shown = subprocess.run(['git', 'show', f'{commit}:{path}'], cwd=ROOT,
                                   capture_output=True)
            if shown.returncode == 0:
                (old_root / path).parent.mkdir(parents=True, exist_ok=True)
                (old_root / path).write_bytes(shown.stdout)
        return scores(paths, old_root)


def over(table):
    return {key: score for key, score in table.items() if score > LIMIT}


def hotspots():
    paths = [p for p in git('ls-files').split() if measured(p)]
    found = sorted(over(scores(paths, ROOT)).items(), key=lambda kv: -kv[1])
    print(f'Cognitive complexity over {LIMIT}: {len(found)} function(s)')
    for (path, name), score in found:
        print(f'  {score:3d}  {path}  {name}')
    return True


def ratchet(ref):
    base = git('merge-base', ref, 'HEAD').strip()
    changed = git('diff', '--name-only', base).split()
    untracked = git('ls-files', '--others', '--exclude-standard').split()
    paths = sorted(p for p in set(changed + untracked) if measured(p))
    old, new = scores_at(base, paths), scores(paths, ROOT)
    worse = {k: v for k, v in over(new).items() if v > old.get(k, 0)}
    better = {k: (old[k], v) for k, v in new.items() if k in old and v < old[k]}
    print(f'Complexity ratchet vs {ref} (merge base {base[:8]}), {len(paths)} changed file(s):')
    for (path, name), score in sorted(worse.items(), key=lambda kv: -kv[1]):
        was = old.get((path, name))
        print(f"  FAIL {score:3d} > {LIMIT}  {path}  {name}  ({'new' if was is None else f'was {was}'})")
    for (path, name), (was, now) in sorted(better.items()):
        print(f'  better  {was} -> {now}  {path}  {name}')
    if not worse:
        print('  ok: no changed function is over the limit and worse than before')
    return not worse


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--diff', metavar='REF',
                        help='gate the functions changed since the merge base with REF')
    args = parser.parse_args()
    ok = ratchet(args.diff) if args.diff else hotspots()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
