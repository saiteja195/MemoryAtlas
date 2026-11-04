"""Demo profiles ship as text-only database snapshots; a reset puts the snapshot back."""
import os
import shutil

from ..config import ROOT
from .registry import Profile
from .runtime import Runtimes


def snapshot_path(kind: str) -> str:
    return str(ROOT / "fixtures" / "profiles" / f"{kind}.db")


def restore(runtimes: Runtimes, profile: Profile) -> None:
    """Close the profile's runtime, replace its database with the snapshot and clear its model cache.

    The copy goes to a temporary name and is renamed into place, so the profile never holds a half-copied
    file. The next `Runtimes.get` opens the restored database on a fresh connection."""
    kind = profile.demo_kind
    if not kind:
        raise ValueError("not a demo profile")
    src = snapshot_path(kind)
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    with runtimes.exclusive(profile.profile_id):      # no request can rebuild the runtime on the old file meanwhile
        runtimes.evict(profile.profile_id)
        folder = runtimes.profile_dir(profile.profile_id)
        db = os.path.join(folder, "memoryatlas.db")
        for suffix in ("-wal", "-shm"):
            if os.path.exists(db + suffix):
                os.remove(db + suffix)
        shutil.rmtree(os.path.join(folder, "llmcache"), ignore_errors=True)
        tmp = db + ".tmp"
        shutil.copyfile(src, tmp)
        os.replace(tmp, db)
