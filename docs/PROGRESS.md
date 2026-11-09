# İlerleme

Her faz sonunda ajan bu dosyayı günceller. En yeni faz en üstte.

## Durum özeti

| Faz | Durum | Tarih | Not |
|---|---|---|---|
| 0 – İskelet + i18n altyapısı | ✅ | 2026-11-09 | Paket adı `orkestra-cli` (D-001) |
| 1 – Config | ⏳ | | |
| 2 – Chat adapter, ask, doctor | ⏳ | | |
| 3 – Durum, bütçe, onay | ⏳ | | |
| 4 – Router | ⏳ | | |
| 5a – Görev + doğrulama | ⏳ | | |
| 5b – Worktree | ⏳ | | |
| 5c – API ile edit | ⏳ | | |
| 6 – CLI ajanları | ⏳ | | |
| 7 – Batch + tahmin | ⏳ | | |
| 8a – status, şablon, önbellek, sayaç | ⏳ | | |
| 8b – review, map, plan expand | ⏳ | | |
| 9 – Skill | ⏳ | | |
| 10 – Şef devri | ⏳ | | |
| 11 – Arayüz, sihirbaz, 5 dil | ⏳ | | |
| 12 – Gece vardiyası, bildirim, öğrenen yönlendirme | ⏳ | | |
| 13 – Benchmark | ⏳ | | |
| 14 – Yayın | ⏳ | | |

## Faz kayıtları

### Faz 0 – Proje iskeleti + çok dilli altyapı (2026-11-09)
**Yapılanlar:**
- `uv` paketi, `src/` düzeni, `pyproject.toml` (paket adı `orkestra-cli`, komut `orkestra`, build backend `uv_build`), `uv.lock`.
- Bağımlılıklar: typer, pydantic, ruamel.yaml, httpx, openai, rich, psutil, jsonschema, pathspec. Dev: pytest, pytest-asyncio, respx, ruff, pyright (`[nodejs]` ekstrası, Node kurulu olmadan çalışsın diye).
- ruff (`E,F,I,B,UP,SIM,RUF`, satır 100), pyright (`basic`), pytest (`asyncio_mode = "auto"`, `live` işareti, varsayılan `-m "not live"`).
- `src/orkestra/`: `__init__.py` (`__version__ = "0.0.1"`), `__main__.py`, `cli.py` (`--version`, global `--lang`), `errors.py` (istisna hiyerarşisi + `ExitCode` + `exit_code_for`), `paths.py` (`ORKESTRA_HOME` ve türetilmiş yollar; dizin oluşturmaz).
- `i18n/__init__.py`: `t()`, `resolve_language()` / `init_language()` (seçim sırası: `--lang` > `ORKESTRA_LANG` > config > sistem > `en`), İngilizceye geri dönüş, `ORKESTRA_I18N_STRICT=1` ile eksik anahtarda hata. `locales/en.yaml`, `locales/tr.yaml`.
- CLI üst seviyesinde `OrkestraError` → ilgili çıkış kodu, beklenmeyen istisna → 10.
- `AGENTS.md`, `CLAUDE.md` (`@AGENTS.md`), kısa `README.md`, MIT `LICENSE`, Python `.gitignore`, `docs/` (iki plan belgesi + PROGRESS + DECISIONS).
- `.github/workflows/ci.yml`: ubuntu/macos/windows × Python 3.11/3.12/3.13; ruff check, ruff format --check, pyright, pytest.

**Kabul kriterleri:**
- ✅ `uv run orkestra --version` → `orkestra 0.0.1` (elle + `tests/unit/test_version.py`, `python -m orkestra` alt süreç testi dahil).
- ✅ `uv run pytest` geçiyor: 89 test (sürüm, çıkış kodu eşlemesi, `t()` dil seçim sırası, eksik anahtarda İngilizceye düşme, en/tr anahtar kümesi + yer tutucular aynı, boş değer yok). Yerelde Python 3.11, 3.12, 3.13 ile denendi.
- ✅ `uv run orkestra --lang tr --help` ve `--lang en --help` çalışıyor; Orkestra metinleri seçili dilde (elle + `tests/unit/test_cli.py`). Geçersiz `--lang` → kod 2.
- ✅ CI üç işletim sisteminde yeşil: ubuntu/macos/windows × Python 3.11/3.12/3.13, 9/9 iş başarılı (PR #1, run 42650875932). İlk koşuda ANSI renk kodu yüzünden 1 test düşmüştü, düzeltildi.

**Ertelenenler:**
- Yok.

**Bilinen sorunlar:**
- typer/click'in kendi metinleri ("Usage", `--help`, `--install-completion` açıklamaları) çevrilmez (plan bunu kabul ediyor).
- Windows'ta çıktı bir boruya yönlendirilince (UTF-8 modu kapalıyken) Türkçe karakterler cp1254 ile yazılır; terminalde doğru görünür. `PYTHONUTF8=1` önerisi Mimari §15'te var.
- GitHub Actions ortamında rich, yakalanan çıktıya da ANSI renk kodu basıyor; CLI testleri renk kodlarını temizleyip karşılaştırıyor, `conftest.py` `NO_COLOR=1` ayarlıyor.
- `LICENSE` telif sahibi "Orkestra contributors"; istenirse gerçek adla değiştirilmeli.

<!--
### Faz N – Başlık (YYYY-MM-DD)
**Yapılanlar:**
-
**Kabul kriterleri:** (her biri ✅/❌ ve nasıl doğrulandığı)
-
**Ertelenenler:**
-
**Bilinen sorunlar:**
-
-->

## Ertelenenler (v1 sonrası)
- YAPILIS_PLANI.md Ek B'deki liste
