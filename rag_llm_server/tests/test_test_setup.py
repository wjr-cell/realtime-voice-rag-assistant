from pathlib import Path

import services


def test_server_root_is_importable():
    expected_services_path = Path(__file__).resolve().parents[1] / "services"
    assert Path(services.__file__).resolve().parent == expected_services_path
