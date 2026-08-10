from pathlib import Path
from .base import Tool, ToolResult


class FilesystemTool(Tool):
    def __init__(self, allowed_root: str):
        self._root = Path(allowed_root).resolve()

    @property
    def name(self) -> str:
        return "filesystem"

    @property
    def description(self) -> str:
        return "Scoped filesystem read/write within allowed_root"

    def _validate(self, path: str) -> Path:
        p = (self._root / path).resolve()
        if p != self._root and not p.is_relative_to(self._root):
            raise PermissionError(f"Path outside allowed root: {path!r}")
        return p

    def execute(self, params: dict) -> ToolResult:
        op = params.get("op")
        try:
            match op:
                case "read_file":        return self.read_file(params["path"])
                case "write_file":       return self.write_file(params["path"], params["content"])
                case "list_directory":   return self.list_directory(params["path"])
                case "create_directory": return self.create_directory(params["path"])
                case "delete_file":      return self.delete_file(params["path"])
                case "file_exists":      return self.file_exists(params["path"])
                case "get_file_info":    return self.get_file_info(params["path"])
                case _:                  return ToolResult(success=False, output="", error=f"Unknown op: {op}")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def read_file(self, path: str) -> ToolResult:
        return self._wrap(lambda: ToolResult(success=True, output=self._validate(path).read_text(encoding="utf-8")))

    def write_file(self, path: str, content: str) -> ToolResult:
        def _do():
            p = self._validate(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"Written: {p}")
        return self._wrap(_do)

    def list_directory(self, path: str) -> ToolResult:
        def _do():
            p = self._validate(path)
            entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
            return ToolResult(success=True, output="\n".join(f"{'d' if e.is_dir() else 'f'}  {e.name}" for e in entries))
        return self._wrap(_do)

    def create_directory(self, path: str) -> ToolResult:
        def _do():
            p = self._validate(path)
            p.mkdir(parents=True, exist_ok=True)
            return ToolResult(success=True, output=f"Created: {p}")
        return self._wrap(_do)

    def delete_file(self, path: str) -> ToolResult:
        def _do():
            p = self._validate(path)
            if p.is_dir():
                return ToolResult(success=False, output="", error="delete_file cannot remove directories — use terminal tool")
            p.unlink()
            return ToolResult(success=True, output=f"Deleted: {p}")
        return self._wrap(_do)

    def file_exists(self, path: str) -> ToolResult:
        try:
            exists = self._validate(path).exists()
        except (PermissionError, Exception):
            exists = False
        return ToolResult(success=True, output=str(exists), metadata={"exists": exists})

    def get_file_info(self, path: str) -> ToolResult:
        def _do():
            p = self._validate(path)
            st = p.stat()
            info = {"size": st.st_size, "modified": st.st_mtime, "type": "directory" if p.is_dir() else "file"}
            return ToolResult(success=True, output=str(info), metadata=info)
        return self._wrap(_do)

    @staticmethod
    def _wrap(fn) -> ToolResult:
        try:
            return fn()
        except PermissionError as e:
            return ToolResult(success=False, output="", error=str(e))
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
