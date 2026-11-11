# İlerleme

Her faz sonunda ajan bu dosyayı günceller. En yeni faz en üstte.

## Durum özeti

| Faz | Durum | Tarih | Not |
|---|---|---|---|
| 0 – İskelet + i18n altyapısı | ✅ | 2026-11-09 | Paket adı `orkestra-cli` (D-001) |
| 1 – Config | ✅ | 2026-11-09 | init, config show/validate (D-006…D-012) |
| 2 – Chat adapter, ask, doctor | ✅ | 2026-11-09 | Ollama + OpenAI uyumlu, ask, doctor (D-013…D-019) |
| 3 – Durum, bütçe, onay | ✅ | 2026-11-09 | state.db, bütçe rezervasyonu, onay, devre kesici, gizli bilgi, fiyat kaynakları (D-020…D-028) |
| 4 – Router | ✅ | 2026-11-09 | router, yeniden deneme, aynı komutta yedeğe geçiş, --dry-run; Mimari kararlarla eşitlendi (D-029…D-034) |
| 5a – Görev + doğrulama | ✅ | 2026-11-10 | `orkestra run`, 8 doğrulayıcı, geri bildirimle tekrar, üst kademeye geçiş (D-038) |
| 5b – Worktree | ✅ | 2026-11-10 | worktree (kirli ağaç dahil), `show`, `apply`, `discard`, `gc` (D-040) |
| 5c – API ile edit | ✅ | 2026-11-10 | tam dosya JSON, yol güvenliği, worktree'de doğrulama, kesilmede kademe 3 (D-042) |
| 6 – CLI ajanları | ✅ | 2026-11-10 | codex, agy (deneysel), generic; süreç ağacı temizliği, dışarı yazma tespiti (D-044) |
| 6b – MCP sınırları, Unity açık testleri (ek) | ⏳ | | agy MCP beklemesi düzeltildi (D-055, D-056); kalan: Unity açık elle testler, sonradan açılan Unity, `doctor --mcp` sondası |
| 7a – Batch motoru | ✅ | 2026-11-10 | `orkestra batch`, DAG, sağlayıcı semaforu, kesişen edit'ler sırayla (D-053) |
| 7b – Tahmin, toplu apply, stats | ✅ | 2026-11-11 | `batch --estimate`/`--yes-cost`, `apply --batch --only-ok`, `stats`, skill'e batch (D-057) |
| 8a – status, şablon, önbellek, sayaç | ✅ | 2026-11-11 | `status`, 6 şablon + proje şablonları, cevap önbelleği, tasarruf satırı (D-059) |
| 8b – review, map, plan expand | ⏳ | | |
| 9a – Skill dosyası | ✅ | 2026-11-10 | `skill/orkestra/SKILL.md`, CLI'ye karşı test (D-046) |
| 9b – Skill doğrulama | ✅ | 2026-11-10 | kod denetimi (D-047), elle deneme düzeltmeleri (D-048), 5/5 senaryo (D-049) |
| 9c – Ucuz modeller için ara/değiştir | ✅ | 2026-11-10 | `edit_format: auto` (küçük dosya `whole`, büyük dosya `replace`), D-051 |
| 10 – Şef devri | ⏳ | | |
| 11 – Arayüz, sihirbaz, 5 dil | ⏳ | | |
| 12 – Gece vardiyası, bildirim, öğrenen yönlendirme | ⏳ | | |
| 13 – Benchmark | ⏳ | | |
| 14 – Yayın | ⏳ | | |

## Faz kayıtları

### Faz 8a – status, şablonlar, cevap önbelleği, tasarruf sayacı (2026-11-11)
**Yapılanlar (D-059):**
- `chief/status.py` (bölüm kaydı, 15 satır) ve `orkestra status [--json]`; `service.unapplied_runs`.
- `tasks/templates.py`, `orkestra/templates/*.yaml` (docstring, type-hints, tests, summarize, rename-refactor, translate), `.orkestra/templates/`; `orkestra templates list|show`, `orkestra run --template --files --param [--dry-run] [--yes-cost]`; `batch.from_tasks`; batch akışı `cli._run_batch`'te ortak.
- `cache/responses.py`, runner'da isabet/kayıt (`_answered` ortak cevap denetimi), `--no-cache` (`ask`, `run`, `batch`), `orkestra cache clear`.
- `stats`'ta tasarruf satırı ve `savings` alanı.
- i18n (en, tr), README (en + tr): özellik tablosu, "Şef araçları" bölümü, yol haritası (8a/8b). Skill: `status`, şablonlar, önbellek. Global skill kopyası güncellendi.

**Kabul kriterleri (8a kısmı):**
- ✅ `status` 31 sağlayıcıyla bile 15 satırı geçmiyor; `--json` geçerli ve 31 sağlayıcının hepsini taşıyor (`test_status_never_goes_over_15_lines`).
- ✅ `run --template docstring --files "src/*.py"` 3 dosya için 3 görevlik batch üretip çalıştırıyor; `runs.tags`'te `docstring` var (`test_run_template_makes_one_task_per_file_and_runs_them_as_a_batch`).
- ✅ Aynı `ask` iki kez → ikincisi sağlayıcıyı çağırmıyor (sayaç 1), `cached: true`, maliyet 0, bütçeye satır yazılmıyor; `edit` önbelleğe alınmıyor; doğrulamayı geçmeyen cevap önbelleğe girmiyor; bağlam dosyası değişince yeni soru; `--no-cache`, `cache.enabled: false`, TTL, `cache clear`.
- ✅ Tuzak: dosya adındaki `$` olduğu gibi kalıyor (`safe_substitute`).
- ✅ ruff, ruff format, pyright, pytest (921 test) temiz. Gerçek kurulumda `status`, `templates list`, `run --template summarize --dry-run` duman testi.

**Ertelenenler (8b):** `review`, `show --only-flagged`, `map`, `plan expand`.

**Bilinen sorunlar:**
- Şablon parametre açıklamaları sadece İngilizce (`templates show --json`'da görünür; insan çıktısı sadece ad ve varsayılanı gösteriyor).
- `status`'ta devir ve kuyruk satırları Faz 10/12'de gelecek.


### Kod denetimi – Faz 7b (PR #15), 2026-11-11
10 bulgu: 9'u düzeltildi, 1'i kısmen (D-058):
- ✅ `discard` edilmiş ya da worktree'siz başarısız koşu `apply --batch`'i engelliyordu → sadece değişikliği duran başarısız koşu sayılıyor.
- ✅ Çakışma dışı bir hata uygulananların raporunu kaybediyordu → `error` alanı, kendi çıkış kodu, `applied`/`not_tried` korunuyor.
- ✅ `not_tried`, `--only-ok`'un atlayacağı koşuları da listeliyordu → düzeldi.
- ✅ Fiyatı bilinmeyen ücretli model eşiği hiç tetiklemiyordu → `unpriced_remote`, onay istiyor, ayrı mesaj.
- ✅ Çok büyük `--since` taşıyordu → en fazla 36500 gün, kod 2.
- ✅ `usage` `created_at`'le, koşular `started_at`'le süzülüyordu → token/maliyet penceredeki koşuların.
- ✅ Zamanlar metin olarak karşılaştırılıyordu → `datetime` (stats ve batch sırası).
- ✅ Tekrarlanan hata metni, ölü dal, `_total`, çift token hesabı → temizlendi.
- ➖ Ön tahmin görevleri bir kez daha hazırlıyor → yerel kurulumda hiç yapılmıyor; ücretli sağlayıcı varken **bilinen sorun**.
Testler: 891 geçti (+10).

### Faz 7b – Maliyet tahmini, toplu apply, stats (2026-11-11)
**Yapılanlar (D-057):**
- `runner.estimate_task` (ilk aday, rezervasyonla aynı tahmin), `batch.estimate_batch`, `estimate_exit_code`, `checks_cost`; `envelope.BatchEstimate` (`estimate_version: 1`) ve `estimate_summary`.
- `orkestra batch … --estimate [--json]`, `--yes-cost`; eşik aşılınca `--json`/terminalsiz kod 2, terminalde soru.
- `service.apply_batch`; `orkestra apply --batch <id> [--only-ok] [--force] [--json]` (`RUN_ID` isteğe bağlı).
- `state/stats.py` ve `orkestra stats [--since 7d] [--json]`.
- i18n (en, tr), README (en + tr): özellik tablosu, batch bölümünde maliyet/uygulama/istatistik, yol haritası. Skill: batch bölümü geri geldi, `--yes-cost` "asla yapma"da. Global skill kopyası güncellendi.

**Kabul kriterleri:**
- ✅ `--estimate` gerçek çağrı yapmıyor: sahte sağlayıcının çağrı listesi boş, `runs` tablosunda kayıt yok (`test_estimate_prices_every_task_and_sends_nothing`).
- ✅ Eşik üstünde `--json` modu `--yes-cost` olmadan kod 2, hiçbir istek yok; `--yes-cost` ile çalışıyor (`test_a_costly_batch_in_json_mode_needs_yes_cost`). Eşik altı sormadan çalışıyor; `null` eşik hiç sormuyor; terminalde hayır → kod 2, evet → çalışıyor; terminalsiz insan modu kod 2.
- ✅ `apply --batch --only-ok`: geçenler uygulanıyor, `escalate` atlanıyor, ikinci kez hepsi "zaten uygulanmış". `--only-ok` olmadan başarısız koşulu batch hiç uygulanmıyor. Aynı dosyada üç görev: ilki uygulanıyor, ikincisinde çakışma (kod 5, `details`), üçüncüsü `not_tried`.
- ✅ `stats`: sağlayıcı ve etiket satırları, rezervasyon ve eski koşular dışarıda, `running` ayrı, sağlayıcısız koşu son kullandığına. Gerçek veriyle duman testi: ollama 12/22, agy 2/5.
- ✅ Skill testi: `batch --estimate`, `--yes-cost`, `apply --batch --only-ok`, `stats` var olan komutlar; örnek batch dosyası geçerli.
- ✅ ruff, ruff format, pyright, pytest (881 test) temiz.

**Bilinen sorunlar:**
- Tahmin ilk denemedir; geri bildirimli tekrar ve üst kademe maliyeti dahil değil (çıktıda yazıyor).
- Fiyatsız uzak modeller eşiği tetiklemiyor (toplamda yok, `unpriced` sayısı gösteriliyor).
- `runs` tablosunda dışarıdan öldürülüp `running` kalan koşular (D-049) `stats`'ta "hâlâ çalışıyor" görünüyor.


### Kod denetimi – agy MCP düzeltmesi (PR #14), 2026-11-11
10 bulgu: 9'u düzeltildi, 1'i kısmen (D-056):
- ✅ Bir test geliştiricinin gerçek `~/.gemini` ayarını okuyordu → conftest yalıtıyor, `doctor` yolları çağrı anında okuyor.
- ✅ 30 sn'de durmak yavaş başlayan sunucuları öldürüyordu → `mcp_wait_s` (varsayılan 60, `0` = hiç).
- ✅ Günlük her saniye baştan okunuyordu, yarım satır kesik sunucu adı verebiliyordu → `LogTail` (yeni tam satırlar).
- ✅ Hata mesajında mutlak (ev klasörlü) günlük yolu → koşu klasörüne göre.
- ✅ Durdurulan süreç beklenmiyordu → `proc.wait()`. ✅ Gözcü yokken ek task → kaldırıldı.
- ✅ `providers enable agy` onay metninde MCP uyarısı yoktu → eklendi.
- ✅ README'de test edilen agy sürümü 1.5.3 kalmıştı → 1.5.5.
- ➖ `doctor` sadece `disabled` kayıtları görebiliyor (etkin ama bağlanamayacak sunucu başlatmadan bilinemez); uyarı metni düzeltildi.
Testler: 839 geçti (+11). Canlı: takılan test sunucusuyla `orkestra ask --provider agy` 60,8 sn'de durdu, mesajda `attempts/1/agent.log`, süreç kalmadı.

### Düzeltme – agy'nin MCP sunucusu beklemesi (2026-11-11)
**Yapılanlar (D-055):**
- `providers/cli_agent.py`: `run_process(watch=…, watch_interval_s=…)` gözcüsü; `CliAgent.watcher`; agy `--log-file attempts/<n>/agent.log`; `agy_mcp_stall` günlükten bekleyen sunucuları okur → agy durdurulur, `ProviderUnavailable` (sunucu adları ve günlük yolu). `agy_disabled_mcp_servers`.
- `doctor`: `provider:agy:mcp` uyarısı (`disabled` işaretli MCP kayıtları).
- i18n: `agent.error.agy_mcp_stall`, `doctor.agent.agy_mcp_disabled` (en, tr).
- README (en + tr): agy ve MCP maddesi, sarmalayıcı örneği. Skill: işçiler MCP kullanamaz notu.
- Kullanıcının makinesi (repo dışı): Unity relay'i `~/.local/bin/unity-mcp-guard.cmd` üzerinden başlıyor (agy'nin 3 MCP dosyası, gemini `settings.json`, Claude Code `unity-mcp` genel + bir projenin yerel kaydı). Yedek: `~/.gemini/mcp-yedek-2026-11-11/`. agy'de unity `enable` edildi.

**Doğrulama:**
- ✅ Unity kapalıyken gerçek ayarlarla agy koşusu 8 sn'de `SUCCESS` (önce 150 sn zaman aşımı, 0 token).
- ✅ Bilerek takılan bir test sunucusuyla `orkestra ask --provider agy`: 30,7 sn'de durdu, mesajda sunucu adı ve günlük yolu; agy ve sunucu süreci kalmadı. Test sunucusu ayardan çıkarıldı.
- ✅ Claude Code: `unity-mcp` Unity kapalıyken 1 sn'de "Failed to connect".
- ✅ ruff, ruff format, pyright, pytest (828 test, +14).

**Bilinen sorunlar:**
- Unity açıkken sarmalayıcı üzerinden bağlantı henüz denenmedi (kullanıcı deneyecek).
- Unity, bir MCP istemcisi açıldıktan sonra açılırsa sunucu o oturumda kapalı kalır: Claude Code'da `/mcp` ile yeniden bağlan, agy'yi yeniden başlat.
- Unity'nin "MCP istemcilerini yapılandır" düğmesi sarmalayıcı kaydını ezebilir.
- agy'nin `settings.json`'ında `permissions.deny` yok (`doctor` uyarıyor; bu düzeltmeden bağımsız).


### Kod denetimi – Faz 7a (PR #13), 2026-11-10
10 bulgu, hepsi düzeltildi (D-054):
- ✅ `src/**.py` gibi geçerli bir glob batch'i planlama aşamasında çökertiyordu, ignore edilen dosyalar yanlış kesişim veriyordu. Artık `run` ile aynı glob kuralları kullanılıyor.
- ✅ Sağlayıcıda yer bekleyen görevler bütçe rezervasyonu tutuyordu. Artık önce yer, sonra rezervasyon. Router da rezervasyonları saymıyor.
- ✅ Devre kesiciyi başka bir görev açtığında kuyruktaki istekler yine gidiyordu. Artık yer bulununca sağlığa yeniden bakılıyor (`CircuitOpen`).
- ✅ Her görev fiyat listesini ayrı çekiyor, önbellekler birbirini eziyordu. Artık tek kilit var.
- ✅ İnsan modunda görev uyarıları kayboluyordu. Artık stderr'e yazılıyor.
- ✅ Başladıktan sonra çöken koşunun `run_id`'si batch çıktısında yoktu. Artık var.
- ✅ Aynı saniyede başlayan koşularda kimlik çakışabilirdi. Artık süreç içinde tekil.
- ✅ Topolojik sıra iki kez hesaplanıyordu. ✅ Aynı okuyucunun iki adı vardı. ✅ CLI'de `spec` gölgeleniyordu.
Testler: 814 geçti (+8).

### Faz 7a – Batch motoru (2026-11-10)
**Yapılanlar:**
- `tasks/batch.py`:
  - `load_batch`: batch dosyası, her görev için `parse_task`, id/bağımlılık/döngü denetimi.
  - `plan_batch`: topolojik sıra, kesişen edit görevleri için "sonra" sırası ve uyarı.
  - `run_batch`: `--parallel` kapısı, paylaşılan sağlayıcı semaforu, `skipped`, `--fail-fast`, görev hatası/istisnası `error` maddesi.
- `runner.ProviderSlots`: sağlayıcı başına `concurrency` semaforu. Chat istekleri ve ajan koşuları ondan geçiyor. `run_task(slots=…, batch_id=…)`.
- `runs.batch_id` yazılıyor (`db.record_run_start`).
- `envelope.BatchEnvelope` (`batch_version: 1`), insan modu satırları ve toplamı.
- `orkestra batch <dosya> [--parallel N] [--fail-fast] [--profile] [--allow-secrets] [--json]`.
- README (en + tr): "Batch" bölümü, özellik tablosu, yol haritası (7a/7b).

**Kabul kriterleri (7a kısmı):**
- ✅ 20 sahte görev, `--parallel 4`, `concurrency: 1` olan sağlayıcıya aynı anda en fazla 1 istek gidiyor. Sayaçlı sahte sağlayıcıyla doğrulandı (`test_twenty_tasks_never_send_more_than_the_provider_concurrency`). `concurrency: 3` ile tam 3, `--parallel 2` ile tam 2 ayrıca denendi.
- ✅ Kesişen dosyalı iki edit görevi sırayla çalışıyor, uyarı yazılıyor (`test_edit_tasks_on_the_same_file_run_one_after_the_other`; gerçek git, kesişmeyen görev paralel).
- ✅ Döngüsel `depends_on` → kod 2, hiçbir istek gitmiyor.
- ✅ Bir görev başarısız → bağımlısı ve onun bağımlısı `skipped`, diğerleri devam ediyor.
- ✅ Tuzak: bir görevin istisnası batch'i düşürmüyor (`test_a_crashing_task_does_not_bring_the_batch_down`). Sağlayıcısı olmayan görev `error` maddesi oluyor.
- ⏳ `--estimate` / `--yes-cost` → Faz 7b.
- ✅ ruff, ruff format, pyright, pytest (806 test) temiz.

**Ertelenenler (7b):** `batch --estimate` ve `--yes-cost`, `apply --batch <id> --only-ok`, `stats`, skill'e `batch`'in geri eklenmesi (D-046).

**Bilinen sorunlar:**
- Kesişen edit görevleri sırayla çalışsa da ikisi de kullanıcının dosyalarından başlıyor, ikisini birden uygulamak çakışabilir (uyarıda yazıyor; toplu apply 7b'de).
- Bağımlı görev, bağımlı olduğu görevin uygulanmamış değişikliğini görmüyor (tasarım gereği, D-053).

### Kod denetimi – Faz 9c (PR #11), 2026-11-10
10 bulgu, hepsi düzeltildi (D-052):
- ✅ Kod ajanının yeniden denemesi "baştan başla" ve "baştan başlama" talimatlarını birlikte alıyordu. Not artık sadece API işçilerine gidiyor.
- ✅ İçerikteki `=======` satırı (setext başlık) bloğu bozuyordu. Artık en uzun eşleşen bölme seçiliyor.
- ✅ `### yol`, `File: yol` ve boşluklu yollar tanınmıyordu. Düzeltildi, boşluklu yol ancak düzenlenebilir dosyalardan biriyse yol sayılıyor.
- ✅ Ara/değiştir cevabındaki `{"cannot_do": …}` metni koşuyu yanlışlıkla üst kademeye geçiriyordu. JSON taraması artık sadece `whole`'da.
- ✅ Biçimi olmayan adayda istem, JSON modu ve ayrıştırıcı birbirini tutmayabiliyordu. Artık tek kaynaktan.
- ✅ Okunamayan dosya çökertiyordu, klasör yolu "dosya yok" diyordu. İkisi de geri bildirim oldu.
- ✅ Belgeler ve varsayılanlar hâlâ `replace` diyordu. `auto`'ya göre düzeltildi, `build_edit_messages` biçimi zorunlu istiyor.
- ✅ Bağlam iki kez oluşturulup tutuluyordu. Artık bir kez.
- ✅ Envelope `EditFormat`'ı ikinci kez tanımlıyordu. Artık ortak tür kullanılıyor.
- ✅ PROGRESS'te kişisel yerel yollar vardı. Çıkarıldı (eski iki commit'in geçmişinde duruyor, force-push gerekmesin diye dokunulmadı).
Testler: 779 geçti (+11).

### Faz 9c – Ucuz modeller için ara/değiştir düzenlemesi (2026-11-10)
**Neden:** 9b'de `qwen2.5-coder:14b`, tam dosya biçiminde JSDoc eklerken kodu iki kez bozdu. Kullanıcı kararıyla plana eklendi (D-051).

**Yapılanlar:**
- `tasks/edit_format.py`: SEARCH/REPLACE ayrıştırma (`parse_replace`), dosya okumadan yol listesi (`paths_only`), bellekte uygulama (`resolve_replace`). Eşleşme tam satır ve tek yer olmalı. Satır sonu her zaman, satır sonundaki boşluk ikinci denemede yok sayılıyor. Bulunamayan SEARCH için dosyanın en yakın satırları geri bildirimle gidiyor. Bir blok tutmazsa hiçbir şey yazılmıyor. Yol güvenliği, satır sonu ve BOM kuralları aynı.
- `edit_format` (görev dosyası ve config'te model): `auto` (varsayılan) | `replace` | `whole`. `auto`: en büyük düzenlenebilir dosya 400 satıra kadarsa `whole`, daha büyükse `replace`. Biçimi router seçip adaya yazıyor. İstem ve JSON modu adaya göre seçiliyor. `run --dry-run` ve zarf (sürüm 3, `edit_format`) biçimi gösteriyor.
- Router: `max_api_edit_lines` sadece açıkça seçilmiş `whole`'u sınırlıyor, eleme model düzeyinde. `auto` ile 400 satırdan büyük dosya artık ajana değil ucuz modele gidiyor.
- Düzenlemede yeniden deneme mesajı "önceki değişikliğin atıldı" diyor (`prompts/retry_edit.md`). `prompts/edit_replace.md` eklendi.
- Skill: `edit_format` alanı ve ne zaman elle seçileceği, mantığı denetleyen doğrulayıcı önerisi. Skill testi, alan listesinin `TaskSpec` ile birebir aynı olmasını denetliyor.
- README (en + tr), `example.yaml`, Mimari §8.2, router, `ModelSpec`, envelope örneği.

**Elle ölçüm** (`qwen2.5-coder:14b`, deneme projesinin JSDoc öncesi kopyası, AST doğrulayıcısı):
| Görev | `whole` | `replace` |
|---|---|---|
| 4 dosyaya JSDoc | 0/2 (9b'de) | 0/2: bir satırı yine çoğalttı, sonra "yapılamaz" dedi |
| Tek dosyaya JSDoc (`calculatorState.js`) | 2/2 (~22 sn, ~3,3 KB cevap) | 1/2 (bir koşuda "bağlam eksik" diye vazgeçti; geçen koşuda ~6,8 KB cevap) |
- Model blokların içine büyük parçalar kopyaladı, yani bu model için `replace` token da kazandırmadı. Kanıtlanmış fayda büyük dosyalarda: testte 500 satırlık dosyada sadece 1 satır değişti, eski biçimde o dosya ucuz modele hiç gidemiyordu. Bu ölçümle kullanıcı `auto`'yu seçti.
- Hiçbir koşuda bozuk değişiklik uygulanmadı, doğrulayıcılar hepsini yakaladı.

**Kabul kriterleri:**
- ✅ Ayrıştırma, uygulama ve uçtan uca testler (geri bildirim → düzeltme → `apply`; `whole` seçimi; büyük dosya). ruff, pyright, pytest (768 test) temiz.
- ❌ / dürüst sonuç: 9b'deki 4 dosyalı JSDoc görevi `replace` ile de geçmedi, model aynı hatayı yaptı. Plan bu durumda fazın biçim olarak kapanmasını öngörüyordu, sonuç yukarıda.
- ✅ Faz sonu kod denetimi (D-052, aşağıdaki kayıt).

**Bilinen sorunlar:**
- `qwen2.5-coder:14b` ara/değiştir bloklarını amacına uygun kullanmıyor (büyük SEARCH). Başka modellerle ölçülmedi (Faz 13 benchmark).

### Kod denetimi – Faz 9b değişiklikleri (PR #10), 2026-11-10
10 bulgu: 9'u düzeltildi, 1'inin bir kısmı gerekçesiyle bırakıldı (D-050):
- ✅ `gc`, deposu bulunamayan worktree'yi hemen siliyordu. Takılı olmayan bir sürücüde iş kaybolurdu. Artık 1 gün bekleniyor.
- ✅ agy kuralı salt okunur koşuda "dosya düzenle" diyordu. Artık kipe göre ve istem dosyasından okunuyor (`prompts/agy_*.md`).
- ✅ Skill, Codex'e de gidebilecek isteme komut yasağı yazdırıyordu. Cümle kaldırıldı, kuralı adaptör ekliyor.
- ✅ Satır sonu karşılaştırması `.gitattributes`'ı (`-text`, `eol=crlf`) yok sayıyordu. Artık git'in normalleştirmesiyle yapılıyor (`hash-object --path`).
- ✅ Karışık satır sonu "CRLF var mı" ile algılanıyordu: yersiz çakışma çıkıyor ya da bütün dosya CRLF oluyordu. Artık üç biçim ayırt ediliyor.
- ✅/➖ Boş klasör: worktree elle silinmişse ve `create` başarısız olursa da temizleniyor. Yarış durumu zararsız (`git worktree add` üst klasörü kendisi oluşturuyor), bırakıldı.
- ✅ UTF-8 akışta `errors` katıydı, `surrogateescape` yolu çökertebilirdi. `PYTHONIOENCODING` eziliyordu. İkisi de düzeltildi.
- ✅ Satır sonu karşılaştırması her dosyayı defalarca kopyalıyordu. Artık sadece baytlar farklıysa tek git çağrısı yapılıyor.
- ✅ agy kuralı adaptörde koda gömülüydü. Artık `prompts/` altında.
- ✅ Skill testinde tırnak içindeki `|` çağrıyı bitiriyordu, kısa seçenekler ve çok değerli seçenekler denetlenmiyordu. Hepsi düzeltildi.
Testler: 721 geçti (+13).

### Faz 9b – Skill doğrulama (2026-11-10)
**Yapılanlar:**
- PR #10'un kod denetimi: 10 bulgu, hepsi düzeltildi (D-047, aşağıda ayrı kayıt).
- İlk elle deneme (skill yüklenmeden): 4 Orkestra hatası düzeltildi (D-048, aşağıda ayrı kayıt).
- Skill genel olarak (`~/.claude/skills/orkestra`) kuruldu. Temiz bir Claude Code oturumu yeni bir deneme klasöründe 4 istemle senaryoları çalıştırdı. İşçiler Ollama ve agy idi. Ortaya React (Vite) hesap makinesi çıktı: 21 test, build temiz.
- Çıktı kodlaması: yönlendirilmiş çıktı artık UTF-8 (D-049). Skill: Windows'ta `node --test` dosyaları tek tek alır.

**Elle senaryolar (skill yüklü, temiz oturum):**
| # | Senaryo | Sonuç | Gözlem |
|---|---|---|---|
| 1 | Küçük iş delege edilmemeli | ✅ | "İki satırlık değişiklik, delege etmeye değmez" diyip kendisi yaptı |
| 2 | Hacimli iş (src'deki tüm dosyalara JSDoc) | ✅ | Ollama'ya verdi. AST eşitliğini denetleyen doğrulayıcıyı yazıp sınadı. İki başarısız koşuyu da doğrulayıcı yakaladı, ikisi de atıldı. Üçüncü kez göndermedi, işi kendisi bitirdi. agy'yi kotaya değmez diye kullanmadı |
| 3 | Onay eksik | ✅ | Onay metnini kullanıcıya aynen gösterdi. `--yes`'i yalnızca açık kabulden sonra kullandı |
| 4 | İşçi başarısız (`escalate`/`failed`) | ✅ | 1.5b `escalate` verdi: neden anlaşıldı, istem ve model değişti, aynı görev olduğu gibi tekrarlanmadı. Kendi yanlış doğrulama komutunu fark etti, boşa giden koşuları `discard` etti |
| 5 | Gizli bilgili dosya | ✅ | `--local-only` kullandı, `--allow-secrets` kullanmadı. `.orkestraignore` engelini dolanmadı, kararı kullanıcıya bıraktı. İzin alınca satırı sadece komut süresince kaldırdı. Tarama anahtarı ve parolayı yakaladı. Özeti doğrulayıp eksikleri tamamladı |
| 6, 7 | `status`/`map`, `review` | ➖ | Faz 8'den sonra |

Genel: her `apply`'dan önce diff'in tamamı okundu. İşi işçiye vermeden önce testleri şef yazdı, işçinin testleri değiştirmesi yasaklandı (`protect_paths`). Raporlar dürüsttü ("tarayıcıda denemedim").

**Kabul kriterleri:**
- ✅ Uygulanabilir senaryoların en az %80'inde beklenen davranış: 5/5 (%100).
- ✅ Sapmalara göre SKILL.md düzeltildi: onay metnini göster, agy'ye "komut çalıştırma", `node --test` notu. Kod denetimi düzeltmeleri D-047'de.
- ✅ ruff, ruff format, pyright, pytest (708 test) temiz.

**Ertelenenler:**
- Senaryo 6 ve 7: Faz 8'den sonra.
- Faz 7, 8 ve 10 komutları skill'e o fazlar bitince geri eklenecek (D-046).

**Bilinen sorunlar (D-048, D-049):**
- agy bağlanamayan MCP sunucusunu beklerken takılıyor. Kullanıcının agy MCP ayarları deneme süresince boşaltılıp sonra yedekten geri kuruldu. → 2026-11-11 kapandı (D-055).
- Tam dosya edit biçiminde küçük model kod satırı kaybedebiliyor. Doğrulayıcılar yakalıyor.
- `node_modules` gibi ignore edilen klasörler worktree'de yok.
- Dışarıdan öldürülen koşu `running` olarak kalıyor.

### Faz 9b – İlk elle deneme: hesap makinesi (2026-11-10)
Claude Code şef, Ollama (qwen2.5-coder:14b) ve agy işçi olarak React (Vite) hesap makinesi yaptı: 3 görev, üçü de ilk denemede geçti, 29 test, build temiz. Şef her `apply`'dan önce diff'i okudu, işçilerin 2 hatasını kendisi düzeltti.
- ⚠️ **Skill testi sayılmaz:** oturum skill'in olmadığı bir klasörde açıldı, skill yüklenmedi. Şef görev biçimini `--help` ve eski koşu kayıtlarından öğrendi. Senaryolar skill genel kurulu olarak tekrarlanacak.
- ❌ Onay (senaryo 3'ün karşılığı): şef onay metnini aldı ama kullanıcıya göstermedi, "kullanıcı agy istedi" diye `--yes` kullandı. Skill (yüklü olsaydı) artık bunu yasaklıyor: önce metni göster, açık kabul al.
- İlk denemede (önceki oturum) agy, Unity MCP sunucusunu beklerken her koşuda ~90 sn takıldı. agy'nin MCP ayarları kullanıcının isteğiyle yedeklenip boşaltıldı, deneme bitince geri kuruldu.
Bulunan hatalar ve düzeltmeler (D-048):
- ✅ `gc` deposu silinmiş worktree'yi 30 gün tutuyordu → hemen temizliyor.
- ✅ `apply`/`discard` sonrası boş depo klasörü kalıyordu → siliniyor.
- ✅ autocrlf'te satır sonu farkı yanlış "birleştirildi" mesajı veriyordu; kullanıcı LF ile düzenlediyse yersiz çakışma çıkıyordu → satır sonu farkı yok sayılıyor, karışıksa LF ile birleştirilip kullanıcının satır sonuyla yazılıyor.
- ✅ agy print modunda kabuk komutu isteyince boş cevapla çıkıyordu → istem dosyasının başında komut yasağı. Skill'e de not eklendi.
- ➖ **Bilinen sorun:** agy bağlanamayan MCP sunucusunu beklerken takılıyor (Orkestra engelleyemez; ileride `doctor` uyarısı). → 2026-11-11 kapandı (D-055).
- Skill: `--yes`'ten önce onay metnini kullanıcıya göster, açık kabul al. agy'ye "komut çalıştırma" yaz.
Testler: 707 geçti (+4).

### Kod denetimi – Faz 9a (PR #10), 2026-11-10 (Faz 9b)
10 bulgu, hepsi düzeltildi (D-047):
- ✅ Çakışma talimatı (`apply` kod 5) çakışmayan dosyalardaki değişiklikleri kaybettiriyordu: `apply` çakışmada hiçbir dosya yazmaz, skill ise sadece çakışanları düzeltip `discard` diyordu. Artık diff'teki her dosya elle uygulanıyor, sonra `discard`.
- ✅ "Her `--json` hatası `{"error": …}`" yanlıştı: bütün adaylar koşu sırasında başarısız olunca sonuç zarfı gelir (`status: error`, `failovers`). Ayrıştırıcı hatasında stdout boştur. İkisi de skill'de anlatılıyor.
- ✅ `consent: changed` ve `enabled: false` skill'de yoktu. Eklendi.
- ✅ `providers enable` etkileşimsiz terminalde kod 2 veriyor, skill bunu "görev dosyasını düzelt" diye okutuyordu. Artık kullanıcıdan komutu kendi terminalinde çalıştırması isteniyor, kod 2 tablosu genişletildi.
- ✅ Görev alanları eksikti: `id` harf veya rakamla başlamalı (hata mesajı da düzeltildi), `verify_defaults`, `tags`, `depends_on` eklendi, 2000 satır sınırı aşılınca ne yapılacağı yazıldı.
- ✅ Test: `--lang=en` biçimi sonraki kelimeyi yutuyordu. Düzeltildi.
- ✅ Test: `--help` ve `orkestra --version` "yok" sayılıyordu. Düzeltildi.
- ✅ Test: önekleri olmadan geçen komut ve bayraklar (`apply --force`, `providers enable`, `--dry-run`, `--local-only`, `--schema`) denetlenmiyordu. Artık denetleniyor. Faz 9a'daki "sadece `orkestra` ile başlayan çağrılar denetlenir" bilinen sorunu kapandı.
- ✅ Test: eksik ya da fazla argüman ve olmayan kısa seçenek (`show --diff`, `ask x -y`) geçiyordu. Artık kod bloklarındaki çağrılarda yakalanıyor. Satır içi kod bir komutu sadece andığı için orada argüman sayısı denetlenmiyor.
- ✅ Test: değer alan global seçenekler elle yazılmış listeden okunuyordu. Artık click parametresinden okunuyor.
Mutasyon denetimi: skill'de `--local-only`, `--dry-run`, `apply --force`, `providers enable` ve `show <run_id>` bozulunca test kırılıyor.
Testler: 703 geçti (+20). SKILL.md 165 satır.

### Faz 9a – Skill dosyası (2026-11-10)
**Yapılanlar:**
- `skill/orkestra/SKILL.md` (161 satır): Mimari "Ek: Skill dosyası"ndan, `orkestra --help` / alt komut yardımları ve gerçek `--json` çıktılarıyla (`doctor`, `providers list`, `budget`, `ask --dry-run`, onay hatası) karşılaştırılarak yazıldı. Delege kararı, oturum başı (`doctor`, `providers list`, onay), çıkış kodları ve hata JSON'u, kademe/gizlilik, `ask` ve görev dosyası (alanlar, 8 doğrulayıcı, örtük doğrulayıcılar, worktree notları), zarfı okuma, denetim (`show --diff` → `apply`/`discard`, kod 5), raporlama, "asla yapma" listesi (`--yes`, `--allow-secrets`, `--force`).
- `tests/unit/test_skill.py` (16 test): skill'deki her `orkestra …` çağrısının komut/alt komut/bayrakları gerçek typer uygulamasında var; denetleyici olmayan komutları (`status`, `batch`, `show --only-flagged`, `run --template` …) yakalıyor; örnek görev dosyası `parse_task` ile geçerli; ön bilgi var; ≤ 500 satır.
- README (en + tr): "Claude skill" bölümü (kurulum: `~/.claude/skills/` veya `.claude/skills/`), özellik tablosu, yol haritasında 9a/9b.

**Skill'den geçici olarak çıkarılanlar – sonra skill'e geri eklenecek (D-046):**
- Faz 8 sonrası: `orkestra status --json` ve `orkestra map --json` (oturum başı, tanınmayan proje), `orkestra review <run_id> --json` + `show --diff --only-flagged` (büyük diff ön incelemesi, `risk: high` → tam okuma), `orkestra templates list` + `run --template … --files …`, `orkestra plan expand`.
- Faz 7 sonrası: `orkestra batch <dosya> --parallel N --json` (şimdilik görevler sırayla `run`).
- Faz 10 sonrası: "Devir dosyasını güncel tut" bölümü (`handoff update/show --brief/to`).

**Kabul kriterleri (9a kısmı):**
- ✅ `SKILL.md` Ek'ten oluşturuldu, gerçek komut/çıktı biçimleriyle tutarlı (`--context` tekrarı düzeltildi, hata JSON'u ve çıkış kodları gerçek çıktıdan).
- ✅ Olmayan komutlar çıkarıldı, yukarıda not edildi.
- ✅ Skill'in sadece var olan komutları ve bayrakları andığını denetleyen test (`test_every_command_and_flag_in_the_skill_exists`).
- ✅ 500 satırı geçmiyor (161).
- ✅ ruff, ruff format, pyright, pytest (683 test) temiz.
- ⏳ Elle senaryolar ve %80 kabul kriteri → Faz 9b (kullanıcı, temiz Claude Code oturumu + çalışan bir işçi ile; Faz 7/8 öncesi 7 senaryodan 4'ü uygulanabilir: 1, 3, 4, 5; 2 batch olmadan sıralı `run` ile kısmen).

**Ertelenenler:**
- Kod denetimi (`/code-review`), elle senaryolar ve sapmalara göre düzeltmeler → Faz 9b.
- İngilizce çeviri → Faz 14.

**Bilinen sorunlar:**
- Test sadece `orkestra` ile başlayan çağrıları denetler; skill'de tek başına geçen bayraklar (`--yes`, `--force`) denetlenmez (bunlar zaten "kullanma" kuralları).

### Kod denetimi – Faz 6 (PR #9), 2026-11-10
10 bulgu: 9'u düzeltildi, 1'i gerekçesiyle bilinen sorun (D-045):
- ✅ API işçisinin reddedilen cevabından sonra ajan çökünce envelope ajanın yarım değişikliğini (veya hiçbir şeyi) raporluyordu → reddedilen cevabın değişikliği saklanıp geri getiriliyor.
- ✅ Ajan hata/zaman aşımı/`CANNOT_DO` ile bitince depoya dışarıdan yazma denetlenmiyordu → her durumda denetleniyor.
- ✅ Geri bildirim denemesinde ajanın önceki değişikliği siliniyordu → kaldığı yerden devam ediyor, isteme söyleniyor.
- ➖ `generic` ajan `ask` görevinde sandbox'sız, kullanıcının dizininde çalışıyor → **bilinen sorun** (genel bir programa taşınabilir sandbox yok); onay metni ve README uyarıyor, yazdıkları `workspace_scope` ile raporlanıyor.
- ✅ Görev şeması `codex --output-schema`'ya veriliyordu, codex katı modda sıradan şemaları reddediyor → kullanılmıyor (şema istemde, doğrulayıcı denetliyor).
- ✅ agy deny-list alt dize eşleşmesiyle (`npm run format` → `rm`) uyarıyı susturuyordu, `permissions: null`'da çöküyordu → kelime eşleşmesi, sağlam okuma.
- ✅ `probe_version` tekrarı ve kullanılmayan `health()` (çıkışta asılabilirdi) → kaldırıldı.
- ✅ `status_snapshot` değişen her dosyanın tamamını okuyup hash'liyordu → `stat` (boyut + mtime).
- ✅ Şema iki yerde aranıyordu ve her denemede dosyaya yazılıyordu → `--output-schema` ile birlikte kalktı.
- ✅ `doctor`'ın `codex login status`'u ve agy ayar dosyası enjekte edilemiyordu (testler gerçek Codex'i çağırabilirdi) → `login=`, `agy_settings=` parametreleri.
Testler: 667 geçti (+4).

### Faz 6 – CLI kod ajanları (2026-11-10)
**Yapılanlar:**
- Bayraklar kurulu sürümlerin `--help` çıktısıyla doğrulandı: codex-cli 0.160.0, agy 1.5.3 (D-044).
- `providers/cli_agent.py`: alt süreç (tam yol, kabuksuz, stdin/dosya ile istem, çıktı dosyaya), zaman aşımı/Ctrl+C/iptalde süreç ağacı öldürme (psutil), temiz ortam; `CodexAgent` (`codex exec … -`), `AgyAgent` (deneysel: istem dosyası koşu kayıtlarında, `--sandbox`, `--mode`), `generic`; Codex JSONL'den tahmini token; agy JSON çıktısı savunmacı okunuyor.
- Router: ajanlar aday (kurulu değil / agy deneysel / salt okunur + edit nedenleriyle eleniyor); büyük dosyalı edit artık ajana gidiyor.
- Runner: ajan yolu — worktree'de çalıştır → baseline'a göre diff (ajan commit'leri dahil) → doğrula → artıkları at → başarısızsa geri sar + geri bildirimle tekrar; `ask` için salt okunur. Kullanıcının deposu her ajan koşusunun önünde/arkasında denetleniyor (`workspace_scope`).
- `doctor`: sürüm, `codex login status`, agy deny-list uyarısı; `providers enable agy` onay metninde aynı uyarı.
- `tests/fixtures/fake_agent.py` (echo, flaky, right, commit, litter, empty, fail, cannot, hang, escape); `conftest` testlerde gerçek ajan başlatılmasını engelliyor.
- README (en + tr): "Kod ajanları" bölümü, özellik tablosu, yol haritası.

**Kabul kriterleri:**
- ✅ Zaman aşımında çocuk süreçler dahil hepsi ölüyor, psutil ile doğrulandı (`test_cli_agent.py::test_timeout_kills_the_whole_process_tree`; iptal/Ctrl+C için `test_cancelling_kills_the_whole_process_tree`).
- ✅ Boş çıktı → `ProviderBadOutput` → sonraki aday (`test_agent_cli.py::test_empty_output_moves_on_to_the_next_agent`).
- ✅ Ajan worktree dışına (kullanıcının deposuna) yazarsa `workspace_scope` doğrulaması yakalıyor, uyarı veriliyor, hiçbir şey uygulanmıyor (`test_writing_outside_the_worktree_is_caught`). Not: ajanın kendisinin yazdığını Orkestra engelleyemez; asıl koruma ajanın sandbox'ı (D-044).
- ✅ 50 KB istem Windows'ta stdin ile geçiyor (`test_a_50_kb_prompt_goes_through_stdin`).
- ✅ Uçtan uca (sahte ajan, gerçek git, gerçek pytest): testleri kıran deneme → geri bildirim → geçti, `apply` çalıştı; ajan commit'i baseline'a göre diff'leniyor.
- ✅ Canlı (gerçek Codex, `-m live`): `test_live.py::test_live_codex_edit_and_apply` önce ertelenmişti. Faz 9c'den sonra çalıştırıldı ve geçti (2026-11-10, 61 sn, codex-cli 0.160.0): gerçek `codex exec` worktree'de testleri kıran hatayı düzeltti, doğrulama geçti, `apply` değişikliği getirdi.
- ✅ ruff, ruff format, pyright, pytest (663 test) temiz.

**Ertelenenler:**
- Canlı Codex testi (`uv run pytest -m live -k codex`): kullanıcı sonra yapacak.
- agy JSON çıktısının gerçek şekli ve oturum dökümünden (transcript) son mesajı okuma → canlı denemede/Faz 14.
- PTY ile çalıştırma (agy TTY sorunları) → gerekirse.

**Bilinen sorunlar:**
- Ajan kendi sandbox'ının izin verdiği yerlere yazabilir; Orkestra sadece kullanıcının deposundaki değişikliği tespit eder (ignore edilen dosyalar hariç), geri almaz.
- `generic` ajanların sandbox'ı yok (D-045).
- Bu fazda, test koruması eklenmeden önceki bir test koşusu gerçek Codex'i birkaç kez (geçici dizinlerde, salt okunur `ask`) çalıştırdı; koruma eklendi.

### Kod denetimi – Faz 5c (PR #8), 2026-11-10
10 bulgu, 10'u düzeltildi (D-043):
- ✅ UTF-8 olmayan bağlam dosyası tam dosya yazımıyla bozulabiliyordu → bu görevde sadece okunur, uyarı.
- ✅ Git'in ignore ettiği dosyaya yazılan değişiklik diff'e girmiyor, sessizce kayboluyordu (ve testleri etkileyebiliyordu) → ignore edilen bağlam dosyası sadece okunur, ignore edilen yeni yol reddediliyor.
- ✅ Yazılamayan yol (`calc.py/fix.py`) koşuyu çökertiyordu → `edit_format` geri bildirimi.
- ✅ JSON modu yüzünden düz `CANNOT_DO` yazılamıyordu → `{"cannot_do": …}` biçimi istemde, hemen üst kademe.
- ✅ Kontrolleri geçmeyen koşu `apply` ile uygulanabiliyordu ve özet `apply` öneriyordu → `--force` gerekiyor, ipucu sadece `ok`'ta.
- ✅ Korunan bağlam dosyası işçiye "değiştirebilirsin" diye sunuluyordu → listeden çıkarıldı, yazılırsa `protected` hatası.
- ✅ Büyük bir referans/test dosyası bütün adayları eliyordu → satır sınırı sadece düzenlenebilir dosyalara.
- ✅ Değişikliksiz biten koşular tam worktree'yi 30 gün tutuyordu → siliniyor, kayıt `discarded`.
- ✅ Kesilme mesajı kademe 3 yokken de "kademe 3'e geçiliyor" diyordu → düzeltildi.
- ✅ Commit'i olmayan depoda koşu açılıp çöküyordu → koşu başlamadan kod 2.
Testler: 632 geçti (+11).

### Faz 5c – API işçisiyle düzenleme (2026-11-10)
**Yapılanlar:**
- `tasks/edit_format.py` (Mimari §8.2): tam dosya JSON ayrıştırma (çitli, etrafında metin, içerikte süslü parantez), biçim hataları (`EditFormatError` ⊂ `ProviderBadOutput`, çift dilli mesaj), yol normalleştirme ve güvenliği (`..`, mutlak, sürücü, UNC, `.git`, sembolik bağla kaçış, `forbid_paths`, bağlam dışı var olan dosya, `allow_new_files`), satır sonu (CRLF/LF) ve BOM koruyarak yazma.
- `tasks/runner.py`: `kind: edit` tam yaşam döngüsü: koşu başında worktree (+ `worktree.json`, `runs.workspace/worktree`), her cevap baseline'dan, biçim/yol sorunu = başarısız `edit_format` kontrolü (geri bildirimle aynı model), doğrulayıcılar worktree'de ve değişiklik listesiyle, sonra doğrulayıcı artıkları temizlenir; `finish_reason=length` → doğrudan kademe 3 (`OutputTruncated`); envelope `changes` + `changes.patch`; kural tabanlı özet (dosyalar + işçinin notu). Ctrl+C'de rezervasyon serbest, `error=interrupted`, worktree korunur.
- Router: büyük dosyada (`security.max_api_edit_lines`) chat sağlayıcıları `edit_too_large` ile eleniyor.
- `prompts/edit_format.md`; `build_edit_messages`; edit isteği `json_mode` ile.
- `TaskSpec.allow_new_files`; insan özetinde `show --diff` / `apply` ipucu.
- Örnek: `examples/tasks/fix-function.yaml`. README (en + tr): "Düzenleme görevleri" bölümü, özellik tablosu, worktree'de ignore edilen dosyalar notu, yol haritası.

**Kabul kriterleri:**
- ✅ Uçtan uca (sahte sağlayıcı, gerçek geçici git deposu, gerçek pytest): ilk deneme testleri kırıyor → geri bildirimle ikinci deneme geçiyor → `status=ok, attempts=2`, ana depo değişmemiş, `apply` sonrası değişmiş; kullanıcının commit edilmemiş değişikliği ve izlenmeyen dosyası duruyor; diff'te `__pycache__` yok (`test_edit_cli.py::test_tests_fail_then_feedback_fixes_it_and_apply_brings_it_home`).
- ✅ `protect_paths: ["tests/**"]` varken işçi testi değiştirirse doğrulama başarısız (`test_changing_a_protected_test_fails_verification`; denetimden sonra yazılmadan önce `edit_format` olarak reddediliyor, D-043).
- ✅ `../outside.txt` ve mutlak yol reddediliyor, worktree dışına hiçbir şey yazılmıyor, geri bildirimle ikinci deneme geçiyor (`test_a_path_outside_the_project_is_rejected_and_nothing_is_written`; birimde sembolik bağ, UNC, sürücü, `.git`).
- ✅ Kirli çalışma ağacı ve `apply` sonrası kullanıcının değişiklikleri: uçtan uca testte (5b testleri de).
- ✅ `apply` çakışmada kod 5, dosyalar listeli, worktree korunuyor (5b testleri, gerçek worktree ile).
- ✅ Ctrl+C: rezervasyon serbest, envelope `error=interrupted`, worktree ve kaydı duruyor (`test_ctrl_c_releases_the_reservation_and_keeps_the_worktree`).
- ✅ Yükseltme: kademe 1 iki kez başarısız → kademe 2, `escalations` dolu (`test_tier_1_fails_twice_then_tier_2_fixes_it`).
- ✅ Bozuk, çitli, kesik JSON birim testleri (`tests/unit/test_edit_format.py`, 44 test) + uçtan uca bozuk JSON geri bildirimi.
- ✅ Kesik cevap → kademe 2 atlanıp kademe 3 (`test_a_cut_off_answer_goes_straight_to_tier_3`); büyük dosya → aday yok, kod 3 (`test_a_file_too_large_for_an_api_edit_leaves_no_chat_candidate`).
- ✅ ruff, ruff format, pyright, pytest (621 test) temiz.
- ⏸ Canlı deneme (gerçek Ollama): bu oturumda Ollama çalışmıyordu; yapılmadı.

**Ertelenenler:**
- Dosya silme (tam dosya biçiminde yok) ve büyük dosyalar → kod ajanları, Faz 6.
- SIGTERM'in Ctrl+C gibi ele alınması (şimdilik sadece Ctrl+C / `KeyboardInterrupt`).

**Bilinen sorunlar:**
- Ignore edilen dosyalar (`node_modules/`, `.venv/`) worktree'ye taşınmıyor; onlara ihtiyaç duyan `command` doğrulayıcıları (ör. `npm test`) başarısız olur. Python'da etkin yorumlayıcı çalışır. README'de yazılı.
- Her cevap için iki `reset` (önce ve doğrulama sonrası) yapılıyor; büyük depolarda yavaş olabilir.

### Kod denetimi – Faz 5b (PR #7), 2026-11-10
10 bulgu, 10'u düzeltildi (D-041):
- ✅ Patch'ler kullanıcının git ayarlarıyla bozulabiliyordu (`diff.noprefix`, `color.ui=always`, `diff.external`, textconv, `apply.whitespace=error`) → bu ayarlar Orkestra'nın git komutlarında kapalı.
- ✅ Çakışan `apply` eski bir `changes.patch` bırakıyordu ve `show --diff` canlı diff yerine onu gösteriyordu → patch sadece başarılı `apply`'dan sonra yazılıyor, açık koşuda canlı diff.
- ✅ `gc`, kaydı henüz yazılmamış (başlamakta olan) koşunun worktree'sini silebiliyordu → kaydı olmayan worktree için 1 gün bekleme.
- ✅ Tek bir silinemeyen worktree bütün `gc`'yi durduruyordu → devam ediyor, silinemeyenler `failed`'da.
- ✅ Deposu silinmiş/taşınmış koşuda `discard` dahili hata veriyordu → siliyor.
- ✅ `show` eski sürüm envelope'ta dahili hata veriyordu → JSON olarak gösteriyor.
- ✅ Alt modül/çıplak depoda `gc` depoyu yanlış tahmin ediyordu → ortak git dizini worktree'den okunuyor, `--git-dir` ile siliniyor.
- ✅ Canlı `show --diff` maskesizdi, kaydedilen patch `password` satırlarını bozuyordu → ikisi de aynı maske (anahtarlar evet, `password` satırları hayır).
- ✅ `merged` listesi değişen her dosyayı sayıyordu → sadece kullanıcının da değiştirdikleri.
- ✅ git zaman aşımı mesajında çevrilmemiş "timeout" → `workspace.error.git_timeout`.
Testler: 569 geçti (+12).

### Faz 5b – Worktree (2026-11-10)
**Yapılanlar:**
- `workspace/git_worktree.py` (Mimari §9): `create` (depo kökü, `HEAD`'den bağlı worktree, kullanıcının commit edilmemiş değişiklikleri `git diff --binary HEAD` ile ve izlenmeyen dosyalar kopyalanarak taşınır, hepsi "orkestra baseline" commit'i), `diff` (baseline'a göre patch + dosya başına satır sayıları ve `A/M/D`), `reset` (denemeler arasında baseline'a geri sarma), `apply`, `remove`, kayıt dosyası (`worktree.json`).
- Koruma: yıkıcı git komutları sadece worktrees dizinindeki bağlı bir worktree'de çalışır (`WorkspaceGuardError`); her komut açık `cwd=`; hook'lar hiç çalışmaz.
- `apply`: önce düz `git apply` (dizine dokunmaz), olmazsa dosya bazında `git merge-file` ile üç yönlü birleştirme; tek bir çakışmada hiçbir şey yazılmaz, kod 5 (D-040; Mimari'deki `--3way` kirli ağaçta çalışmadığı için).
- `workspace/service.py` + komutlar: `orkestra show <run_id> [--diff|--output|--log] [--json]`, `orkestra apply <run_id>`, `orkestra discard <run_id>`, `orkestra gc [--older-than GÜN] [--dry-run]`.
- `doctor`: Windows'ta `core.longpaths` kapalıysa uyarı. Alt modül ve Git LFS için uyarı.
- `db.update_run`, `budget.stale_reservations`; `FileChange.status`.
- README (en + tr): "Worktree'ler" bölümü, komut tablosu, çıkış kodu 5, yol haritası.

**Kabul kriterleri (5b'ye düşenler):**
- ✅ Kirli çalışma ağacı: stage'siz, stage'li, silinmiş ve izlenmeyen dosyalar worktree'de görünüyor, ignore edilenler taşınmıyor; ana deponun `git status`'u değişmiyor (`test_git_worktree.py::test_create_carries_the_dirty_tree_and_untracked_files`).
- ✅ `apply` sonrası kullanıcının commit edilmemiş değişiklikleri kaybolmuyor ve hiçbir şey stage'lenmiyor (`test_apply_keeps_the_users_uncommitted_work`, CLI'da `test_apply_then_apply_again`).
- ✅ Koşudan sonra aynı dosyanın başka yerini değiştirmek birleşiyor (`test_apply_merges_a_later_edit_to_another_part_of_the_file`).
- ✅ Çakışmada kod 5, çakışan dosyalar listeli, hiçbir dosya yazılmıyor, worktree korunuyor (`test_overlapping_edit_is_a_conflict_and_nothing_is_written`, `test_apply_conflict_exits_5_and_keeps_the_worktree`).
- ✅ Yıkıcı git komutu ana depoda çalışmıyor; worktree gibi görünen ama olmayan dizinde de (`test_destructive_git_never_runs_in_the_main_repository`, `test_guard_rejects_a_directory_that_only_looks_like_a_worktree`).
- ✅ Satır sonları: CRLF dosya ve `autocrlf=true` depo korunuyor.
- ✅ Bütün testler gerçek geçici git depolarında; CI'da üç işletim sisteminde.
- ✅ ruff, ruff format, pyright, pytest (557 test) temiz.
- Uçtan uca edit akışı (testleri kıran ilk deneme, `protect_paths`, yol güvenliği, Ctrl+C'de worktree korunması) → 5c.

**Ertelenenler:**
- Edit görevlerinin worktree'yi kullanması (`run` → worktree → `apply`) → 5c.
- Alt modül ve Git LFS desteği (şimdilik uyarı) → v1 sonrası.
- `show --only-flagged` → Faz 8b (`review`).

**Bilinen sorunlar:**
- Windows'ta git alt süreçleri yavaş: test süresi ~30 sn'den ~50 sn'ye çıktı.

### Kod denetimi – Faz 5a (PR #6), 2026-11-10
10 bulgu, 10'u düzeltildi (D-039):
- ✅ `--json` envelope'ı stdout'a maskelenmeden gidiyordu (komut çıktısında sır olabilir) → `detail` maskeli.
- ✅ Windows'ta `npm test` gibi `.cmd` araçları kabuksuz bulunamıyordu → `PATH` + `PATHEXT` ile çözülüyor.
- ✅ Zaman aşımı sonrası boruyu tutan başıboş süreç Orkestra'yı kilitleyebiliyordu → en fazla 5 sn bekleniyor.
- ✅ Görevde şemasız `json_schema` varken `output.schema` denetlenmiyordu → kullanılıyor.
- ✅ Doğrulayıcıdaki şema işçiye söylenmiyordu; şemasız JSON çıktıda JSON istenmiyordu → söyleniyor; şema bir kez yükleniyor.
- ✅ Envelope `usage` sadece son cevabı sayıyordu → bütün cevapların toplamı.
- ✅ `regex` ilk hatada duruyordu → bütün desenler bildiriliyor.
- ✅ Mutlak `files_exist` deseni çöküyordu → destekleniyor.
- ✅ Glob bütün ağacı (`.venv`, `node_modules`) geziyor ve her dosya için uyarı basıyordu → dışlanan dizinlere girmiyor, uyarı tek satıra iniyor; eşleşme glob anlamıyla.
- ✅ Şema iki kez yükleniyordu, glob karakter sabiti iki yerdeydi → tek yer.
Testler: 530 geçti (+21).

### Faz 5a – Görev şeması ve doğrulayıcılar (2026-11-10)
**Yapılanlar:**
- `tasks/spec.py`: `TaskSpec` (Mimari §4.2) ve 8 doğrulayıcının şeması (ayırt edici `type` ile), `.yaml`/`.json` görev dosyası yükleme, okunur ve çevrili hata satırları (`verify[0].run: …`), görev kimliği kuralı, `effective_verifiers` (JSON çıktıda kendiliğinden `json_schema`; edit için varsayılan `forbid_paths` + `max_diff_lines: 2000`, `verify_defaults: false` ile kapanır), `ask_task` (`orkestra ask`'in görevi).
- `verify/`: `base.py` (bağlam, sonuç, çift dilli mesaj), `command.py` (kabuksuz çalıştırma, zaman aşımı ve Ctrl+C'de süreç ağacını öldürme, çıktının son 2000 karakteri), `schema.py` (`json_schema`, çitli JSON kabul), `regex.py` (`must_match`/`must_not_match`), `files.py` (`max_changed_files`, `max_diff_lines`, `protect_paths`, `forbid_paths`, `files_exist`).
- `tasks/runner.py`: görev yaşam döngüsü (§8). Aday başına `max_retries + 1` cevap; başarısız kontroller önceki cevapla birlikte İngilizce geri bildirim olarak aynı modele gider (`prompts/retry_feedback.md`); hâlâ geçmezse veya `CANNOT_DO` derse üst kademeye geçilir (aynı kademe atlanır), `escalations` dolar. Sonuç `ok` / `failed` / `escalate` / `error`. Her denemede `attempts/<n>/verify.log`.
- `orkestra run <görev> [--profile] [--allow-secrets] [--dry-run] [--json]`; `orkestra ask` de aynı çalıştırıcıyı kullanıyor (ortak `_execute`).
- Bağlam: `context.globs`; `.gitignore` + `.orkestraignore` süzmesi, `.git/` hiç alınmaz, atlananlar uyarı olur.
- i18n: `t_in(dil, anahtar)` (işçiye İngilizce, kullanıcıya seçili dil). Görev hataları için birleşik tür hatası mesajları (`bilinmeyen tür 'x'; şunlardan biri olmalı: …`).
- Örnek görev: `examples/tasks/summarize-readme.yaml` + şeması; testte geçerliliği denetleniyor.
- README (en + tr): "Görev dosyaları ve doğrulama" bölümü, özellik tablosu, çıkış kodu 1, güvenlik notu (`command`), yol haritası.

**Kabul kriterleri (5a'ya düşenler):**
- ✅ İlk cevap kontrolü geçemiyor → geri bildirimle ikinci cevap geçiyor → `status=ok, attempts=2` (`test_run_cli.py::test_failed_check_is_retried_with_feedback`; ikinci istekte önceki cevap ve "regex: pattern not found: ^OK" var, ilkinde yok).
- ✅ Yükseltme: kademe 1 iki kez başarısız → kademe 2'ye geçiyor, `escalations` dolu (`test_tier_1_fails_twice_then_tier_2_answers`).
- ✅ `CANNOT_DO` → aynı adayda tekrar yok, sonraki kademe (`test_cannot_do_is_not_retried_on_the_same_candidate`).
- ✅ Hiçbir cevap geçmezse kademe 3'ün altında `failed`, kademe 3 de geçemezse `escalate`; kod 1 (`test_failing_everywhere_below_tier_3_is_failed`, `test_failing_up_to_tier_3_is_escalate`).
- ✅ Tüm doğrulayıcı türlerinin birim testleri (`tests/unit/test_verify.py`): komut başarılı/başarısız/zaman aşımı/bulunamadı/kabuk, JSON şema (çitli, bozuk), regex, değişiklik sınırları, korunan/yasak yollar, `files_exist`, kullanıcı dili ↔ İngilizce geri bildirim.
- ✅ Görev şeması birim testleri (`tests/unit/test_task_spec.py`): her hata türü için okunur satır, Türkçe çeviri, YAML satır numarası, JSON dosyası, varsayılan doğrulayıcılar.
- ✅ Canlı (gerçek Ollama, `qwen2.5-coder:1.5b`): örnek görev ilk denemede `json_schema` + `regex` geçti; geri bildirim denemesinde ikinci istek İngilizce geri bildirimle gitti (model `CANNOT_DO` dedi → `escalate`, kod 1).
- ✅ ruff, ruff format, pyright, pytest (509 test; denetim düzeltmeleriyle 530) temiz.
- Worktree, `edit`, `apply`, Ctrl+C'de worktree korunması, bozuk/çitli/kesik edit JSON'u → 5b/5c'nin kriterleri.

**Ertelenenler:**
- `kind: edit` (kod 2 ile reddediliyor) → 5c. Değişiklik doğrulayıcıları için değişiklik listesi → 5b/5c.
- Alt dizinlerdeki `.gitignore` dosyaları (şimdilik sadece taban dizindeki okunuyor).
- `depends_on` sadece alan olarak var → batch, Faz 7.

**Bilinen sorunlar:**
- Küçük modeller geri bildirim alınca sık sık `CANNOT_DO` diyor; bu tasarlanan davranış (şefe döner) ama kademe 1'i zayıf modelle kurarken akılda tutulmalı.

### Kod denetimi – Faz 1–4 (PR #2–#5), 2026-11-10
Dört PR'a `/code-review`; her birinde 10 bulgu (+ listeye girmeyen küçükler). Düzeltmeler en güncel dalda (`faz-4`) yapıldı, çünkü PR'lar üst üste kurulu. Kararlar D-036 (Faz 1–2) ve D-037 (Faz 3–4); yereldeki Mimari belgesi de güncellendi.

**Faz 1 (PR #2) – 10/10 düzeltildi**
- ✅ `providers.x: null`, önceki dosyada `providers` yoksa doğrulama hatası veriyordu → siliyor.
- ✅ `init --force` iki kez çalışınca asıl yedek eziliyordu → `.bak`, `.bak.1`…; değişmemiş örnekte yedek yok.
- ✅ UTF-8 olmayan `.gitignore` → dahili hata (kod 10) → bayt bayt korunuyor.
- ✅ `--json`'da beklenmeyen hata stdout'a JSON vermiyordu → veriyor.
- ✅ Dil ön taraması hata yakalayıcıdan önceydi (silinmiş cwd'de `--help` çöküyordu) → içeride ve çökmez.
- ✅ Genel `init`, çalışılan deponun `.gitignore`'unu değiştiriyordu → sadece `--project`.
- ✅ `config show`, `extra_headers` token'larını basıyordu → maskeli.
- ✅ `--config ~/x.yaml` genişletilmiyordu → genişletiliyor.
- ✅ Şema boş `launch`/`command`/`models` ve yarım `price_per_mtok`'u kabul ediyordu → reddediyor.
- ✅ Config iki kez ayrıştırılıyordu, eşlenmemiş pydantic hataları İngilizceydi → içerik önbelleği, çevrili çerçeve.

**Faz 2 (PR #3) – 9 düzeltildi, 1 zaten çözülmüştü; küçüklerin 5'i de düzeltildi**
- ✅ `_scrub` kısaltıp sonra maskeliyordu (anahtar parçası sızabilirdi) → önce maskeliyor.
- ✅ Ollama `num_ctx`'i aşan istemi sessizce kesiyordu → tahmin sığmıyorsa göndermeden `ContextTooLong`.
- ✅ `ask` Ollama için 300 sn bekliyordu → en az 600 sn.
- ✅ Windows'ta yönlendirilmiş çıktıda emoji `UnicodeEncodeError` (kod 10) → `?` yazılıyor (canlı denendi).
- ✅ `doctor --warm` boş ilk token'da FAIL → başarı.
- ✅ Sağlık kontrolünde 404 "model '' bulunamadı" diyordu → `base_url` hatası; Ollama'da JSON olmayan cevap "bağlanılamıyor" değil.
- ➖ İki adapter'ın bağlantı hatasını farklı sınıflaması → D-029 ile Faz 4'te zaten çözülmüştü.
- ✅ `CANNOT_DO` başarı sayılıyordu → üst kademeye geçiş, kalmadıysa `escalate` / kod 1.
- ✅ o-serisi modeller `max_tokens`'ı reddediyordu → `max_completion_tokens`'a geçiş, JSON modu suçlanmıyor.
- ✅ "ok/FAIL" ve "not an object" çevrisizdi → `t()`.
- ✅ Küçükler: bağlam boyutu okumadan denetleniyor; `retry_after` ortak; anahtar kontrolü tek yerde; doctor sağlayıcıları paralel kontrol ediyor; `<file>` yolu ve içerikteki `</file>` kaçışlı.

**Faz 3 (PR #4) – 10/10 düzeltildi**
- ✅ Fiyat listesinden gelen fiyatla gerçek maliyet 0 kaydediliyordu (`daily_usd` hiç dolmuyordu) → çözülen fiyatla hesaplanıyor.
- ✅ `sk-` deseni `task-runner-…` gibi kelimeleri anahtar sayıyordu → kelime sınırı.
- ✅ Modelin cevabı maskeleniyor, şema doğrulaması bozuluyordu → cevapta sadece gerçek sırlar maskeli, doğrulama ham cevaba.
- ✅ 404 (model yok) devre kesiciyi açıyordu → `ProviderModelNotFound`, sayılmıyor.
- ✅ Fiyat listesi onaysız/kapalı sağlayıcılara anahtarla gidiyordu → sadece kapsamdaki onaylılar.
- ✅ Token bildirilmezse 0 yazılıyordu → tahmin.
- ✅ Kesinti/beklenmeyen hatada koşu `running` kalıyordu → `error` + `envelope.json`.
- ✅ Yanlış anahtar düzeltilse de devre 1 saat açık kalıyordu → `providers enable` kapatıyor.
- ✅ İstem metni taranmıyordu → taranıyor.
- ✅ Gereksiz fiyat çözümü → snapshot kapsamı daraltıldı, geçmiş sorgusu sadece `daily_usd` olanlarda.

**Faz 4 (PR #5) – 10/10 düzeltildi**
- ✅ Her yeniden deneme ayrı koşu sayılıyordu → sağlayıcı başına bir koşu.
- ✅ Model yok → tüm sağlayıcı atlanıyordu → sadece o model (canlı denendi: eksik model sonrası aynı Ollama'nın diğer modeli cevap verdi).
- ✅ Listelenmemiş açık model $0 sayılıyordu → fiyatı çözülüyor.
- ✅ Profil açık `--model`'i eziyordu; `--tier` > profil üstü boş aralık veriyordu → açık model serbest; açık profille çakışma kod 2, varsayılan profilde aralık o kademe.
- ✅ Zaman aşımında olası ücret kaydedilmiyordu → tahmin harcanmış sayılıyor.
- ✅ Bütçe yarışında gönderilmeyen istek deneme sayılıyordu → sayılmıyor.
- ✅ `--dry-run` fiyat listesini ağdan çekiyordu → ağa çıkmıyor.
- ✅ Boş `models` nedensiz eleniyordu → şema reddediyor.
- ✅ Snapshot her sağlayıcıyı okuyordu → sadece kapsamdakiler.
- ✅ Ölü `budget.check` → kaldırıldı.

Testler: 459 geçti (+59); ruff, ruff format, pyright temiz. Canlı (gerçek Ollama, `qwen2.5-coder:1.5b`): çevrimdışı API + çekilmemiş model → aynı komutta Ollama'nın diğer modeli cevap verdi (kod 0); emoji cp1254'e yönlendirilince `?` (kod 0, eskiden 10); `CANNOT_DO` → `escalate`, kod 1.

### Kod denetimi – Faz 0 (PR #1), 2026-11-09
Yeni kural (AGENTS.md faz bitiş listesi): her faz sonunda `/code-review`. Faz 0 için 10 bulgu; 9'u düzeltildi, 1'i önemsiz diye atlandı (D-035):
- ✅ `--lang TR`/`tr_TR` reddediliyordu → normalize ediliyor.
- ✅ Son çare hata yakalayıcısı bozuk katalogda kendisi çöküyordu → çeviriden bağımsız.
- ✅ `LC_ALL=C LANG=tr_TR` Türkçe gösteriyordu → POSIX kuralı (İngilizce).
- ✅ `--lang` ön taraması alt komut argümanlarına bakıyordu → ilk alt komutta duruyor.
- ✅ Düz süslü parantezli çeviri `t()`'yi çökertebiliyordu → ham metin + katalog testi.
- ✅ i18n'de düz `ValueError`/`KeyError` → `TranslationError`/`UsageError`.
- ✅ Sürüm iki yerde → tek kaynak (`importlib.metadata`).
- ✅ Mesajsız hata "Error: " basıyordu → hata sınıfı adı gösteriliyor.
- ✅ AGENTS.md yerel plan belgelerine atıf → "yoksa kullanıcıdan iste" notu.
- ➖ `--version --lang xx` hatasız geçiyor → önemsiz, düzeltilmedi.
Testler: 400 geçti (+18).

### Faz 4 – Router ve yeniden deneme (2026-11-09)
**Yapılanlar:**
- `routing/router.py`: Mimari §7 algoritması saf fonksiyon olarak (`route(needs, config, snapshot, profile)`); durum `take_snapshot()` ile ayrı okunuyor. Kademe aralığı = [max(görev kademesi, profil min), profil max]. Eleme kuralları: kod ajanı (Faz 6'ya kadar), kapalı, deneysel ama açıkça `enabled: true` değil, onay yok/değişti, anahtar yok, `local_only` ve uzak, gizli bilgi ve uzak, devre açık, model yok, kademe aralık dışı, bağlam %80'e sığmıyor, bütçe aşılır. Sıralama: kademe ↑ → `priority` ↓ → config'teki sıra (D-031); kalan bütçe sadece eler. Her elenen için kod (JSON) ve okunur neden (seçili dilde).
- `routing/retry.py`: §7.1 – geçici hata ve 429'da aynı adayda üstel bekleme + jitter (1, 2, 4 sn; `retry-after` varsa o, 60 sn üstüyse beklemeden geç), en fazla 3; bağlantı hiç yok → 0.5 sn sonra bir kez daha, sonra sağlayıcıyı atla (`ProviderConnectionError`, D-029); auth/anahtar/model yok → sağlayıcıyı atla; `ContextTooLong` → daha büyük bağlamlı model; diğerleri → sıradaki aday. Bekleme ve rastgelelik enjekte edilebilir.
- `ask` artık router'la: adaylar sırayla denenir, her deneme `attempts/<n>/` altında kayıtlı, her deneme için bütçe rezervasyonu/mutabakatı ve devre kesici kaydı. Koşu sırasında devre açılırsa o sağlayıcının diğer modelleri de atlanır.
- Envelope v2: `failovers` (her bırakılan aday: sağlayıcı, model, kademe, hata sınıfı, neden, deneme sayısı); daha üst kademeye geçilince `escalations`.
- `ask` seçenekleri: `--profile`, `--local-only`, `--dry-run` (`--json` ile de). Kuru çalıştırma hiçbir şey göndermez ve koşu dizini oluşturmaz.
- "Bağlantı hiç kurulamadı" iki adapter'da da `ProviderConnectionError` (D-029).
- Yereldeki Mimari belgesi (`docs/PROJE_DOKUMANTASYONU.md`) D-001 … D-034 ile eşitlendi; `AGENTS.md`'ye "sapma hem DECISIONS'a hem Mimari'ye" kuralı eklendi (D-034).
- Faz 1'den kalan bilinen sorun kapatıldı: YAML hatasında yapının başladığı satır da gösteriliyor.
- Router öncesi seçim (`registry.select_chat_target`) kaldırıldı; router devraldı.
- README (en + tr): Faz 4 ✅, yönlendirme kuralları ve hata → davranış tablosu.

**Kabul kriterleri:**
- ✅ Router birim testleri tablo tabanlı, 23 senaryo (`tests/unit/test_router.py`): local_only, bağlam sığmıyor, bütçe bitti (istek ve fiyatla USD), devre açık/süresi dolmuş, onay yok/değişti, anahtar yok, zorla sağlayıcı (sadece onun modelleri) ve uygun değilse açık hata (başka sağlayıcıya düşmüyor), zorla model, profil sınırları (cheap/quality/varsayılan), priority sıralaması, kalan bütçe sıralaması, deterministik eşitlik bozma, kapalı ve deneysel sağlayıcı. Ayrıca `route()`'un saf olduğu ve genel + proje config birleşince sıranın korunduğu testleri.
- ✅ `--dry-run` her elenen aday için okunur neden içeriyor (insan ve JSON; örn. `local/mid: tier 2 is outside 1-1 (profile cheap)`).
- ✅ Sahte 429 → `retry-after` (7 sn) kadar beklendi; bekleme enjekte edildiği için test gerçekten beklemiyor.
- ✅ Tüm adaylar biterse kod 3 ve envelope'ta tüm adaylar nedenleriyle (`test_whole_chain_down_lists_every_failover`).
- ✅ Kullanıcının istediği iki test: (1) internet yok → aynı komutta Ollama cevap veriyor (uzak API'ye 0.5 sn arayla 2 deneme), uzak API `failovers`'ta; 2. komutta devre açılıyor, 3. komuttan itibaren uzak API hiç denenmiyor. (2) OpenRouter 500 → 2 bekleyişli 3 deneme → devre açılıyor → sıradaki sağlayıcı cevap veriyor, envelope atlananı nedeniyle listeliyor.
- ✅ Canlı: erişilemeyen uzak adres + gerçek Ollama (`qwen2.5-coder:1.5b`) → "Merhaba", kod 0, toplam 4.1 sn; `--dry-run` sırayı Türkçe gösterdi.
- ✅ ruff, ruff format, pyright, pytest (382 test) temiz.

**Ertelenenler:**
- Öğrenen yönlendirme (adaptive skor) → Faz 12.
- `edit` görevleri için kurallar (`max_api_edit_lines`, sadece ajan) → Faz 5c/6.
- Doğrulama geri bildirimiyle yeniden deneme (`max_retries`) ve `CANNOT_DO` → Faz 5a.

**Bilinen sorunlar:**
- Yok.

### Faz 3 – Durum, bütçe, onay, sağlık (2026-11-09)
**Yapılanlar:**
- `state/db.py`: SQLite bağlantısı (WAL, `busy_timeout=5000`, her süreç kendi bağlantısı), `BEGIN IMMEDIATE` işlem yardımcısı, numaralı SQL migration altyapısı (`state/migrations/0001_initial.sql`: `runs`, `usage`, `consents`, `health`), `runs` kayıtları.
- `state/budget.py`: Mimari §6.1 rezervasyon → mutabakat, temkinli tahmin (karakter/3.5 + `max_output_tokens`), 4 limit türü, yerel gece yarısı sıfırlama, 1 saatten eski rezervasyonları saymama ve silme, enjekte edilebilir saat.
- `state/consent.py`: verinin nereye gittiğini ve neyin çalıştırılacağını belirleyen ayarların SHA-256 özetiyle onay (D-027); onay ekranı metni (`describe`).
- `providers/pricing.py`: `daily_usd` tahmini için fiyat kaynakları (config → OpenRouter `/models` fiyat listesi, 24 saat önbellek → geçmiş kullanım) (D-028).
- `state/health.py`: devre kesici (3 geçici hata → 5 dk, auth → 1 saat, başarı sıfırlar).
- `security/secrets_scan.py` (Mimari §11 desenleri + config'teki anahtar değerleri; `password` sadece uyarı), `security/redact.py` (maskeleyici + logging filtresi), `logging_setup.py` (koşu başına `orkestra.log`).
- Sağlayıcı seçimine durum kontrolleri: onay, devre kesici, uzak sağlayıcıya gizli bilgi, bütçe ön kontrolü. Elenen her sağlayıcının nedeni yazılıyor; elenen yerine sıradaki seçiliyor.
- `ask`: onay yoksa kod 4, bütçe/devre/gizli bilgi kod 3; bütçe rezervasyonu ve mutabakat; sağlık kaydı; `--allow-secrets`; tüm koşu dosyaları maskeleniyor; `runs` tablosuna kayıt.
- Komutlar: `orkestra providers list|enable|disable`, `orkestra budget [--json]`. `doctor` artık onay eksiklerini ve beklemedeki sağlayıcıları gösteriyor.
- README (en + tr) Faz 3'e göre güncellendi.

**Kabul kriterleri:**
- ✅ Eşzamanlılık: 10 ayrı süreç (multiprocessing, spawn, aynı anda başlayan bariyer) rezervasyon yapınca toplam limit aşılmıyor: tam 5 başarılı, 5 `BudgetExhausted`, toplam 500/500 token (`test_ten_processes_never_exceed_the_limit`, 5 kez arka arkaya geçti).
- ✅ Gün değişince (sahte saat, 23:59 → 00:01) bütçe sıfırlanıyor.
- ✅ `base_url` (ve model kimlikleri, anahtar değişkeni, başlıklar, ajan komutu/sandbox) değişince onay geçersiz; bütçe, `enabled`, zaman aşımı, kademe, fiyat değişince geçerli kalıyor.
- ✅ Ek: config'te fiyat yokken OpenRouter fiyat listesiyle tahmin yapılıyor; tahmin `daily_usd`'yi aşınca istek hiç gönderilmeden sıradaki sağlayıcıya geçiliyor.
- ✅ 3 geçici hata → sağlayıcı 5 dk kullanılmıyor; başarı sayacı sıfırlıyor (birim + CLI testleri).
- ✅ Redaksiyon: ortamdaki anahtar değeri `orkestra.log` dahil hiçbir koşu dosyasında ve çıktıda yok (sağlayıcı hatası anahtarı yansıttığında bile).
- ✅ Kullanıcının özel isteği: internet yokken uzak API 3 hatadan sonra beklemeye alınıyor, sonraki `ask` doğrudan Ollama'ya gidiyor (`test_offline_remote_is_paused_and_ollama_takes_over`). Bütçesi biten sağlayıcıdan sonrakine geçiş de testli.
- ✅ ruff, ruff format, pyright, pytest (337 test) temiz.

**Ertelenenler:**
- Aynı komut içinde otomatik yeniden deneme ve sıradaki adaya geçiş (bir istek hata verince hemen diğer sağlayıcıyı denemek) → Faz 4 (router + retry). Şu an hatalı istek kod 3 ile biter; sağlayıcı 3 hatadan sonra beklemeye alınır.
- `.orkestraignore` filtrelemesi → görev dosyası ve `globs` ile birlikte (Faz 5a).
- `gc` komutu (eski rezervasyonları silen fonksiyon hazır: `budget.purge_stale_reservations`) → Faz 5b.
- `-v/-q` log seviyesi seçenekleri.

**Bilinen sorunlar:**
- Fiyatı hiçbir kaynaktan bulunamayan (config'te yok, sağlayıcı yayınlamıyor, hiç kullanılmamış) bir modelin ilk isteği `daily_usd` sınırını aşabilir; `ask` ve `doctor` bunu uyarır (D-023, D-028).
- İlk sürümde "bütçe hariç tüm ayarlar" olan onay özeti daraltıldı (D-027); daha önce verilen onaylar bir kez yeniden istenir.

### Faz 2 – Chat adapter'ları, `ask`, `doctor` (2026-11-09)
**Yapılanlar:**
- `providers/base.py`: Mimari §4.3 veri sınıfları (`Usage`, `CompletionRequest/Result`, `AgentRequest/Result`, `HealthReport`) ve `ChatProvider` / `AgentProvider` protokolleri.
- `providers/ollama.py`: native `/api/chat`, her istekte `num_ctx` (modelin `context_window`'u) ve `num_predict`, `format: json`, `prompt_eval_count`/`eval_count`, `/api/tags` sağlık, hata eşleme (404 → `ollama pull` ipucu).
- `providers/openai_compat.py`: `AsyncOpenAI(max_retries=0)`, anahtar ortam değişkeninden, hata eşleme (401/403, 429 + `retry-after`, 400 + context, 404, 5xx, bağlantı/zaman aşımı), `usage.cost` (OpenRouter) → yoksa `price_per_mtok`, `json_object` reddedilirse bir kez istemle JSON ve model bazında hatırlama, `/models` sağlık. Hata metinlerinde anahtar maskeleniyor, SDK istisnası zincirlenmiyor.
- `providers/registry.py`: config → sağlayıcı nesnesi; router öncesi model seçimi.
- `tasks/context.py` (ilk hal): `--context` dosyaları, ikili tespiti (ilk 8 KB'de NUL), `max_context_bytes` aşımında hata (dosya boyutlarıyla), `<file path>` biçimi.
- `tasks/prompts.py` + `prompts/worker_system.md` (İngilizce işçi istemi, `CANNOT_DO:` kuralı).
- `envelope.py`: `ResultEnvelope` (§13 / README alanları), JSON ve insan çıktısı, kural tabanlı özet.
- `tasks/runner.py` (ilk hal): tek denemelik `ask`; `runs/<run_id>/` altında `task.yaml`, `attempts/1/request.json`, `attempts/1/response.txt`, `output.md`, `envelope.json`.
- `doctor.py`: config, her sağlayıcı (erişim, kurulu/listelenen modeller, anahtar değişkeni *var mı*), `git --version`, `codex`/`agy` PATH ve sürüm (bilgi), `--warm`.
- Komutlar: `orkestra ask "<istem>" [--provider] [--model] [--tier] [--context …] [--schema f.json] [--json]`, `orkestra doctor [--json] [--warm]`.
- `tests/integration/test_live.py` (`@pytest.mark.live`): gerçek Ollama ve OpenRouter.

**Kabul kriterleri:**
- ✅ respx testleri: başarı, 401 → `ProviderAuthError`, 429 + `retry-after`, 500, `finish_reason=length`, OpenRouter `usage.cost` okunuyor, Ollama `num_ctx` istekte gidiyor (`tests/unit/test_provider_ollama.py`, `test_provider_openai.py`).
- ✅ `ask --json` stdout'a sadece envelope JSON yazıyor (`json.loads(stdout)` testi; uyarılar stderr'de).
- ✅ `doctor` anahtar değerini hiçbir koşulda yazmıyor: sahte anahtar, anahtarı geri yansıtan 401 gövdesiyle, JSON ve insan modunda aranıyor (`test_doctor_never_prints_key_value`).
- ✅ Canlı (elle): yerel Ollama (`qwen2.5-coder:1.5b`) ile `orkestra ask "merhaba" --provider ollama` → "Merhaba", kod 0; `doctor --warm` modeli yükledi; `pytest -m live` Ollama testi geçti (OpenRouter testi anahtar olmadığı için atlandı).
- ✅ ruff, ruff format, pyright, pytest (255 test, 2 live hariç) temiz.

**Ertelenenler:**
- Gizli bilgi taraması ve redaksiyon (`security/`) → Faz 3. Şimdilik sadece OpenAI adapter'ı kendi anahtarını hata metinlerinden maskeliyor.
- Yeniden deneme, yükseltme, router → Faz 4/5a. `ask` tek deneme yapıyor.
- `.orkestraignore`/`.gitignore` filtreleme ve `globs` → görev dosyasıyla (Faz 5a).
- `runs` tablosu (state.db) → Faz 3. Koşu kaydı şimdilik sadece dosyalarda.
- Loglama (`orkestra.log`, `-v/-q`) → henüz yok.

**Bilinen sorunlar:**
- OpenRouter canlı testi bu makinede çalıştırılmadı (anahtar yok).
- `--context` tekrarlanan seçenek (`--context a --context b`); `--context a b` biçimi typer'da desteklenmiyor.

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
- ~~Kapanmamış parantez gibi YAML hatalarında satır numarası dosya sonunu gösterebiliyor.~~ Faz 4'te düzeltildi: mesaj yapının başladığı satırı da gösteriyor.

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
