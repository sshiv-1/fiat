from pathlib import Path

import pytest


@pytest.fixture
def sample_repository(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'sample'\n")
    (tmp_path / ".gitignore").write_text("ignored/\n*.secret\n")
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "a.py").write_text(
        "from . import b\n\n"
        "@decorator\n"
        "def collision_detector(vehicle: str) -> bool:\n"
        "    return b.is_colliding(vehicle)\n"
    )
    (package / "b.py").write_text(
        "from . import a\n\n"
        "class VehicleService:\n"
        "    def is_colliding(self, vehicle: str) -> bool:\n"
        "        return False\n\n"
        "def is_colliding(vehicle: str) -> bool:\n"
        "    return False\n"
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_collision.py").write_text(
        "from pkg.a import collision_detector\n\n"
        "def test_collision_detector():\n"
        "    assert collision_detector('car') is False\n"
    )
    frontend = tmp_path / "frontend" / "src"
    frontend.mkdir(parents=True)
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "1.0"}}')
    (frontend / "Widget.tsx").write_text(
        "import { collision_detector } from '../../pkg/a';\n"
        "export const CollisionPanel = () => <div />;\n"
        "export class Dashboard {\n"
        "  render() { return CollisionPanel(); }\n"
        "}\n"
    )
    (tmp_path / "broken.py").write_text("def broken(:\n")
    ignored = tmp_path / "ignored"
    ignored.mkdir()
    (ignored / "ignored.py").write_text("def ignored(): pass\n")
    (tmp_path / "asset.bin").write_bytes(b"\x00\x01\x02")
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "client.generated.py").write_text("def generated(): pass\n")
    return tmp_path
