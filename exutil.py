#!/usr/bin/env python3.6
import argparse
import builtins
import os
import re
import shutil
import subprocess as sp
import sys
from contextlib import contextmanager
from functools import wraps
from glob import glob
from io import StringIO

import pytest

RGX_LIST = re.compile('[ ,;]')
opts = None


def print(*args, level=0, **kwargs):
    kwargs = dict(kwargs)
    if 'flush' not in kwargs:
        kwargs['flush'] = True
    if 'level' in kwargs:
        if opts.verbose < level:
            return
        del kwargs['level']
    return builtins.print(*args, **kwargs)


class CommandManager(object):
    def __init__(self):
        self.commands = []

    def register(self, function):
        self.commands.append(function)
        self.commands.sort(key=lambda f: f.__name__)
        return function

    def find_best(self, s):
        matches = [
            c for c in self.commands
            if c.__name__.startswith(s)
        ]
        if len(matches) == 1:
            return matches[0]
        elif len(matches) == 0:
            print(f"Unknown command '{s}''")
        else:
            print(f"Ambigious command '{s}'; choose from the following:")
            for match in matches:
                print(f'  {match.__name__}')
        sys.exit(1)

    def __iter__(self):
        return (f.__name__ for f in self.commands)


cmd_mgr = CommandManager()


class ExtendAction(argparse.Action):
    def __init__(self, option_strings, dest, **kwargs):
        super(ExtendAction, self).__init__(option_strings, dest, **kwargs)

    def __parse__(self, value):
        return value

    def __extend__(self, namespace, value):
        current = getattr(namespace, self.dest)
        if current is None:
            current = []
        parsed = RGX_LIST.split(value)
        current.extend(map(self.__parse__, parsed))
        setattr(namespace, self.dest, current)

    def __call__(self, parser, namespace, values, option_string=None):
        if isinstance(values, list):
            for value in values:
                self.__extend__(namespace, value)
        else:
            self.__extend__(namespace, values)


class CommandAction(ExtendAction):
    def __parse__(self, value):
        return cmd_mgr.find_best(value)


@contextmanager
def capture():
    oldout, olderr = sys.stdout, sys.stderr
    try:
        out = [StringIO(), StringIO()]
        sys.stdout, sys.stderr = out
        yield out
    finally:
        sys.stdout, sys.stderr = oldout, olderr
        out[0] = out[0].getvalue()
        out[1] = out[1].getvalue()


def task(action):
    def _dec(function):
        @wraps(function)
        def _wrapper(target, *args, **kwargs):
            print(f'{action.title()} {target}...', end='')
            try:
                if opts.verbose:
                    print()
                    function(target, *args, **kwargs)
                else:
                    with capture():
                        function(target, *args, **kwargs)
                print('Done')
            except sp.CalledProcessError as e:
                print(e.output.decode().strip())
                sys.exit(e.returncode)
            except SystemExit as e:
                print('Failed')
                sys.exit(e.code)
        return _wrapper
    return _dec


def terminal(*args):
    print(' '.join(args))
    sp.check_call(args, stderr=sp.STDOUT).decode().strip()


def exercism(*args):
    return terminal('exercism', *args)


def git(*args):
    return terminal('git', *args)


@cmd_mgr.register
@task('migrating')
def migrate(exercise):
    if os.path.isfile(os.path.join(exercise, '.solution.json')):
        print(f'{exercise} has already been migrated')
        return
    exercism('download', '-t', 'python', '-e', exercise)
    src_dir = '{}-2'.format(exercise)
    if not os.path.isdir(src_dir):
        solution_file = '{}.py'.format(exercise.replace('-', '_'))
        print(f'Restoring {solution_file}')
        git('checkout', '--', os.path.join(exercise, solution_file))
    else:
        for filename in (
            '.solution.json',
            'README.md',
            '{}_test.py'.format(exercise.replace('-', '_')),
        ):
            src = os.path.join(src_dir, filename)
            dst = os.path.join(exercise, filename)
            print(f'Copying {src}->{dst}')
            shutil.copy2(src, dst)
        print(f'Removing {src_dir}/')
        shutil.rmtree(src_dir)


@cmd_mgr.register
@task('testing')
def test(exercise):
    args = ['-x', exercise]
    if opts.timeout is not None:
        args.extend(('--timeout', opts.timeout))
    print(' '.join(['pytest', *args]))
    ret = pytest.main(args)
    return ret


@cmd_mgr.register
@task('submitting')
def submit(exercise):
    solution_file_name = '{}.py'.format(exercise.replace('-', '_'))
    solution_file_path = os.path.join(exercise, solution_file_name)
    exercism('submit', solution_file_path)


@cmd_mgr.register
@task('restoring')
def restore(exercise):
    print(f'Removing {exercise}/')
    shutil.rmtree(exercise)
    git('checkout', '--', exercise)


@cmd_mgr.register
@task('checking in')
def checkin(exercise):
    git('add', exercise)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='count')
    parser.add_argument('-i', '--ignore', action=ExtendAction, default=[])
    parser.add_argument('-t', '--timeout', type=int, help='pytest timeout')
    parser.add_argument(
        'command',
        action=CommandAction,
        help=','.join(list(cmd_mgr))
    )
    parser.add_argument('exercise', action=ExtendAction, nargs='+')
    opts = parser.parse_args()
    for pattern in opts.exercise:
        for ex in glob(pattern):
            if ex in opts.ignore:
                continue
            for command in opts.command:
                ret = command(ex)
                if ret not in {None, 0}:
                    sys.exit(ret)
