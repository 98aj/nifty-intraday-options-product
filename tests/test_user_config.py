from bot import user_config as uc


def test_read_editable_has_core_fields(cfg):
    vals = uc.read_editable(cfg)
    # Only two user-facing fields are exposed.
    assert "capital.total" in vals
    assert "capital.lots" in vals
    assert set(uc.EDITABLE) == {"capital.total", "capital.lots"}


def test_apply_sets_live_and_skips_unknown(cfg):
    applied = uc.validate_and_apply(cfg, {
        "capital.total": 750000,
        "capital.lots": 3,
        "bogus.key": 1,
        "capital.total_typo": 9,
        # fields no longer editable from the UI must be ignored
        "capital.max_risk_per_trade_pct": 2.5,
        "instrument.lot_size": 50,
    })
    assert applied["capital.total"] == 750000.0
    assert cfg.capital.total == 750000.0           # applied live
    assert applied["capital.lots"] == 3
    assert cfg.capital.lots == 3                    # applied live
    assert "bogus.key" not in applied
    assert "capital.max_risk_per_trade_pct" not in applied   # backend-only now
    assert "instrument.lot_size" not in applied              # backend-only now


def test_values_are_clamped(cfg):
    applied = uc.validate_and_apply(cfg, {"capital.lots": 0})
    assert applied["capital.lots"] == 1            # min clamp
    applied = uc.validate_and_apply(cfg, {"capital.lots": 4.9})
    assert applied["capital.lots"] == 4            # coerced to int


def test_overrides_roundtrip(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(uc, "overrides_path",
                        lambda: tmp_path / "user_overrides.yaml")
    uc.save_overrides({"capital.total": 123456, "capital.lots": 2})
    ov = uc.load_overrides()
    assert ov["capital"]["total"] == 123456
    assert ov["capital"]["lots"] == 2
