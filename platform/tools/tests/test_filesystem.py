import pytest
from tools.filesystem import FilesystemTool


@pytest.fixture
def fs(tmp_path):
    return FilesystemTool(str(tmp_path))


def test_write_and_read(fs, tmp_path):
    assert fs.write_file("hello.txt", "world").success
    r = fs.read_file("hello.txt")
    assert r.success
    assert r.output == "world"


def test_write_creates_parent_dirs(fs, tmp_path):
    assert fs.write_file("a/b/c.txt", "deep").success
    assert (tmp_path / "a" / "b" / "c.txt").exists()


def test_list_directory(fs, tmp_path):
    (tmp_path / "file.txt").write_text("x")
    (tmp_path / "subdir").mkdir()
    r = fs.list_directory(".")
    assert r.success
    assert "file.txt" in r.output
    assert "subdir" in r.output


def test_create_directory(fs, tmp_path):
    r = fs.create_directory("new/nested")
    assert r.success
    assert (tmp_path / "new" / "nested").is_dir()


def test_delete_file(fs, tmp_path):
    (tmp_path / "bye.txt").write_text("bye")
    assert fs.delete_file("bye.txt").success
    assert not (tmp_path / "bye.txt").exists()


def test_delete_directory_blocked(fs, tmp_path):
    (tmp_path / "dir").mkdir()
    r = fs.delete_file("dir")
    assert not r.success
    assert "cannot remove" in r.error


def test_file_exists_true(fs, tmp_path):
    (tmp_path / "yes.txt").write_text("y")
    r = fs.file_exists("yes.txt")
    assert r.success
    assert r.metadata["exists"] is True


def test_file_exists_false(fs):
    r = fs.file_exists("no_such_file.txt")
    assert r.success
    assert r.metadata["exists"] is False


def test_get_file_info(fs, tmp_path):
    (tmp_path / "data.txt").write_text("1234")
    r = fs.get_file_info("data.txt")
    assert r.success
    assert r.metadata["type"] == "file"
    assert r.metadata["size"] == 4


def test_path_traversal_read_rejected(fs):
    r = fs.read_file("../../etc/passwd")
    assert not r.success
    assert "outside" in r.error


def test_path_traversal_write_rejected(fs):
    r = fs.write_file("../escape.txt", "bad")
    assert not r.success


def test_path_traversal_delete_rejected(fs):
    r = fs.delete_file("../something")
    assert not r.success


def test_execute_dispatch(fs, tmp_path):
    r = fs.execute({"op": "write_file", "path": "dispatch.txt", "content": "ok"})
    assert r.success
    r2 = fs.execute({"op": "read_file", "path": "dispatch.txt"})
    assert r2.output == "ok"


def test_execute_unknown_op(fs):
    r = fs.execute({"op": "explode"})
    assert not r.success
    assert "Unknown op" in r.error
