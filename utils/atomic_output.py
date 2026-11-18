"""Stage encodes beside their destination so a failed save preserves the previous file."""

from contextlib import contextmanager, suppress
import os
import tempfile


@contextmanager
def staged_output(target):
    target = os.path.abspath(target)
    with tempfile.NamedTemporaryFile(
        dir=os.path.dirname(target), prefix=".a5-save-", suffix=os.path.splitext(target)[1],
        delete=False,
    ) as temp:
        path = temp.name
    try:
        yield path
        os.replace(path, target)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(path)
        raise
