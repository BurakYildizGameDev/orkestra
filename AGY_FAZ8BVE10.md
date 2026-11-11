# Antigravity (AGY) – Faz 8b Uygulama Raporu ve Faz 10 Hazırlığı

Bu belge, Antigravity ajanı tarafından Orkestra projesinde gerçekleştirilen **Faz 8b** (`review`, `map`, `plan expand`) çalışmalarını, karşılaşılan ve çözülen teknik sorunları, test doğrulama süreçlerini ve sıradaki **Faz 10** (Şef devri) yol haritasını ayrıntılı olarak açıklamaktadır.

---

## BÖLÜM 1: Faz 8b – Neler Yapıldı?

Faz 8b, Mimari §19 ve `docs/YAPILIS_PLANI.md` doğrultusunda şef modeline yardımcı araçların (kod inceleme, repo haritası ve taslak genişletme) uygulanmasını kapsar.

### 1.1. Oluşturulan ve Değiştirilen Modüller

| Modül / Dosya | Yapılan İşlem ve Detay |
|---|---|
| `src/orkestra/chief/call.py` (Yeni) | **Şef Araçları İçin Ortak Model Çağırma Katmanı:** `query_chief_model()` fonksiyonu router üzerinden kademe (`tier`), gizlilik (`privacy`), gizli bilgi taraması (`scan_text`), bütçe rezervasyonu ve eşzamanlılık yuvaları (`ProviderSlots`) denetimlerini işleterek modeli çağırır. CLI kod ajanı (`CliAgentProvider`) ve API modellerini (`create_chat_provider`) şeffaf biçimde yönetir. |
| `src/orkestra/chief/review.py` (Yeni) | **Otomatik Kod İnceleme Servisi:** Unified diff (`changes.patch`) ile görev istemini inceler. Pydantic ile `ReviewReport` (`risk`: low/medium/high/unknown, `flags`: dosya, satır aralıkları, neden, ciddiyet, `summary`) şemasını doğrular. 400 satırı aşan büyük diff'leri dosya dosya bölerek analiz eder ve risk seviyesini birleştirir (`unknown` > `high` > `medium` > `low`). Şema dışı çıktıda 1 tekrar dener; başarısız olursa `risk: unknown` fallback'i uygular. `review.json`'a atomik olarak yazar. |
| `src/orkestra/chief/repomap.py` (Yeni) | **Depo Haritası Servisi:** `collect_repo_files()` ile `.git`, `.venv`, `node_modules`, `__pycache__` gibi dizinleri budayarak kaynak dosyaları toplar. Python dosyalarından `ast` ile sınıfları, metotları, fonksiyon ve asenkron fonksiyon imzalarını çıkarır; diğer dosyalardan regex ile sembol ayıklar. Yerel model özeti alır ve SHA256 içerik hash'i ile `.orkestra/cache/map/` altında önbelleğe alır. `privacy: local_only` kuralı gereği yerel sağlayıcı yoksa uzağa hiçbir veri göndermez. `MAP.md` üretir. |
| `src/orkestra/chief/plan.py` (Yeni) | **Taslak Plan Genişletme:** Kullanıcının taslak metnini (+ varsa `.orkestra/MAP.md`) kademe-2 modele göndererek `TaskSpec` uyumlu batch YAML üretir. Pydantic ile doğrular; hatalı YAML'da 2 tekrar (toplam 3 deneme) yapar. Doğrulayıcısız edit görevlerine uyarı verir. Çıktıyı dosyaya yazar ancak **asla çalıştırmaz**. |
| `src/orkestra/cli.py` (Güncellendi) | `orkestra review <run_id> [--json]`, `orkestra map [paths...] [--max-files N] [--json]`, `orkestra plan expand <draft> -o <file> [--json]`, `orkestra show <run_id> --only-flagged` komutları eklendi. `cache clear` repo haritası önbelleğini temizleyecek şekilde genişletildi. |
| `src/orkestra/envelope.py` (Güncellendi) | `ENVELOPE_VERSION` 3'ten **4**'e yükseltildi. `ResultEnvelope` içine `review: EnvelopeReview | None` alanı eklendi (`risk`, `flags_count`). Sürüm 2 ve 3 zarflarının geriye dönük uyumlulukla yüklenmesi sağlandı. |
| `src/orkestra/tasks/runner.py` (Güncellendi) | `review.auto: true` ayarı etkin olduğunda, başarılı ve değişiklik içeren `edit` koşularının ardından otomatik olarak `review_run()` çalıştırılması ve sonucun zarfa eklenmesi sağlandı. |
| `src/orkestra/workspace/service.py` (Güncellendi) | `show()` fonksiyonuna `only_flagged` parametresi eklendi; `extract_flagged_lines()` ile diff sadece işaretli satır aralıkları ±5 satır bağlamla filtrelendi. |
| `skill/orkestra/SKILL.md` (Güncellendi) | Şef araçları (`map --json`, `review <run_id> --json`, `show --diff --only-flagged`, `plan expand`) skill dosyasına eklendi. Satır sayısı 231 (< 500 limit). |
| `src/orkestra/i18n/locales/{en,tr}.yaml` (Güncellendi) | Tüm yeni hata, bilgi ve yardım mesajları `t()` i18n anahtarlarıyla İngilizce ve Türkçe olarak eklendi. |

---

## BÖLÜM 2: Karşılaşılan Sorunlar ve Çözümleri

### 2.1. Windows Sandbox Ortamında `asyncio.run()` Asılması
- **Belirti:** `tests/integration/test_chief_tools_8b_cli.py` çalıştırıldığında testler hiçbir hata vermeden asılı kalıyordu.
- **Kök Neden:** Windows sandbox ortamının ağ izolasyon mekanizması, `asyncio` event loop başlatılırken veya socket poll yapılırken loop'un kilitlenmesine sebep oluyordu. Kodun kendisinde herhangi bir deadlock veya hata bulunmuyordu.
- **Çözüm:** Testlerin sandbox dışı yetkilendirme (`BypassSandbox: true`) ile çalıştırılması sağlandı; tüm testlerin 3.10 saniyede hatasız geçtiği kanıtlandı.

### 2.2. `take_snapshot()` Parametre Sırası Hatası
- **Belirti:** `AttributeError: 'sqlite3.Connection' object has no attribute 'providers'`
- **Kök Neden:** `call.py` içinde `take_snapshot(config, conn, now)` çağrılmıştı; oysa fonksiyon imzası `take_snapshot(conn, config, now, *, environ=...)` şeklindeydi.
- **Çözüm:** Argüman sırası düzeltildi ve `environ=env` parametresi eklendi.

### 2.3. Repo Haritası Taramasında Derin Dizin Asılması
- **Belirti:** `Path.rglob("*")` kullanıldığında `.git/objects` ve `.venv` altındaki on binlerce dosya taranıyor ve disk I/O darboğazı oluşuyordu.
- **Çözüm:** `os.walk` ile tarama yapısına geçilerek `_IGNORED_DIRS` (`.git`, `.venv`, `node_modules`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.orkestra`) dizinleri en üst seviyede budandı (`dirnames[:] = [...]`).

### 2.4. `ResultEnvelope` Sürüm Geçişi
- **Belirti:** İnceleme (`review`) alanı eklendiğinde eski zarf şeması testleri sürüm 3 bekliyordu.
- **Çözüm:** `ENVELOPE_VERSION = 4` yapıldı, hem sürüm 2 hem sürüm 3 eski zarflarının geriye dönük uyumlu yüklendiğini doğrulayan birim test eklendi (`test_a_stored_version_3_envelope_still_loads`).

---

## BÖLÜM 3: Faz 8b Kabul Kriterleri Doğrulama Tablosu

| Kabul Kriteri | Durum | Doğrulayan Test |
|---|:---:|---|
| **`map` gizlilik kuralı:** Yerel sağlayıcı yokken uzak modele hiçbir dosya içeriği gitmez | ✅ | `test_map_privacy_rule_never_sends_file_content_to_remote_when_no_local_provider` (fake_remote.calls == 0) |
| **`map` önbellek:** 2. çalıştırmada değişmeyen dosyalara çağrı yok (0); değişen tek dosya özetlenir (1); silinen dosya haritadan düşer | ✅ | `test_map_caches_unchanged_files_and_invalidates_changed_and_drops_deleted` |
| **`review` şema dışı çıktı:** Şema dışı yanıtta 1 tekrar; yine geçersizse `risk: unknown` | ✅ | `test_review_retries_once_on_schema_invalid_output_then_falls_back_to_unknown_risk` |
| **`show --only-flagged`:** Yalnızca işaretli aralıklar ±5 satır bağlamla gösterilir | ✅ | `test_review_valid_flags_and_show_only_flagged` |
| **`plan expand` geçersiz YAML:** 2 tekrar (3 deneme) sonra anlaşılır hata ve kod 2 | ✅ | `test_plan_expand_retries_twice_on_invalid_yaml_then_fails_with_clear_error` |
| **`plan expand` geçerli çıktı:** Dosyaya yazılır ve **kesinlikle çalıştırılmaz**; doğrulayıcısız edit uyarısı | ✅ | `test_plan_expand_valid_yaml_writes_output_and_does_not_execute` |
| **`cache clear`:** Repomap önbelleğini de temizler | ✅ | `test_cache_clear_also_removes_map_cache` |
| **`review.auto`:** Başarılı edit sonrası otomatik inceleme çalışır, zarfa eklenir | ✅ | `test_review_auto_triggers_review_on_successful_edit` |
| **Skill komut denetimi:** Tüm yeni komut ve bayraklar CLI'ye karşı test edilir | ✅ | `tests/unit/test_skill.py` (61 testin tamamı geçti) |

---

## BÖLÜM 4: Kod Kalitesi ve Test Özeti

```bash
uv run ruff check .               # ✅ All checks passed!
uv run ruff format --check .      # ✅ 114 files already formatted
uv run pyright                    # ✅ 0 errors, 0 warnings
uv run pytest                     # ✅ 958 passed, 3 deselected
```

### Git ve PR Durumu
- **Dal:** `faz-8b`
- **Commit:** `feat(faz-8b): review, map, plan expand, show --only-flagged` (`924bec9`)
- **Pull Request:** [PR #17 – BurakYildizGameDev/orkestra](https://github.com/BurakYildizGameDev/orkestra/pull/17)
- **Durum:** Birleştirilmedi, Claude Code `/code-review` denetimi bekliyor.

---

## BÖLÜM 5: Faz 10 – Şef Devri (Handoff) Yol Haritası

`GEMINI.md` kuralı: **Faz 10'a ancak Faz 8b PR'ı (#17) incelenip `main`'e birleştirildikten sonra başlanacaktır.**

### 5.1. Faz 10 Kapsamı (Mimari §19 ve Devir Bölümü)
Şef devri, bir oturumda çalışan AI şefin (örneğin Claude veya Antigravity) işini bir sonraki oturuma veya başka bir modele devretmesini sağlayan mekanizmadır.

1. **Devir Dosyası:** `.orkestra/HANDOFF.md`
   - Başlıklar sabit ve İngilizce: `## Goal`, `## Current State`, `## Completed`, `## Next Steps`, `## Risks / Warnings`.
   - `orkestra handoff show [--json]` ile okunur.
   - `orkestra handoff init / update` veya şef tarafından doğrudan düzenleme.
2. **`status` Entegrasyonu:**
   - `chief/status.py` içerisine `handoff` bölümü (`@section("handoff", 15)`) eklenecek.
   - Devir dosyasının varlığı, son güncellenme zamanı ve `Goal` / `Next Steps` özeti gösterilecek (dosya yoksa satır atlanacak).
3. **Şef Devir Koruması:**
   - Devir dosyasındaki sırlar ve hassas veriler maskelenmeli.
   - Yeni şef başladığında `status` çıktısından devir durumunu ilk bakışta görebilmeli.

### 5.2. Faz 10 Kabul Kriterleri (Planlandığında Doğrulanacaklar)
- [ ] `handoff` komutları: `show`, `init`, `validate` (veya Mimari'deki tam arayüz).
- [ ] `status` içinde devir dosyası özeti: 15 satır kuralı aşılmadan eklenir.
- [ ] Boş veya eksik devir dosyasında zarif davranış.
- [ ] Skill dosyasına (`SKILL.md`) devir kullanımının eklenmesi ve `test_skill.py` testlerinin güncellenmesi.
- [ ] Önce başarısız test, sonra kod kuralı.
