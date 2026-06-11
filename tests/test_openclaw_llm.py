import json
import subprocess

from app import llm
from app.config import CONFIG


def test_parse_openclaw_json_direct_payload():
    raw = json.dumps({"payloads": [{"text": "ok"}]})
    assert llm._parse_openclaw_json(raw)["payloads"][0]["text"] == "ok"


def test_parse_openclaw_json_with_log_prefix():
    raw = "warning line\n" + json.dumps({"result": {"payloads": [{"text": "ok"}]}}) + "\ntrace"
    assert llm._parse_openclaw_json(raw)["result"]["payloads"][0]["text"] == "ok"


def test_openclaw_command_prefers_path_executable(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda name: "C:/bin/openclaw.cmd" if name == "openclaw" else None)
    assert llm._openclaw_command() == ["C:/bin/openclaw.cmd"]


def test_openclaw_command_falls_back_to_powershell_shim(monkeypatch):
    def fake_which(name):
        if name == "pwsh":
            return "C:/Program Files/PowerShell/7/pwsh.exe"
        return None

    monkeypatch.setattr(llm.shutil, "which", fake_which)
    monkeypatch.setattr(llm.os.path, "expanduser", lambda _: "C:/Users/test")
    monkeypatch.setattr(llm.os.path, "exists", lambda path: path.endswith("openclaw.ps1"))

    cmd = llm._openclaw_command()
    assert cmd[:3] == ["C:/Program Files/PowerShell/7/pwsh.exe", "-NoProfile", "-ExecutionPolicy"]
    assert cmd[-1].endswith("openclaw.ps1")


def test_generate_openclaw_reply_extracts_result_payload(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_openclaw_agent", "main")
    monkeypatch.setattr(CONFIG, "llm_openclaw_model", "")
    monkeypatch.setattr(CONFIG, "llm_openclaw_timeout", 30)
    monkeypatch.setattr(llm, "_openclaw_command", lambda: ["openclaw"])
    monkeypatch.setattr(llm, "_track_usage", lambda account_key, kind: None)

    def fake_run(cmd, **kwargs):
        assert cmd[:4] == ["openclaw", "agent", "--agent", "main"]
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"result": {"payloads": [{"text": "Здравствуйте!"}]}}),
            stderr="",
        )

    monkeypatch.setattr(llm.subprocess, "run", fake_run)

    result = llm._generate_openclaw_reply(
        [
            {"role": "system", "content": "Отвечай кратко."},
            {"role": "user", "content": "Здравствуйте, удобно созвониться?"},
        ],
        account_key="test",
    )

    assert result == "Здравствуйте!"


def test_generate_openclaw_reply_accepts_plain_text(monkeypatch):
    monkeypatch.setattr(CONFIG, "llm_openclaw_agent", "main")
    monkeypatch.setattr(CONFIG, "llm_openclaw_model", "")
    monkeypatch.setattr(CONFIG, "llm_openclaw_timeout", 30)
    monkeypatch.setattr(llm, "_openclaw_command", lambda: ["openclaw"])
    monkeypatch.setattr(llm, "_track_usage", lambda account_key, kind: None)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="Готов обсудить детали.", stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)

    result = llm._generate_openclaw_reply(
        [{"role": "user", "content": "Здравствуйте"}],
        account_key="test",
    )

    assert result == "Готов обсудить детали."
