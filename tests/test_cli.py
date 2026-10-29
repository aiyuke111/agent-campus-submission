import json

from src.cli import main


def _request(**overrides):
    data = {
        "material_id": "M05",
        "publish_date": "2026-11-05",
        "publish_time": "20:00",
        "hard": True,
        "operator": "test",
    }
    data.update(overrides)
    return data


def test_cli_valid_request(tmp_path, capsys):
    req = tmp_path / "req.json"
    req.write_text(json.dumps(_request(), ensure_ascii=False), encoding="utf-8")
    code = main(["--request", str(req), "--store", str(tmp_path / "drafts.json"),
                 "--outdir", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert code == 0
    assert "NEEDS_CONFIRMATION" in captured.out
    assert (tmp_path / "out" / "req.result.json").exists()
    assert (tmp_path / "out" / "req.trace.json").exists()


def test_cli_accepts_utf8_bom(tmp_path, capsys):
    req = tmp_path / "bom.json"
    payload = json.dumps(_request(), ensure_ascii=False).encode("utf-8")
    req.write_bytes(b"\xef\xbb\xbf" + payload)
    code = main(["--request", str(req), "--store", str(tmp_path / "drafts.json")])
    assert code == 0
    assert "NEEDS_CONFIRMATION" in capsys.readouterr().out


def test_cli_malformed_json_returns_error(tmp_path, capsys):
    req = tmp_path / "bad.json"
    req.write_text("{ not valid json", encoding="utf-8")
    code = main(["--request", str(req), "--store", str(tmp_path / "drafts.json")])
    out = capsys.readouterr().out
    assert code == 2
    assert '"status": "ERROR"' in out


def test_cli_missing_file_returns_error(tmp_path, capsys):
    code = main(["--request", str(tmp_path / "nope.json"), "--store", str(tmp_path / "drafts.json")])
    assert code == 2
    assert "请求文件无法读取" in capsys.readouterr().out


def test_cli_empty_material_id_returns_needs_input(tmp_path, capsys):
    req = tmp_path / "empty.json"
    req.write_text(json.dumps(_request(material_id="")), encoding="utf-8")
    code = main(["--request", str(req), "--store", str(tmp_path / "drafts.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert "NEEDS_INPUT" in out


def test_cli_batch_runs_multiple_requests(tmp_path, capsys):
    req1 = tmp_path / "a.json"
    req2 = tmp_path / "b.json"
    req1.write_text(json.dumps(_request(), ensure_ascii=False), encoding="utf-8")
    req2.write_text(json.dumps(_request(material_id="M03", publish_time="19:00")), encoding="utf-8")
    code = main(["--request", str(req1), "--request", str(req2),
                 "--store", str(tmp_path / "drafts.json"), "--outdir", str(tmp_path / "out")])
    assert code == 0
    assert (tmp_path / "out" / "a.result.json").exists()
    assert (tmp_path / "out" / "b.result.json").exists()


def test_cli_unknown_material_returns_needs_input(tmp_path, capsys):
    req = tmp_path / "unknown.json"
    req.write_text(json.dumps(_request(material_id="M99")), encoding="utf-8")
    code = main(["--request", str(req), "--store", str(tmp_path / "drafts.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert "NEEDS_INPUT" in out
