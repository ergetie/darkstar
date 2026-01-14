"""
Security test: Path traversal prevention in SPA fallback handler.
"""
from pathlib import Path
import pytest
from fastapi import HTTPException
from backend.main import validate_path

def test_validate_path_traversal():
    """Verify validate_path raises 404 for traversal attempts."""
    # Create a dummy base structure
    # We don't need real files, just Path logic
    base_dir = Path("/tmp/static_test")
    
    # Logic is purely Path-based, so we can test with non-existent paths 
    # as long as we mock resolve behavior OR assume standard behavior.
    # Actually, .resolve() typically requires files to exist to resolve symlinks, 
    # but for ".." collapsing it handles it lexically in recent Pythons IF strict=False (default).
    # HOWEVER, strict containment check relies on .resolve() returning absolute path.
    
    # Better approach: Use a real temp dir for reliable .resolve() test
    pass

@pytest.fixture
def temp_static_dir(tmp_path):
    """Create a temporary static directory structure."""
    static = tmp_path / "static"
    static.mkdir()
    (static / "safe.txt").write_text("safe")
    (tmp_path / "secret.txt").write_text("secret")
    return static

def test_validate_path_safe(temp_static_dir):
    """Test legitimate file access."""
    # Should not raise
    resolved = validate_path(temp_static_dir, "safe.txt")
    assert resolved.name == "safe.txt"

def test_validate_path_traversal_blocked(temp_static_dir):
    """Test traversal to parent directory."""
    with pytest.raises(HTTPException) as exc:
        validate_path(temp_static_dir, "../secret.txt")
    assert exc.value.status_code == 404

def test_validate_path_traversal_deep(temp_static_dir):
    """Test deep traversal."""
    with pytest.raises(HTTPException) as exc:
        validate_path(temp_static_dir, "../../etc/passwd")
    assert exc.value.status_code == 404
