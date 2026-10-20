"""Fake command runner only: these tests never open a serial device."""
from types import SimpleNamespace
import pytest
from scripts import camera_chip_id as chip


def test_read_only_sequence_and_reset_policy():
    calls=[]
    def run(command,**kwargs):
        calls.append(command);return SimpleNamespace(returncode=0,stdout="FAKE ROM ID",stderr="")
    assert chip.identify("COM99",runner=run,emit=lambda s:None)==0
    assert [c[-1] for c in calls]==["chip-id","flash-id"]
    for command in calls:
        assert command[command.index("--before")+1]=="no-reset"
        assert command[command.index("--after")+1]=="no-reset"
        assert "--no-stub" in command
        assert command[command.index("--chip")+1]=="esp32"


def test_failure_never_attempts_flash_id():
    calls=[];output=[]
    def run(command,**kwargs):
        calls.append(command);return SimpleNamespace(returncode=2,stdout="FAKE timeout",stderr="")
    assert chip.identify("COM99",runner=run,emit=output.append)==1
    assert len(calls)==1 and "FAIL:" in output[-1]


def test_ambiguous_or_missing_port_is_not_guessed():
    a=SimpleNamespace(device="COM8",vid=0x1A86,pid=0x55D4)
    b=SimpleNamespace(device="COM9",vid=0x1A86,pid=0x55D4)
    with pytest.raises(ValueError):chip.select_port([a,b])
    with pytest.raises(ValueError):chip.select_port([],"COM9")
    assert chip.select_port([a,b],"com9")=="COM9"


def test_host_timeout_is_fail_without_retry():
    import subprocess
    calls=[]
    def run(command,**kwargs):
        calls.append(command);raise subprocess.TimeoutExpired(command,60)
    assert chip.identify("COM99",runner=run,emit=lambda s:None)==1
    assert len(calls)==1


def test_no_serial_data_prints_ranked_checks_without_another_hardware_command():
    output=[];calls=[]
    def run(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=2,stdout="",stderr="ERROR: No serial data received.")
    assert chip.identify("COM99",runner=run,emit=output.append)==1
    assert len(calls)==1 and calls[0][-1]=="chip-id"
    assert [line[:2] for line in output if line[:2] in ("1.","2.","3.","4.","5.")]==["1.","2.","3.","4.","5."]
    assert any("LOCAL ECHO OFF" in line for line in output)
    assert any("NEVER connect both" in line for line in output)
