from services.startup_config import summarize_for_startup_log, validate_configuration


def _clear_all(monkeypatch):
    for var in [
        "AUTH_JWT_SECRET", "MASTERDB_STORAGE_DIR", "MASTERDB_DATABASE_URL",
        "MDU_BASE_URL", "MDU_API_KEY", "PRAVAH_BHIV_INSIGHT_FLOW_BRIDGE",
        "RATE_LIMIT_MAX_REQUESTS", "RATE_LIMIT_WINDOW_SECONDS",
    ]:
        monkeypatch.delenv(var, raising=False)


def test_reports_unset_auth_secret(monkeypatch):
    _clear_all(monkeypatch)
    report = validate_configuration()
    assert report["AUTH_JWT_SECRET"]["set"] is False
    assert "random" in report["AUTH_JWT_SECRET"]["note"]


def test_reports_in_memory_persistence_when_nothing_set(monkeypatch):
    _clear_all(monkeypatch)
    report = validate_configuration()
    assert report["persistence"]["mode"] == "in_memory"


def test_reports_no_persistence_key_when_database_url_set(monkeypatch):
    _clear_all(monkeypatch)
    monkeypatch.setenv("MASTERDB_DATABASE_URL", "postgresql://user:pass@host:5432/db")
    report = validate_configuration()
    assert "persistence" not in report
    assert report["MASTERDB_DATABASE_URL"]["set"] is True
    assert report["MASTERDB_DATABASE_URL"]["format"] == "set_and_well_formed"


def test_flags_malformed_database_url(monkeypatch):
    _clear_all(monkeypatch)
    monkeypatch.setenv("MASTERDB_DATABASE_URL", "not-a-url-at-all")
    report = validate_configuration()
    assert report["MASTERDB_DATABASE_URL"]["format"] == "set_but_malformed"


def test_flags_both_storage_dir_and_database_url_set(monkeypatch):
    _clear_all(monkeypatch)
    monkeypatch.setenv("MASTERDB_STORAGE_DIR", "storage/")
    monkeypatch.setenv("MASTERDB_DATABASE_URL", "sqlite:///x.db")
    report = validate_configuration()
    assert "priority" in report["MASTERDB_DATABASE_URL"]["note"]


def test_flags_partial_mdu_configuration(monkeypatch):
    _clear_all(monkeypatch)
    monkeypatch.setenv("MDU_BASE_URL", "https://mdu.example.test")
    report = validate_configuration()
    assert report["MDU_BASE_URL"]["set"] is True
    assert report["MDU_API_KEY"]["set"] is False
    assert "only one" in report["MDU_BASE_URL"]["note"]


def test_full_mdu_configuration_has_no_warning(monkeypatch):
    _clear_all(monkeypatch)
    monkeypatch.setenv("MDU_BASE_URL", "https://mdu.example.test")
    monkeypatch.setenv("MDU_API_KEY", "key123")
    report = validate_configuration()
    assert report["MDU_BASE_URL"].get("note") is None


def test_flags_invalid_rate_limit_values(monkeypatch):
    _clear_all(monkeypatch)
    monkeypatch.setenv("RATE_LIMIT_MAX_REQUESTS", "not-a-number")
    report = validate_configuration()
    assert report["RATE_LIMIT_MAX_REQUESTS"]["valid"] is False
    assert report["RATE_LIMIT_WINDOW_SECONDS"]["valid"] is False


def test_valid_rate_limit_values(monkeypatch):
    _clear_all(monkeypatch)
    monkeypatch.setenv("RATE_LIMIT_MAX_REQUESTS", "50")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "30")
    report = validate_configuration()
    assert report["RATE_LIMIT_MAX_REQUESTS"]["valid"] is True


def test_never_leaks_actual_secret_values(monkeypatch):
    _clear_all(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_SECRET", "super-secret-value-should-not-appear")
    monkeypatch.setenv("MDU_API_KEY", "another-secret-should-not-appear")
    report = validate_configuration()
    report_text = str(report)
    assert "super-secret-value-should-not-appear" not in report_text
    assert "another-secret-should-not-appear" not in report_text


def test_summarize_produces_readable_multiline_string(monkeypatch):
    _clear_all(monkeypatch)
    report = validate_configuration()
    summary = summarize_for_startup_log(report)
    assert "Configuration at startup:" in summary
    assert "AUTH_JWT_SECRET" in summary
