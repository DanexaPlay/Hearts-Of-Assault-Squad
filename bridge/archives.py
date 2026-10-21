"""Share read-only native archive indexes for one generation, then close all."""
from contextlib import contextmanager,ExitStack
from contextvars import ContextVar
from pathlib import Path
import zipfile
from .core import BridgeError

_active=ContextVar('hmb_native_archive_session',default=None)


def identity(path):
    stat=path.stat()
    return stat.st_size,stat.st_mtime_ns,stat.st_ino


@contextmanager
def archive_session():
    if _active.get() is not None:
        yield
        return
    with ExitStack() as stack:
        entries={};token=_active.set((entries,stack))
        try:
            yield
            for path,(stamp,_) in entries.items():
                if identity(path)!=stamp:raise BridgeError('Native archive changed during mission generation: '+path.name)
        finally:_active.reset(token)


@contextmanager
def open_archive(filename):
    state=_active.get()
    if state is None:
        with zipfile.ZipFile(filename) as archive:yield archive
        return
    entries,stack=state;path=Path(filename).resolve();stamp=identity(path)
    if path in entries:
        previous,archive=entries[path]
        if previous!=stamp:raise BridgeError('Native archive changed during mission generation: '+path.name)
    else:
        archive=stack.enter_context(zipfile.ZipFile(path));entries[path]=(stamp,archive)
    yield archive
