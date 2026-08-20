import os
import socket
from pathlib import Path

import pytest


def test_runner_is_non_root_read_only_and_offline() -> None:
    assert os.getuid() != 0
    with pytest.raises(OSError):
        Path("forbidden-write.txt").write_text("blocked")
    with socket.socket() as client:
        client.settimeout(0.2)
        with pytest.raises(OSError):
            client.connect(("1.1.1.1", 443))
