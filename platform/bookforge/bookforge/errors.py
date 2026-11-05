"""Exceptions raised by the bookforge library. The CLI turns them into exit code 1."""


class BookforgeError(Exception):
    """A problem the user can fix: bad input, missing file, wrong state."""


class ConfigError(BookforgeError):
    pass


class PromptError(BookforgeError):
    pass


class LayerError(BookforgeError):
    """A layer could not produce an acceptable result."""


class StateError(BookforgeError):
    pass


class VcsError(BookforgeError):
    pass
