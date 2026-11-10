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
