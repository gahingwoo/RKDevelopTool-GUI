"""
Turn rkdeveloptool's failure output into a likely cause and what to do next.

The patterns are the messages rkdeveloptool actually prints (main.cpp,
RKComm.cpp in rockchip-linux/rkdeveloptool); the first match wins, so more
specific messages come first. Each kind has three translated strings in
i18n.py: err_<kind>_title, err_<kind>_causes and err_<kind>_actions (lines
separated by newlines). Output that matches nothing is left unexplained
rather than guessed at.
"""
import re

_PATTERNS = (
    ("too_many_devices", r"Found too many rockusb devices"),
    ("no_device", r"Did not find any rockusb device|not found any devices"),
    ("bad_arguments", r"Parameter of \[\w+\] command is invalid|command is invalid"),
    ("loader_upgrade", r"Upgrading loader failed|Device not support to upgrade the loader"
                       r"|Opening loader failed, exiting upgrade loader"),
    ("loader_download", r"Downloading bootloader failed|Opening loader failed, exiting download boot"
                        r"|parseLoader failed"),
    ("file_open", r"can't open file|Opening output file \(.*\) failed|Cannot get file size"),
    ("cannot_open", r"[Cc]reating [Cc]omm [Oo]bject failed|Creating device object failed"),
    ("write_failed", r"Write LBA failed|writing entry \(.*\) failed|Writing (parameter|master gpt|backup gpt) failed"),
    ("read_failed", r"Read LBA failed"),
    ("no_partition_table", r"Not found any partition table|Read GPT failed|Read parameter failed"),
    ("bad_parameter_file", r"Pars(e|ing) parameter failed"),
    ("storage_switch", r"Change Storage failed|Storage is invalid"),
    ("needs_loader", r"Reading Flash Info failed|Reading flash ID failed|Read Chip Info failed"
                     r"|Getting flash info from device failed|Read capability"),
)
_COMPILED = tuple((kind, re.compile(pattern)) for kind, pattern in _PATTERNS)

KINDS = tuple(kind for kind, _ in _PATTERNS)

# Kinds a missing Linux udev rule can cause.
PERMISSION_KINDS = ("no_device", "cannot_open")


def classify_failure(output):
    """The kind of failure rkdeveloptool's output shows, or None."""
    for kind, pattern in _COMPILED:
        if pattern.search(output or ""):
            return kind
    return None


def explain(tr, output, linux_permission_command=None):
    """(title, body) explaining a failure, or None when the output isn't
    recognised. linux_permission_command, when given, is added for the
    kinds a missing udev rule causes."""
    kind = classify_failure(output)
    if kind is None:
        return None
    causes = [line for line in tr(f"err_{kind}_causes").split("\n") if line]
    actions = [line for line in tr(f"err_{kind}_actions").split("\n") if line]
    if linux_permission_command and kind in PERMISSION_KINDS:
        causes.insert(0, tr("err_linux_permission_cause"))
        actions.insert(0, tr("err_linux_permission_action").format(linux_permission_command))
    body = (tr("err_causes_heading") + "\n" + "\n".join(f"• {c}" for c in causes) + "\n\n"
            + tr("err_actions_heading") + "\n"
            + "\n".join(f"{i}. {a}" for i, a in enumerate(actions, 1)))
    return tr(f"err_{kind}_title"), body
