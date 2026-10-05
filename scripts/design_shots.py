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

"""Render reference screenshots of the design prototype (docs/design/hybrid-keys.html).

    scripts/design_shots.py                      # every shot in docs/design/reference_shots.json
    scripts/design_shots.py echo-frozen home     # just these
    scripts/design_shots.py --keys '/,a,d,d' --name my-search   # an ad-hoc key sequence

Runs on the host (not in Docker): it needs Google Chrome or Chromium. Each shot opens the page
with ``#keys=…`` (the prototype plays those keys into its terminal on load) in headless Chrome at
1440x900 and saves ``test/artifacts/design/<name>.png``, plus a ``manifest.md`` listing the keys and
what each shot shows. See docs/agentic-dev.md.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN = REPO_ROOT / 'docs' / 'design' / 'hybrid-keys.html'
REFERENCES = REPO_ROOT / 'docs' / 'design' / 'reference_shots.json'
OUTPUT = REPO_ROOT / 'test' / 'artifacts' / 'design'
WINDOW = '1440,900'
KEY_DELAY_MS = 120  # The page's default pause between keys.
SETTLE_MS = 1000  # Virtual time after the last key: the page's 250 ms clock renders, a 1.6 s toast still shows.
CHROMES = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser')


def find_chrome(explicit: str | None) -> str:
    for candidate in ([explicit] if explicit else CHROMES):
        path = shutil.which(candidate)
        if path:
            return path
    sys.exit(f'no Chrome found (tried {", ".join(CHROMES)}); pass --chrome')


def page_url(keys: list[str]) -> str:
    url = DESIGN.as_uri()
    return f'{url}#keys={",".join(quote(key, safe="") for key in keys)}' if keys else url


def time_budget_ms(keys: list[str]) -> int:
    waits = sum(int(key[4:]) for key in keys if key.startswith('wait') and key[4:].isdigit())
    return (len(keys) + 1) * KEY_DELAY_MS + waits + SETTLE_MS


def render(chrome: str, keys: list[str], output: Path) -> None:
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            [
                chrome, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
                '--no-default-browser-check', f'--user-data-dir={profile}', f'--window-size={WINDOW}',
                f'--virtual-time-budget={time_budget_ms(keys)}', f'--screenshot={output}', page_url(keys),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('names', nargs='*', help='shots from reference_shots.json (default: all)')
    parser.add_argument('--keys', help='an ad-hoc comma-separated key sequence (with --name)')
    parser.add_argument('--name', default='adhoc', help='file name for --keys')
    parser.add_argument('--out', type=Path, default=OUTPUT)
    parser.add_argument('--chrome', help='Chrome/Chromium binary')
    args = parser.parse_args()

    if args.keys is not None:
        shots = [{'name': args.name, 'keys': [k for k in args.keys.split(',') if k], 'shows': '(ad hoc)'}]
    else:
        shots = json.loads(REFERENCES.read_text())
        if args.names:
            unknown = set(args.names) - {shot['name'] for shot in shots}
            if unknown:
                sys.exit(f'unknown shots: {", ".join(sorted(unknown))}')
            shots = [shot for shot in shots if shot['name'] in args.names]

    chrome = find_chrome(args.chrome)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = ['# Design reference shots', '', f'From `{DESIGN.relative_to(REPO_ROOT)}`.', '']
    for shot in shots:
        output = args.out / f'{shot["name"]}.png'
        render(chrome, shot['keys'], output)
        keys = ' '.join(f'`{key}`' for key in shot['keys']) or '(none)'
        manifest += [f'## {shot["name"]}', '', f'- keys: {keys}', f'- shows: {shot["shows"]}',
                     f'- file: {output.name}', '']
        print(output)
    (args.out / 'manifest.md').write_text('\n'.join(manifest))
    print(args.out / 'manifest.md')


if __name__ == '__main__':
    main()
