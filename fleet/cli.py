"""The `iterum` command: one word per fleet module, each run as `python -m` would.

`iterum <command> [args]` sets `sys.argv` and runs the module as `__main__`, so
every module keeps its own argument parsing. Output is line-buffered, in place
of `python -u`.
"""

import runpy
import sys

# command: (module, arguments put before the user's)
COMMANDS = {
    "run": ("fleet.run", ["--plan"]),
    "resume": ("fleet.run", ["--resume"]),
    "land": ("fleet.merge", []),
    "receiver": ("fleet.telemetry", []),
    "view": ("fleet.view", []),
    "budget": ("fleet.governor", []),
    "recovery": ("fleet.recovery", []),
    "worker": ("fleet.worker", []),
    "dlq": ("fleet.dlq", []),
    "conflicts": ("fleet.conflicts", []),
    "approve": ("fleet.approve", []),
    "freeze": ("fleet.approve", ["freeze"]),
    "thaw": ("fleet.approve", ["thaw"]),
    "canary": ("fleet.canary", []),
    "sync": ("fleet.sync", []),
    "project": ("fleet.project", []),
    "doctor": ("fleet.doctor", []),
    "eval": ("fleet.eval", []),
    "scorecard": ("fleet.scorecard", []),
    "sweep": ("fleet.sweep", []),
}

DRILLS = {
    "run": "fleet.run",
    "kill": "fleet.kill_drill",
    "claims": "fleet.claims_drill",
    "merge": "fleet.merge_drill",
}


def usage() -> str:
    """The command list `iterum --help` prints."""
    lines = ["usage: iterum <command> [args]", "", "commands:"]
    lines += [f"  {name:<12} python -m {module} {' '.join(prefix)}".rstrip()
              for name, (module, prefix) in COMMANDS.items()]
    lines += [f"  {'drill ' + name:<12} python -m {module}" for name, module in DRILLS.items()]
    lines += ["", "iterum <command> --help shows that module's own help."]
    return "\n".join(lines)


def resolve(args: list[str]) -> tuple[str, list[str]]:
    """Map `iterum` arguments to a module name and the argv it should see."""
    name, rest = args[0], args[1:]
    if name == "drill":
        if not rest or rest[0] not in DRILLS:
            raise SystemExit(f"usage: iterum drill {{{','.join(DRILLS)}}}")
        return DRILLS[rest[0]], rest[1:]
    if name not in COMMANDS:
        raise SystemExit(f"iterum: unknown command {name!r}\n\n{usage()}")
    module, prefix = COMMANDS[name]
    if name == "sync" and not rest:
        rest = ["sync"]
    if prefix[:1] in (["--plan"], ["--resume"]) and (not rest or rest[0].startswith("-")):
        prefix = []
    return module, prefix + rest


def main() -> None:
    """Entry point for the `iterum` script."""
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(usage())
        return
    module, argv = resolve(sys.argv[1:])
    sys.argv = [f"iterum {sys.argv[1]}", *argv]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
