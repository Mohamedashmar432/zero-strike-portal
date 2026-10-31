import subprocess


def ping(host: str):
    return subprocess.run("ping -c 1 " + host, shell=True, capture_output=True)
