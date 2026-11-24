import builtins


_REAL_IMPORT = builtins.__import__
_REAL_OPEN = builtins.open
_REAL_GETATTR = builtins.getattr
_REAL_SETATTR = builtins.setattr
_REAL_DELATTR = builtins.delattr

_BLOCKED_BUILTINS = {
    "eval",
    "exec",
    "compile",
    "input",
    "breakpoint",
    "globals",
    "locals",
    "vars",
    "exit",
    "quit",
    "help",
    "license",
    "credits",
    "copyright",
    "__loader__",
    "__spec__",
}

_BLOCKED_ATTRS = {
    "__builtins__",
    "__globals__",
    "__subclasses__",
    "__loader__",
    "__spec__",
    "__import__",
    "__code__",
    "__closure__",
    "__func__",
    "__self__",
    "f_globals",
    "f_locals",
    "f_builtins",
    "f_back",
    "gi_frame",
    "cr_frame",
    "ag_frame",
    "tb_frame",
}
