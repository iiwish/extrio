"""Bounded package pruning inside a disposable Debian image, never on the host."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ALLOWED = {'libxml2', 'libllvm19', 'libcups2t64', 'libegl-mesa0', 'libgl1-mesa-dri', 'libglx-mesa0',
           'mesa-libgallium', 'mesa-vulkan-drivers', 'mesa-va-drivers', 'mesa-vdpau-drivers'}


def removal_plan(output, essential):
    if re.search(r'^(Inst|Conf)\s', output, re.MULTILINE):
        raise ValueError('unexpected installation in removal plan')
    names = {m.partition(':')[0] for m in re.findall(r'^(?:Remv|Purg) ([a-z0-9][a-z0-9+.:-]*)', output, re.MULTILINE)}
    if not names or names - ALLOWED or names & essential:
        raise ValueError('unsafe or unknown removal plan: ' + ','.join(sorted(names)))
    return names


def full_browser_directory(root, executable):
    root, executable = Path(root), Path(executable)
    try:
        relative = executable.relative_to(root)
    except ValueError as exc:
        raise ValueError('unsafe browser path') from exc
    if not relative.parts:
        raise ValueError('unsafe browser path')
    directory = root / relative.parts[0]
    if (root.is_symlink() or not re.fullmatch(r'chromium-\d+', directory.name) or directory.is_symlink()
            or not executable.is_file() or not executable.resolve().is_relative_to(directory.resolve())):
        raise ValueError('unsafe browser path')
    return directory


def command(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=180, check=True,
                            env={**os.environ, 'LC_ALL': 'C'})
    return result.stdout


def packages():
    rows = command(['dpkg-query', '-W', '-f=${db:Status-Status}\t${binary:Package}\t${Essential}\n'])
    installed, essential = set(), set()
    for row in rows.splitlines():
        status, binary, required = row.split('\t')
        if status == 'installed':
            name = binary.partition(':')[0]
            installed.add(name)
            if required == 'yes':
                essential.add(name)
    return installed, essential


def prune(variant, *, plan_only=False):
    if (os.environ.get('EXTRIO_DISPOSABLE_IMAGE_BUILD') != '1' or sys.platform != 'linux' or os.geteuid() != 0
            or not Path('/opt/extrio/bin/python').is_file() or not Path('/app/backend/uv.lock').is_file()):
        raise RuntimeError('Pruning requires the disposable root build container')
    if variant == 'baseline':
        return {'variant': variant, 'removedPackages': []}
    before, essential = packages()
    roots = ['libcups2t64'] if variant == 'headless' else ['libxml2', 'libllvm19']
    if not set(roots) <= before:
        raise RuntimeError('expected baseline packages are absent')
    browser_directory = None
    if variant == 'headless':
        from playwright.sync_api import sync_playwright

        root = Path('/ms-playwright')
        shells = [p for p in root.glob('chromium_headless_shell-*/*/*')
                  if p.name in {'headless_shell', 'chrome-headless-shell'} and p.is_file()]
        if len(shells) != 1 or 'libcups.so' in command(['ldd', str(shells[0])]):
            raise RuntimeError('headless shell is absent, ambiguous or still requires libcups')
        with sync_playwright() as p:
            browser_directory = full_browser_directory(root, p.chromium.executable_path)
    simulated = command(['apt-get', '--simulate', 'purge', *roots])
    if plan_only:
        actions = {m.partition(':')[0] for m in re.findall(
            r'^(?:Remv|Purg) ([a-z0-9][a-z0-9+.:-]*)', simulated, re.MULTILINE)}
        blockers = actions - ALLOWED | actions & essential
        return {'variant': variant, 'planOnly': True, 'status': 'blocked' if blockers else 'eligible_for_review',
                'plannedPackages': sorted(actions), 'blockers': sorted(blockers), 'removedPackages': [], 'aptPlan': simulated}
    print(simulated, flush=True)
    planned = removal_plan(simulated, essential)
    if not set(roots) <= planned:
        raise RuntimeError('incomplete removal plan')
    print(command(['apt-get', 'purge', '-y', *roots]), flush=True)
    after, after_essential = packages()
    if before - after != planned or after - before or essential != after_essential or set(roots) & after:
        raise RuntimeError('package removal differs from the verified plan')
    if browser_directory:
        shutil.rmtree(browser_directory)
    return {'variant': variant, 'removedPackages': sorted(planned), 'essentialPackagesPreserved': True,
            'fullChromiumRemoved': browser_directory is not None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('variant', choices=['baseline', 'llvm', 'headless'])
    parser.add_argument('--plan', action='store_true')
    args = parser.parse_args()
    result = prune(args.variant, plan_only=args.plan)
    if not args.plan:
        target = Path('/usr/local/share/extrio/native-pruning.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
