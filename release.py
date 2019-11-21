#!/usr/bin/python3

import os
import re
import sys

from contextlib import ExitStack, contextmanager
from debian.changelog import Changelog
from git import Repo
from git.exc import GitCommandError
from subprocess import run
from tempfile import NamedTemporaryFile


@contextmanager
def chdir(path):
    here = os.getcwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(here)


@contextmanager
def atomic(dst, encoding='utf-8'):
    """Open a temporary file for writing using the given encoding.

    The context manager returns an open file object, into which you can write
    text or bytes depending on the encoding it was opened with.  Upon exit,
    the temporary file is moved atomically to the destination.  If an
    exception occurs, the temporary file is removed.

    :param dst: The path name of the target file.
    :param encoding: The encoding to use for the open file.  If None, then
        file is opened in binary mode.
    """
    directory = os.path.dirname(dst)
    mode = 'wb' if encoding is None else 'wt'
    with ExitStack() as resources:
        fp = resources.enter_context(NamedTemporaryFile(
            mode=mode, encoding=encoding, dir=directory, delete=False))
        yield fp
        os.rename(fp.name, dst)


def update_changelog(repo, series, version):
    # Update d/changelog.
    with ExitStack() as resources:
        debian_changelog = os.path.join(
            repo.working_dir, 'debian', 'changelog')
        infp = resources.enter_context(
            open(debian_changelog, 'r', encoding='utf-8'))
        outfp = resources.enter_context(atomic(debian_changelog))
        changelog = Changelog(infp)
        changelog.distributions = series
        series_version = {
            'focal': '20.04',
            'eoan': '19.10',
            'disco': '19.04',
            'bionic': '18.04',
            'xenial': '16.04',
            }[series]
        new_version = '{}+{}ubuntu1'.format(version, series_version)
        changelog.version = new_version
        changelog.write_to_open_file(outfp)
    return new_version


def sru_tracking_bug(repo, sru):
    with ExitStack() as resources:
        debian_changelog = os.path.join(
            repo.working_dir, 'debian', 'changelog')
        infp = resources.enter_context(
            open(debian_changelog, 'r', encoding='utf-8'))
        outfp = resources.enter_context(atomic(debian_changelog))
        changelog = Changelog(infp)
        changelog.add_change('  * SRU tracking number LP: #{}'.format(sru))
        changelog.write_to_open_file(outfp)


def continue_abort(msg='Pausing'):
    print(msg)
    while True:
        answer = input('[c]ontinue, [a]bort? ')
        if answer == 'a':
            print('Aborting!  Fix things manually')
            sys.exit(1)
        elif answer == 'c':
            break


def tag_or_skip(repo, version):
    force = False
    while True:
        answer = input('[t]ag, [f]orce, or [s]kip? ')
        if answer == 's':
            return
        if answer in 'tf':
            if answer == 'f':
                force = True
            break
    repo.create_tag(version, force=force)


def munge_lp_bug_numbers(repo):
    debian_changelog = os.path.join(repo.working_dir, 'debian', 'changelog')
    with ExitStack() as resources:
        infp = resources.enter_context(
            open(debian_changelog, 'r', encoding='utf-8'))
        outfp = resources.enter_context(atomic(debian_changelog))
        changelog = Changelog(infp)
        # Iterate through every line in the top changelog block.  Because we
        # want to modify the existing LP bug numbers, and because the API
        # doesn't give us direct access to those lines, we need to pop the
        # hood, reach in, and manipulate them ourselves.
        for i, line in enumerate(changelog[0]._changes):
            munged = re.sub('LP: #([0-9]+)', 'LP:\\1', line)
            changelog[0]._changes[i] = munged
        changelog.write_to_open_file(outfp)


def make_source_package(working_dir):
    with chdir(working_dir):
        run(['gbp', 'buildpackage', '-S', '-us', '-uc', '--git-ignore-branch'])


def main():
    try:
        working_dir = sys.argv[1]
    except IndexError:
        working_dir = os.getcwd()
    repo = Repo(working_dir)
    assert not repo.bare
    # Start by modifying the master branch.
    print('Updating master...')
    repo.heads.master.checkout()
    # The version number.
    version = input('version: ')
    sru = input('SRU tracking bug: ')
    # Modify the snapcraft.yaml.
    snapcraft_yaml = os.path.join(working_dir, 'snapcraft.yaml')
    with ExitStack() as resources:
        infp = resources.enter_context(
            open(snapcraft_yaml, 'r', encoding='utf-8'))
        outfp = resources.enter_context(atomic(snapcraft_yaml))
        for line in infp:
            if line.startswith('version: '):
                print('version:', '{}+snap1'.format(version), file=outfp)
            else:
                outfp.write(line)
    new_version = update_changelog(repo, 'focal', version)
    continue_abort('Pausing for manual review and commit')
    tag_or_skip(repo, new_version)
    make_source_package(working_dir)
    # Now do the Eoan branch.
    repo.git.checkout('eoan')
    # This will almost certainly cause merge conflicts.
    try:
        repo.git.merge('master', '--no-commit')
    except GitCommandError:
        continue_abort('Resolve merge master->eoan conflicts manually')
    munge_lp_bug_numbers(repo)
    sru_tracking_bug(repo, sru)
    new_version = update_changelog(repo, 'eoan', version)
    continue_abort('Pausing for manual review and commit')
    tag_or_skip(repo, new_version)
    make_source_package(working_dir)
    # Now do the Disco branch.
    repo.git.checkout('disco')
    # This will almost certainly cause merge conflicts.
    try:
        repo.git.merge('master', '--no-commit')
    except GitCommandError:
        continue_abort('Resolve merge master->disco conflicts manually')
    munge_lp_bug_numbers(repo)
    sru_tracking_bug(repo, sru)
    new_version = update_changelog(repo, 'disco', version)
    continue_abort('Pausing for manual review and commit')
    tag_or_skip(repo, new_version)
    make_source_package(working_dir)
    # Now do the Bionic branch.
    repo.git.checkout('bionic')
    # This will almost certainly cause merge conflicts.
    try:
        repo.git.merge('master', '--no-commit')
    except GitCommandError:
        continue_abort('Resolve merge master->bionic conflicts manually')
    munge_lp_bug_numbers(repo)
    sru_tracking_bug(repo, sru)
    new_version = update_changelog(repo, 'bionic', version)
    continue_abort('Pausing for manual review and commit')
    tag_or_skip(repo, new_version)
    make_source_package(working_dir)
    # Now do the Xenial branch.
    repo.git.checkout('xenial')
    # This will almost certainly cause merge conflicts.
    try:
        repo.git.merge('master', '--no-commit')
    except GitCommandError:
        continue_abort('Resolve merge master->xenial conflicts manually')
    munge_lp_bug_numbers(repo)
    sru_tracking_bug(repo, sru)
    new_version = update_changelog(repo, 'xenial', version)
    continue_abort('Pausing for manual review and commit')
    tag_or_skip(repo, new_version)
    make_source_package(working_dir)
    # Back to master and create the snap.
    repo.heads.master.checkout()


if __name__ == '__main__':
    main()
