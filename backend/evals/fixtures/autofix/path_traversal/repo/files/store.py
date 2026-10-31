import os

BASE_DIR = "/srv/uploads"


def read_upload(name: str) -> bytes:
    with open(os.path.join(BASE_DIR, name), "rb") as fh:
        return fh.read()
