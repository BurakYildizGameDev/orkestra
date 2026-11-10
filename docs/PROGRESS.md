# İlerleme

Her faz sonunda ajan bu dosyayı günceller. En yeni faz en üstte.

## Durum özeti

| Faz | Durum | Tarih | Not |
|---|---|---|---|
| 0 – İskelet + i18n altyapısı | ✅ | 2026-11-09 | Paket adı `orkestra-cli` (D-001) |
| 1 – Config | ✅ | 2026-11-09 | init, config show/validate (D-006…D-012) |
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

### Faz 1 – Yapılandırma (2026-11-09)
**Yapılanlar:**
- `config/schema.py`: Mimari §4.1 modelleri, `type` alanına göre discriminated union, doğrulayıcılar (sağlayıcı adı deseni, `defaults.profile` / `queue.default_profile` / `defaults.chief` tanımlı mı, `min_tier <= max_tier`, `danger-full-access` için özel mesaj, cli_agent `kind` komuttan çıkarımı).
- `config/loader.py`: arama sırası (`--config` > `ORKESTRA_CONFIG` > `~/.orkestra/config.yaml`, üstüne git köküne kadar en yakın `orkestra.yaml`), birleştirme (sözlük derin, liste değiştirme, `providers.<ad>: null` siler), YAML hata satırı, pydantic hatalarının seçili dilde `alan.yolu: mesaj` özetleri, `init_config` (atomik yazma, `--force` ile `.bak`, `.gitignore`'a `.orkestra/cache/`).
- `config/example.yaml` (package data) ve aynı içerikli `examples/orkestra.example.yaml`.
- Komutlar: `orkestra init [--force] [--project] [--json]`, `orkestra config show [--json]`, `orkestra config validate [--json]`; global `--config` seçeneği.
- Config'teki `language` artık dil seçim sırasına bağlı (`--lang` > `ORKESTRA_LANG` > config > sistem).
- `--json` modunda hata olursa stdout'a tek JSON belgesi: `{"error": {"code", "type", "message", "details"}}`.
- `OrkestraError` artık `details` (satır satır sorunlar) taşıyor.
- Yeni metinler en + tr kataloglarında.

**Kabul kriterleri:**
- ✅ Geçersiz tier, bilinmeyen sağlayıcı tipi, `danger-full-access` → çıkış kodu 2 ve anlaşılır mesaj (`test_config_cli.py::test_validate_rejects_with_exit_2`, `test_config_schema.py`; elle de denendi, örn. `providers.openrouter.models[0].tier: 1, 2 veya 3 olmalı`).
- ✅ Proje config'i genel config'i doğru eziyor: liste değiştirme, sözlük birleştirme, null ile silme (`test_config_loader.py::test_project_overrides_global` + `merge_dicts` birim testleri).
- ✅ `init` iki kez çalışınca ikincisi dosyayı bozmuyor (bayt karşılaştırmalı test; `.gitignore` satırı tek kez ekleniyor).
- ✅ `config show --json` geçerli JSON (`json.loads` testi).
- ✅ ruff, ruff format, pyright, pytest (176 test) temiz.

**Ertelenenler:**
- Kurulum sihirbazı (`init` artık sadece örneği kopyalıyor) → Faz 11.
- `providers` boşken görev komutlarının "orkestra init çalıştır" mesajıyla kod 2 vermesi → görev komutları geldiğinde (Faz 2).

**Bilinen sorunlar:**
- Kapanmamış parantez gibi YAML hatalarında satır numarası dosya sonunu gösterebiliyor (ruamel'in `problem_mark`'ı).

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
