import re
from typing import Iterable

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

# https://pip.pypa.io/en/stable/reference/requirements-file-format/#comments
# There are two types of comments:
# 1. lines that begins with `#` are comments, e.g., # type 1 comment
# 2. Whitespace followed by a # in a line, e.g., abc # type 2 comment
COMMENT_RE = re.compile(r"(^|\s+)#.*$")


def join_lines(lines: list[str]) -> Iterable[str]:
    """Deal with [line continuations](https://pip.pypa.io/en/stable/reference/requirements-file-format/#line-continuations). Code adapted from [pip](https://github.com/pypa/pip/blob/ffbf6f0ce61170d6437ad5ff3a90086200ba9e2a/src/pip/_internal/req/req_file.py#L481)

    Parameters
    ----------
    lines : list[str]
        a list where each element corresponds to a line in the original requirements.txt file

    Returns
    -------
    Iterable[str]
        a generator producing joined lines
    """
    new_line: list[str] = []
    for line in lines:
        if not line.endswith("\\") or COMMENT_RE.match(line):
            if COMMENT_RE.match(line):
                # this ensures comments are always matched later
                line = " " + line
            if new_line:
                new_line.append(line)
                yield "".join(new_line)
                new_line = []
            else:
                yield line
        else:
            new_line.append(line.strip("\\"))

    # last line contains \
    if new_line:
        yield "".join(new_line)


def ignore_comments(lines: Iterable[str]) -> Iterable[str]:
    """Strips comments and filter empty lines. Code adapted from [pip](https://github.com/pypa/pip/blob/ffbf6f0ce61170d6437ad5ff3a90086200ba9e2a/src/pip/_internal/req/req_file.py#L512)

    Parameters
    ----------
    lines : list[str]
        a generator of lines produced by `join_lines`

    Returns
    -------
    Iterable[str]
        a generator producing non-empty and non-comment lines
    """
    for line in lines:
        line = COMMENT_RE.sub("", line)
        line = line.strip()
        if line:
            yield line


def preprocess(content: str) -> Iterable[str]:
    lines = content.splitlines()
    lines = join_lines(lines)
    lines = ignore_comments(lines)
    return lines


def get_args(line: str) -> str:
    """Get the arguments in each requirement line. Code adapted from [pip](https://github.com/pypa/pip/blob/ffbf6f0ce61170d6437ad5ff3a90086200ba9e2a/src/pip/_internal/req/req_file.py#L436)"""
    tokens = line.split(" ")
    args = []
    for token in tokens:
        if token.startswith("-") or token.startswith("--"):
            break
        else:
            args.append(token)
    return " ".join(args)


def parse_requirements(content: str) -> dict[str, str]:
    """Parse requirements.txt to extract dependencies

    Parameters
    ----------
    content : str
        the content of a requirements.txt file

    Returns
    -------
    dict[str, str]
        a dict where each key is the dependency's canonicalized name and the value is the dependency's specifier
    """
    requirements: dict[str, str] = {}

    for line in preprocess(content):
        try:
            args = get_args(line)
            if not args:
                continue
            req = Requirement(args)
            # The existence of url suggests that this library is not from PyPI,
            # therefore we skip it.
            if req.url is not None:
                continue
            name = canonicalize_name(req.name)
            specifier = str(req.specifier) if req.specifier else ""
            requirements[name] = specifier
        except InvalidRequirement:
            continue

    return requirements
