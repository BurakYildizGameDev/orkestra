# Kararlar

PROJE_DOKUMANTASYONU.md veya YAPILIS_PLANI.md'den her sapma burada kayıt altına alınır.

<!--
## D-001 – Başlık (YYYY-MM-DD, Faz N)
**Bağlam:** Neden karar gerekti?
**Karar:** Ne yapıldı?
**Alternatifler:** Neler düşünüldü, neden seçilmedi?
**Sonuç:** Neyi etkiliyor?
-->

## D-000 – Başlangıç kararları (2026-11-06)
- Dil Python 3.11+, paket yöneticisi uv.
- Ollama için OpenAI uyumlu uç nokta yerine native `/api/chat` (bağlam penceresi `num_ctx` gönderilebilsin diye).
- API işçileri düzenlemeyi diff değil tam dosya içeriği olarak döner.
- Tarayıcı otomasyonuyla web hesaplarına bağlanma kapsam dışı (kullanım şartları, kırılganlık).
- Kullanıcıya görünen metinler i18n ile (varsayılan İngilizce; tr, de, es, fr). Config anahtarları/değerleri, JSON alanları ve işçi istemleri İngilizce.
- YAML için ruamel.yaml (yorumları korumak için).
- Devir dosyası başlıkları sabit ve İngilizce.
- Kademe seçimini şef (Claude) yapar; LLM tabanlı zorluk sınıflandırma v1'de yok.

## D-001 – PyPI paket adı `orkestra-cli` (2026-11-09, Faz 0)
**Bağlam:** `https://pypi.org/pypi/orkestra/json` 200 döndü (ad alınmış); `orkestra-cli` 404 (boş).
**Karar:** Dağıtım adı `orkestra-cli`. İçe aktarma paketi (`import orkestra`) ve komut adı `orkestra` aynen kalır (`[tool.uv.build-backend] module-name = "orkestra"`).
**Alternatifler:** `orkestra-ai`, `orkestra-dispatch`; `-cli` eki planda önerildiği için seçildi.
**Sonuç:** Kurulum komutları `uv tool install orkestra-cli` olur; README/vitrin (Faz 14) buna göre yazılmalı.

## D-002 – `orkestra.cli:app` bir fonksiyon, typer uygulaması `build_app()` ile kuruluyor (2026-11-09, Faz 0)
**Bağlam:** typer yardım metinleri tanım anında sabitlenir; `--lang tr --help`'in Türkçe çıkması için dil, uygulama kurulmadan önce bilinmeli.
**Karar:** Giriş noktası `app(argv=None)` fonksiyonu: `--lang` değerini argv'den önceden okur, `i18n.init_language()` çağırır, sonra `build_app()` ile typer uygulamasını kurup çalıştırır. `OrkestraError` → `exit_code_for`, diğer istisnalar → 10. Testler `app([...])` veya `build_app()` kullanır.
**Alternatifler:** Tembel (lazy) çevrilen help string'leri – click/rich bunları düz `str` gibi işlediği için kırılgan.
**Sonuç:** Faz 1+ komutları `build_app()` içinde tanımlanmalı (help metinleri `t()` ile). Config'teki `language` Faz 1'de `init_language(config=...)` ile bağlanacak.

## D-003 – Yakalanmamış sağlayıcı hataları çıkış kodu 3 (2026-11-09, Faz 0)
**Bağlam:** Mimari, `ProviderAuthError` vb. sınıfların CLI'ye kadar sızması durumunda hangi kodu alacağını söylemiyor.
**Karar:** `ProviderError` ailesi varsayılan olarak `ExitCode.NO_PROVIDER` (3): normalde router bunları yakalar; sızıyorsa isteği karşılayabilecek sağlayıcı kalmamıştır.
**Sonuç:** Faz 2–4'te zorla verilen sağlayıcı hatalarında farklı kod gerekirse burada güncellenir.

## D-004 – `AGENTS.md` okuma listesindeki yollar `docs/` önekli (2026-11-09, Faz 0)
**Bağlam:** Ek C, `AGENTS.md`'yi "olduğu gibi" oluşturmayı söylüyor ama plan belgeleri Mimari §2 ve Ek C gereği `docs/` altında.
**Karar:** Okuma listesinde `docs/PROJE_DOKUMANTASYONU.md` ve `docs/YAPILIS_PLANI.md` yazıldı; geri kalan içerik birebir.

## D-005 – Araç ayarları: `docs/` ruff dışında, `ı` izinli, katı i18n modu (2026-11-09, Faz 0)
- `ruff format` Markdown içindeki Python bloklarını da biçimlendiriyor; plan belgeleri bozulmasın diye `extend-exclude = ["docs"]`.
- Türkçe test/docstring metinleri `RUF001/RUF002` uyarısı veriyor; `allowed-confusables = ["ı"]`.
- Mimari §18 "İngilizcede de yoksa anahtarın kendisini döner ve testte hata verir": `ORKESTRA_I18N_STRICT=1` (testlerde `conftest.py` açar) eksik anahtarda `KeyError` fırlatır. Boş çeviri değeri İngilizceye düşer; eksik yer tutucu değeri `{ad}` olarak bırakılır (çökme yok).
- pyright `pyright[nodejs]` ekstrasıyla kuruluyor (Node.js gerektirmesin, CI ve Windows'ta tutarlı).
- `.gitattributes` `* text=auto eol=lf`: Windows'taki `core.autocrlf` farkları sahte diff üretmesin (Faz 5 tuzağı), CI'da ruff format tutarlı olsun.

## D-006 – Config modelleri bilinmeyen alanları reddeder (2026-11-09, Faz 1)
**Bağlam:** Mimari bilinmeyen anahtarlar için bir şey söylemiyor; pydantic varsayılanı sessizce yok saymak.
**Karar:** Tüm config modellerinde `extra="forbid"`: `defaults.profil` gibi yazım hataları `bilinmeyen alan` hatası verir.
**Sonuç:** İleride alan kaldırılırsa eski config'ler hata verir; `version` artırılarak yönetilmeli.

## D-007 – `OpenAICompatProvider.api_key_env` varsayılanı `None` (2026-11-09, Faz 1)
Mimari'de varsayılansız (`str | None`), yani alanın yazılması zorunlu. LM Studio gibi anahtarsız yerel sunucular için alanın hiç yazılmaması yeterli olsun diye `= None`.

## D-008 – Yerleşik profiller ve şefler her zaman var (2026-11-09, Faz 1)
**Bağlam:** "Profil adları cheap, balanced, quality". Kullanıcı `profiles:` altına tek bir profil yazınca yerleşikler kaybolsaydı `defaults.profile: balanced` geçersiz olurdu.
**Karar:** `profiles` ve `chiefs` kullanıcı girdileri yerleşiklerin üstüne birleştirilir (aynı adlı yerleşik ezilebilir, yenisi eklenebilir, yerleşik silinemez).

## D-009 – Config arama ayrıntıları (2026-11-09, Faz 1)
- Git deposu dışında proje dosyası sadece çalışma dizininde aranır (dosya sistemi köküne kadar yukarı çıkılmaz). Git kökü `.git` dizini veya dosyası (worktree) ile bulunur.
- `--config` veya `ORKESTRA_CONFIG` verilip dosya yoksa kod 2; varsayılan genel dosya yoksa sorun değil.
- Hiç config dosyası yoksa yerleşik varsayılanlar (`version: 1`, sağlayıcı yok) kullanılır. Dosya varsa birleşmiş halde `version` zorunlu.
- `providers.<ad>: null` silme kuralı sadece sağlayıcı seviyesinde; başka yerde `null` bir değerdir (örn. `estimate.confirm_above_usd: null` = onay eşiği yok).

## D-010 – `init` hedefi ve `.gitignore` (2026-11-09, Faz 1)
- Varsayılan hedef genel config (`--config` / `ORKESTRA_CONFIG` / `~/.orkestra/config.yaml`); `--project` ile `./orkestra.yaml`. Hedef seçimi Faz 11 sihirbazında soru olarak gelecek.
- `.orkestra/cache/` satırı sadece git deposu içindeyken, deponun kök `.gitignore`'una eklenir; eşdeğer satır varsa (`/.orkestra/cache` dahil) dokunulmaz, satır sonu stili korunur.
- `--force` eski dosyayı `<ad>.bak` olarak saklar.

## D-011 – `--json` modunda hatalar da JSON (2026-11-09, Faz 1)
§13 "stdout'a tek bir JSON belgesi" kuralı hata durumuna da uygulanır: `{"error": {"code", "type", "message", "details"}}`, çıkış kodu değişmez. JSON ASCII kaçışlı yazılır (`ensure_ascii`), Windows'ta UTF-8 olmayan borularda bozulmasın diye. Click'in kendi kullanım hataları (bilinmeyen seçenek vb.) bu kapsamda değil, stderr'e gider.

## D-012 – Örnek config ve ek kısıtlar (2026-11-09, Faz 1)
- `example.yaml` yorumları İngilizce (config anahtarları gibi dil bağımsız; Faz 14 İngilizce dokümanla uyumlu).
- Örnekte `agy` için `enabled: false` (README "Sınırlamalar": deneysel, varsayılan kapalı).
- Mimari'de olmayan sayısal kısıtlar eklendi: bütçe ve sayaçlar `>= 0`, `concurrency`/`timeout_s`/`context_window` gibi alanlar `>= 1`, profil kademeleri 1–3.
- Config'teki `language`, uygulama kurulmadan önce doğrulamasız okunur (`loader.read_language`); bozuk config `--help`'i engellemez.

## D-013 – `openai` SDK 3.x'in altında tutuluyor (2026-11-09, Faz 2)
**Bağlam:** `openai` 3.x HTTP katmanı için `httpx` yerine ayrı `httpx2` paketini kullanıyor; `respx` onu yakalayamıyor (deneme: bağlantı hatası). Plan ve Mimari §16 HTTP testlerinin `respx` ile yapılmasını istiyor.
**Karar:** `openai>=1.40,<3` (kilitli sürüm 2.54.0, `httpx` tabanlı).
**Alternatifler:** `http_client` ile `httpx2` mock transport'u enjekte etmek; bu respx'ten vazgeçmek, yani test stratejisinden sapmak demek.
**Sonuç:** 3.x'e geçmek için respx'in `httpx2` desteği veya başka bir mock yöntemi gerekir.

## D-014 – Mimari §2'de olmayan modül ve servis yerleri (2026-11-09, Faz 2)
- `src/orkestra/doctor.py`: `doctor` kontrolleri (cli.py iş mantığı içermesin diye). §2'de karşılığı yok.
- `ask` servisi `tasks/runner.py`'nin ilk hali olarak yazıldı (Faz 5'te tam yaşam döngüsüne genişleyecek).
- Router öncesi model seçimi `providers/registry.py` içinde (`select_chat_target`); Faz 4'te router'a devredilecek.

## D-015 – Router öncesi model seçim kuralları (2026-11-09, Faz 2)
- Hiçbir şey verilmezse: config sırasıyla ilk uygun sağlayıcının `--tier` (varsayılan 1) kademesindeki modeli; aynı kademede `priority` yüksek olan önce.
- Uygun değil: `cli_agent`, `enabled: false`, `api_key_env` tanımlı ama ortamda yok. Hiç aday kalmazsa kod 3 ve her sağlayıcı için neden.
- `--provider` verilip `--tier` verilmezse o sağlayıcının en düşük kademesi (kademe-1 modeli olmayan sağlayıcı da seçilebilsin).
- `--provider` + `--model` verilirse model config'te listelenmese de kullanılır (kullanıcı açıkça istedi).
- `providers` boşsa kod 2 ve "`orkestra init` çalıştır" (Mimari §4.1).

## D-016 – Hata eşleme ayrıntıları (2026-11-09, Faz 2)
- Ollama: bağlantı reddi → `ProviderUnavailable`; 404 → `ProviderUnavailable` + `ollama pull <model>` ipucu; zaman aşımı ve 5xx → `ProviderTransient`.
- OpenAI uyumlu: 404 → `ProviderUnavailable`; diğer 4xx → `ProviderError` (kod 3). Anahtar değişkeni ortamda yoksa `ProviderUnavailable`, mesajda sadece değişken adı.
- SDK istisnaları `from None` ile yeniden fırlatılır ve hata ayrıntısında anahtar `***` ile değiştirilir: OpenAI 401 mesajları anahtarı geri yansıtabiliyor.
- `HealthReport` Mimari'de tanımlı değildi: `ok`, `models`, `version`, `error` alanlarıyla tanımlandı.

## D-017 – Faz 2 `ask` davranışı (2026-11-09, Faz 2)
- Tek deneme; sağlayıcı hatasında envelope `status=error` yazılır (ve `--json`'da stdout'a basılır), çıkış kodu hatanın kodu (sağlayıcı hataları 3).
- `finish_reason=length`: durum `ok` kalır, stderr'e "çıktı sınırına ulaştı" uyarısı.
- `--schema`: `json_mode` açılır, cevap (kod çitleri temizlenerek) JSON Schema ile bir kez doğrulanır; geçmezse `status=failed`, kod 1. Yeniden deneme Faz 5a'da.
- Özet: ilk 400 karakter, kelime sınırında; "(tam metin: …)" eki sadece kesildiyse.
- `Escalation` modeli şimdilik `provider, model, tier, reason`; Faz 5'te gerekirse `envelope_version` artırılarak değişir.
- JSON çıktısı ASCII kaçışlı (D-011 ile aynı neden).

## D-018 – `doctor` çıkış kodu ve durumları (2026-11-09, Faz 2)
Her kontrol `ok | warn | fail | info`. Herhangi bir `fail` varsa kod 1, yoksa 0. Anahtar değişkeni eksikliği `warn` (o sağlayıcı kullanılamaz ama diğerleri çalışır), erişilemeyen veya kimlik doğrulaması başarısız sağlayıcı `fail`, `git` yoksa `fail`, `codex`/`agy` sadece bilgi.

## D-019 – `--context` tekrarlanan seçenek (2026-11-09, Faz 2)
README `--context <dosya...>` yazıyor; typer seçeneklerde çok değer (nargs) desteklemiyor. Kullanım: `--context a.py --context b.py`.

## D-020 – `usage` tablosunda `created_at` sütunu (2026-11-09, Faz 3)
**Bağlam:** §6.1 "1 saatten eski rezervasyonlar sayılmaz" diyor ama §6'daki `usage` şemasında zaman sütunu yok.
**Karar:** İlk migration'a `created_at TEXT` (yerel saat dilimli ISO) ve `(provider, day)` indeksi eklendi. Karşılaştırma Python'da saat dilimli `datetime` ile yapılıyor (yaz saati ve saat dilimi farkları metin karşılaştırmasını bozmasın diye).

## D-021 – Durum kontrolleri router'dan önce, seçimde (2026-11-09, Faz 3)
- Onay, devre kesici, uzak sağlayıcıya gizli bilgi ve bütçe ön kontrolü `select_chat_target`'a kontrol fonksiyonları olarak verilir; elenen sağlayıcının yerine sıradaki seçilir. Faz 4'te router bu kontrolleri devralacak.
- Onay her sağlayıcı tipi için zorunlu, Ollama dahil (§7 "ollama için de").
- Hiç aday kalmazsa ve en az birini onay eksikliği eledi ise kod 4 (`ConsentRequired`), değilse kod 3. Her iki durumda tüm nedenler listelenir.
- Kesin bütçe kontrolü rezervasyonda (`BEGIN IMMEDIATE`); yarışta kaybeden istek envelope `status=error`, kod 3 ile biter.

## D-022 – Devre kesici hangi hataları sayar (2026-11-09, Faz 3)
`ProviderTransient`, `ProviderRateLimit` ve `ProviderUnavailable` (bağlantı reddi / internet yok dahil) geçici sayılır: 3 ardışık hata → 5 dk. `ProviderAuthError` → hemen 1 saat. `ContextTooLong`, `ProviderBadOutput` ve diğer 4xx isteğe özgü olduğundan sayılmaz. Bekleme süresi bitince sayaç başarıya kadar sıfırlanmaz; ilk yeni hata sağlayıcıyı yeniden 5 dk bekletir (yarı açık durum).

## D-023 – Bütçe ayrıntıları (2026-11-09, Faz 3)
- Bir `ask` = 1 koşu + 1 istek. Başarısız istek de 1 istek sayılır (token 0); kesinti (Ctrl+C) rezervasyonu siler.
- Maliyet tahmini için fiyat sırası: config `price_per_mtok` → sağlayıcının `/models` fiyat listesi (OpenRouter) → bu modelin geçmiş kullanımındaki en yüksek token başı maliyet (D-028). Hiçbiri yoksa tahmin 0'dır; o zaman `daily_usd` sadece hiç kullanılmamış, fiyatı yayınlanmamış bir modelin ilk isteğinde aşılabilir ve hem `ask` hem `doctor` bunu uyarır.

## D-024 – Gizli bilgi ve maskeleme kapsamı (2026-11-09, Faz 3)
- Engelleyen bulgular: §11 desenleri (`sk-…`, `sk-or-v1-…`, `AKIA…`, özel anahtar başlığı, `gh*_…`, `github_pat_…`, `xox*-…`, `AIza…`) ve config'teki `api_key_env` değişkenlerinin ortamdaki değerleri (8 karakterden kısa değerler hariç). `password = …` sadece uyarı.
- Bulgu mesajları değeri asla içermez (dosya, satır, tür).
- Maskeleme koşu dizinine yazılan her dosyaya (istek, yanıt, `output.md`, envelope, log) ve `ask`'ın ekrana bastığı cevaba uygulanır; yani yerel modelin cevabında geçen anahtar da `***` olur.
- `.orkestraignore` filtrelemesi Faz 5a'ya (görev dosyası `globs` ile) bırakıldı.

## D-025 – Onay ayrıntıları (2026-11-09, Faz 3)
- Özetin kapsamı D-027 ile daraltıldı: sadece verinin nereye gittiğini ve neyin çalıştırılacağını belirleyen alanlar.
- `providers enable`: TTY yoksa ve `--yes` yoksa kod 2. Windows `NUL`'u TTY gösterdiği için soru EOF/Abort ile karşılaşırsa da kod 2. Kullanıcı "hayır" derse kod 4.
- `providers disable` onayı siler; config'teki `enabled` alanına dokunmaz.

## D-026 – `doctor`'a durum satırları (2026-11-09, Faz 3)
Açık sağlayıcılar için onay eksikliği (`warn`, çözüm: `orkestra providers enable <ad>`) ve devre kesicinin beklettiği sağlayıcılar (`warn`, son hata ile) gösterilir. Bunlar `fail` değil: kullanıcı düzeltebilir ve diğer sağlayıcılar çalışır.

## D-027 – Onay özeti sadece güvenlikle ilgili alanlardan (2026-11-09, Faz 3)
**Bağlam:** Mimari §6.3 özeti "bütçe hariç tüm sağlayıcı ayarları"ndan hesaplıyor. Bu yüzden `enabled`, `timeout_s`, `concurrency` veya bir modelin `tier`'ı değişince de yeniden onay isteniyordu; kullanıcıyı gereksiz yere yoruyor ve onayı anlamsızlaştırıyor.
**Karar:** Özet şu alanlardan hesaplanır: `type`, `base_url`, `local`, `api_key_env`, `extra_headers`, `command`, `kind`, `sandbox`, `extra_args`, `model` (ajan) ve model kimlikleri (`models[].id`, sıralı). Değişmesi yeniden onay istemeyenler: `enabled`, `budget`, `timeout_s`, `concurrency`, `experimental`, modellerin `tier`/`priority`/`context_window`/fiyat/`strengths` alanları.
**Neden model kimlikleri dahil:** OpenRouter gibi yönlendiricilerde yeni bir model kimliği verinin başka bir şirkete gitmesi demek (`anthropic/…` → `deepseek/…`).
**Sonuç:** Özet hesabı değiştiği için bu değişiklikten önce verilen onaylar bir kez geçersiz olur (`providers enable` ile yeniden).

## D-028 – Fiyat kaynakları ve önbelleği (2026-11-09, Faz 3)
**Bağlam:** `price_per_mtok` yazılmayan modellerde maliyet tahmini 0 olduğu için `daily_usd` istekten önce uygulanamıyordu.
**Karar:** Yeni modül `providers/pricing.py` (§2'de yok). Fiyat sırası: config → sağlayıcı listesi → geçmiş kullanım.
- Sağlayıcı listesi: `GET {base_url}/models`, OpenRouter'ın `pricing.prompt`/`pricing.completion` (USD/token) alanları. `-1` (değişken fiyat) yok sayılır. Sadece `daily_usd` tanımlı ve fiyatsız modeli olan `openai_compat` sağlayıcılar için çekilir. Önbellek `~/.orkestra/cache/prices.json`, 24 saat; başarısız çekim (ör. internet yok) 1 saat sonra yeniden denenir, böylece çevrimdışıyken her komut 5 sn beklemez. `base_url` değişirse önbellek geçersiz. Önbellekte anahtar tutulmaz.
- Geçmiş kullanım: `usage` tablosundaki gerçek kayıtlardan en yüksek `cost / (prompt + completion)` oranı, girdi ve çıktı için aynı oran (temkinli).
- Fiyat yine bilinmiyorsa `ask` stderr'e, `doctor` `warn` olarak uyarır. `doctor` fiyat listesini her çalıştığında tazeler ve hangi kaynaktan geldiğini gösterir.

## D-029 – "Bağlantı hiç kurulamadı" ayrı hata: bir kısa deneme, sonra atla (2026-11-09, Faz 4)
**Bağlam:** Mimari §4.3/§5.2 bağlantı hatasını `ProviderTransient` sayıyordu; §7.1'e göre bu 1+2+4 sn bekleyişli yeniden deneme demek. İnternet yokken her komut ~7 sn bekler, sonra yerel modele düşerdi. Kullanıcının önceliği internet yokken hızlı yedeğe geçiş. Ama hiç yeniden denememek de anlık bir ağ dalgalanmasında sağlayıcıyı gereksiz yere atlatır.
**Karar:** Yeni hata sınıfı `ProviderConnectionError` (`ProviderUnavailable` alt sınıfı): DNS hatası, ağ yok, bağlantı reddi (Ollama `httpx.ConnectError`, OpenAI uyumlu `APIConnectionError` ama zaman aşımı değil). Router 0.5 sn sonra **bir kez** yeniden dener; yine olmazsa sağlayıcının tüm modellerini bu koşuda atlar. Zaman aşımı, 5xx ve 429 geçici kalır (1-2-4 sn). Anahtar/model yok gibi diğer `ProviderUnavailable` durumları hiç yeniden denenmez.
**Sonuç:** İnternet yokken yerel modele geçiş ~0.5 sn; devre kesici her başarısız denemeyi saydığı için ikinci komutta uzak sağlayıcı beklemeye alınır ve sonrakilerde hiç denenmez. Mimari §4.3, §5.2, §7.1 buna göre güncellendi (D-034).

## D-030 – Envelope v2: `failovers` (2026-11-09, Faz 4)
Envelope'a `failovers` listesi eklendi (sağlayıcı, model, kademe, hata sınıfı, neden, deneme sayısı) ve `envelope_version` 2 oldu (§13). `escalations`'a, sıradaki aday daha yüksek kademedeyse son bırakılan aday yazılır (§8). Tüm adaylar başarısızsa `status=error`, `error="All N candidate(s) failed…"`, kod 3.

## D-031 – Sıralama: kademe → priority → config'teki sıra (2026-11-09, Faz 4)
**Bağlam:** §7 adım 4 "kademe → priority → kalan bütçe oranı → ad" diyordu. Uygulayınca iki sürpriz çıktı: config'te üstte yazılan sağlayıcı, adı alfabede sonra geliyorsa geride kalıyordu; bütçesi tanımsız sağlayıcı (oran hep %100) biraz harcamış olanı hep geçiyordu.
**Karar:** Sıralama kademe ↑ → (Faz 12: adaptive skor) → `priority` ↓ → config'teki sıra: sağlayıcılar yazıldığı sırayla, sonra modelleri listelendiği sırayla. Kullanıcı tercihini sırayla belirtir; `priority` bunu ezmek içindir. Kalan bütçe sıralamayı etkilemez, sadece eler (rezervasyon aynen çalışır); oran `--dry-run`'da bilgi olarak gösterilir. Genel + proje config birleşince sıra genelinkidir, projede yeni eklenen sağlayıcılar sona gelir.
**Alternatifler:** Yük dengeleme için kalan bütçe sıralaması ileride açık bir ayarla (`routing.balance_budget`) geri gelebilir.
**Sonuç:** Görev kademesi verilmezse 1'dir ve aralık profilin üst sınırına kadar uzanır, yani üst kademeler yedek olarak denenir (yükseltme). Mimari §7 güncellendi (D-034).

## D-032 – Yeniden deneme ayrıntıları (2026-11-09, Faz 4)
- Taşıma denemeleri `max_retries`'tan sayılmaz; aday başına en fazla 3 yeniden deneme (toplam 4 istek). Bağlantı hiç kurulamazsa sadece 1 kısa (0.5 sn) yeniden deneme (D-029). Ama her başarısız deneme devre kesiciye yazılır; devre açılınca (3. ardışık hata) beklemeden sıradaki adaya geçilir ve aynı sağlayıcının diğer modelleri de bu koşuda atlanır.
- `retry-after` 60 sn'den uzunsa beklenmez, sıradaki adaya geçilir.
- `ProviderAuthError`, `ProviderUnavailable` ve denemesi biten `ProviderConnectionError` → sağlayıcının tüm modelleri bu koşuda atlanır. `ContextTooLong` → sadece daha büyük `context_window`'lu adaylar kalır. `ProviderBadOutput`, diğer 4xx ve rezervasyondaki bütçe yarışı → sıradaki aday.
- Her deneme `attempts/<n>/request.json` (sağlayıcı adıyla) ve başarılıysa `response.txt`.

## D-033 – Router ayrıntıları (2026-11-09, Faz 4)
- Deneysel sağlayıcı ancak config'te `enabled: true` açıkça yazılmışsa aday olur (pydantic `model_fields_set` ile; varsayılan `true` yetmez).
- Zorla sağlayıcı + config'te olmayan model: güvenilir, aralığın alt kademesine konur.
- Bağlam kontrolü: tahmini istem token'ı (karakter/3.5) ≤ `context_window × 0.8`.
- `ask --local-only` eklendi (`privacy: local_only`, Faz 5a'da görev dosyasında da var).
- `--dry-run`: aday yoksa da raporu basar, kod 3 (onay eksikse 4). Bütçe, koşu dizini, istek yok. Fiyat listesi gerekiyorsa tazelenebilir (D-028).
- D-014'teki `registry.select_chat_target` kaldırıldı; seçim router'da.

## D-034 – Mimari belgesi kararlarla eşitlendi (2026-11-09, Faz 4 sonu)
**Bağlam:** `AGENTS.md` Mimari bölümünü "tek doğruluk kaynağı" sayıyor. Sapmalar sadece DECISIONS.md'de kalırsa, Mimari'yi okuyan başka bir ajan bir kararı "düzeltmeye", yani eski haline döndürmeye kalkabilir.
**Karar:** Yereldeki `docs/PROJE_DOKUMANTASYONU.md` (git dışında) D-001 … D-034 ile eşitlendi: paket adı, `openai<3`, klasör yapısına `doctor.py`, `providers/pricing.py`, `state/migrations/`; §4.1 ek kurallar; §4.3 hata sınıfları ve `HealthReport`; §5.2 hata eşleme ve fiyat listesi; §6 `created_at`; §6.1 fiyat kaynakları; §6.2 sayılan hatalar; §6.3 onay alanları; §7 eleme ve sıralama; §7.1 yeniden deneme; §13 envelope v2 ve JSON hata belgesi. Değişen her yerde karar numarası yazılı.
**Kural (bundan sonra):** Yeni bir sapma hem DECISIONS.md'ye hem Mimari'ye yazılır. Not: `Downloads/` altındaki orijinal kopya eski haliyle duruyor; güncel olan `docs/` altındaki.

## D-035 – Faz 0 kod denetimi düzeltmeleri (2026-11-09)
`/code-review` (PR #1) bulgularına göre:
- `--lang` değeri `ORKESTRA_LANG` gibi normalize edilir (`TR`, `tr_TR` kabul).
- Sistem dili POSIX kuralıyla: ilk tanımlı `LC_ALL`/`LC_MESSAGES`/`LANG` karar verir; `C`/`POSIX` → İngilizce, desteklenmeyen değer → sistem dili yok. (Önceki davranış `LC_ALL=C LANG=tr_TR`'de Türkçe gösteriyordu.)
- `--lang`/`--config` ön taraması ilk alt komutta durur; alt komut argümanları dili değiştiremez.
- `t()` biçimlendirme hatasında çökmez (ham metin, katı modda `TranslationError`); katalog testleri her metnin biçimlendirilebildiğini denetler.
- i18n hataları `errors.py`'den: `TranslationError(InternalError)`, geçersiz dil `UsageError`.
- Son çare hata yakalayıcısı çeviri bozuk olsa da düz İngilizce mesajla kod 10 verir; ayrıntı 300 karakterle sınırlı.
- Mesajsız hata "Error: <HataSınıfı> (no details)" olarak gösterilir.
- Sürüm tek kaynaktan: `pyproject.toml` → `importlib.metadata.version("orkestra-cli")`.
- `AGENTS.md`: plan belgeleri yerel; klonda yoksa kullanıcıdan istenir.
- Atlanan: `--version --lang xx` (sürüm basıp çıkıyor) – önemsiz.
Mimari §18 güncellendi (D-034 kuralı).

## D-036 – Faz 1 ve Faz 2 kod denetimi düzeltmeleri (2026-11-10)
`/code-review` (PR #2 ve #3) bulgularına göre:
- **Config birleştirme:** `providers.<ad>: null`, daha önceki dosyada `providers` bölümü olmasa da sağlayıcıyı siler (boş eşlemeye birleştirilir).
- **`init`:** `--force` önceki yedeği asla ezmez (`.bak`, `.bak.1`, …); dosya hâlâ değiştirilmemiş örnekse yedek almaz. `.gitignore`'a `.orkestra/cache/` sadece `--project` ile eklenir (genel config'in çalışılan depoyla ilgisi yok). UTF-8 olmayan `.gitignore` bayt bayt korunur.
- **CLI:** `--json` modunda beklenmeyen hata da stdout'a tek JSON belgesi verir (D-011). Dil ön taraması hata yakalayıcının içinde ve dosya sistemi hatalarında çökmez. `--config ~/...` genişletilir. `config show`, `extra_headers` içindeki kimlik bilgisi gibi görünen başlıkları (`Authorization`, `*key*`, `*token*`…) ve anahtar desenine uyan değerleri `***` gösterir. Konsol kod sayfasının yazamadığı karakterler (ör. Windows'ta yönlendirilmiş çıktıda emoji) `?` olur; tam metin `output.md`'de.
- **Şema:** boş `chiefs.*.launch`, boş `command`, boş `models` ve yarım `price_per_mtok` (sadece input ya da output) reddedilir. Eşlenmemiş pydantic hataları da çevrili çerçeveyle gösterilir. Config dosyaları bir çağrıda bir kez ayrıştırılır (içeriğe göre önbellek).
- **OpenAI uyumlu adapter:** hata metninde anahtar önce maskelenir, sonra 300 karaktere kısaltılır. Model `max_tokens`'ı reddedip `max_completion_tokens` isterse (OpenAI o-serisi, gpt-5) o parametreyle tekrar gönderilir ve model için hatırlanır; bu durumda JSON modu suçlanmaz. Sağlık kontrolünde 404 artık "model '' bulunamadı" değil, `base_url`'i gösterir.
- **Ollama:** tahmini istem `num_ctx`'e sığmıyorsa istek gönderilmeden `ContextTooLong` (Ollama aşan istemi hatasız keser; Mimari §5.1). İstek zaman aşımı varsayılanı en az 600 sn (`registry.request_timeout`, doctor da aynı). Sağlık kontrolünde 404 → adres hatası, JSON olmayan cevap → bozuk cevap (bağlantı hatası değil).
- **`CANNOT_DO`:** işçi `CANNOT_DO: <neden>` derse koşu başarılı sayılmaz: aynı kademedeki diğer adaylar atlanır, daha üst kademeye geçilir (Mimari §8.1). Üst kademe kalmadıysa `status=escalate`, çıkış kodu 1. Failover kaydında hata sınıfı `CannotDo`. (Doğrulama geri bildirimiyle yeniden deneme hâlâ Faz 5a'da.)
- **doctor:** `--warm` boş/tek satır sonu cevabı başarı sayar (model yüklendi ve cevap verdi). Sağlayıcılar aynı anda kontrol edilir, sırayla raporlanır.
- **Bağlam:** boyut sınırı dosyalar tamamen okunmadan önce (`stat`) denetlenir; ikili dosyalar sayılmaz. `<file path="…">` içindeki yol HTML kaçışlı, dosya içindeki `</file>` `<\/file>` olarak yazılır.
- **Küçükler:** `retry_after` iki adapter'da ortak (`providers/base.py`); anahtar varlığı tek yerde (`openai_compat.read_api_key`); envelope'taki "ok/FAIL" ve şemanın "nesne değil" hatası çevrili.
- **Zaten çözülmüş:** bağlantı hatasının iki adapter'da farklı sınıflanması D-029 ile Faz 4'te giderilmişti.

## D-037 – Faz 3 ve Faz 4 kod denetimi düzeltmeleri (2026-11-10)
`/code-review` (PR #4 ve #5) bulgularına göre:
- **Yeni hata sınıfları (Mimari §4.3):** `ProviderTimeout(ProviderTransient)` – cevap gelmedi ama sağlayıcı isteği işlemiş ve ücretlendirmiş olabilir. `ProviderModelNotFound(ProviderError)` – sağlayıcı çalışıyor ama modeli tanımıyor (404). `ProviderUnavailable` artık model yokluğunu kapsamıyor.
- **Model yok (404):** sadece o model atlanır (`Action.NEXT`); aynı sağlayıcının diğer modelleri denenir ve devre kesici saymaz (istek hatalı, sağlayıcı değil). Önceden tüm sağlayıcı atlanıyor, 3 seferde 5 dk duraklatılıyordu.
- **Bütçe:**
  - Sağlayıcı maliyeti bildirmezse gerçek maliyet modelin çözülen fiyatıyla (config → fiyat listesi → geçmiş) hesaplanır; önceden fiyat listesinden geliyorsa 0 kaydediliyordu ve `daily_usd` hiç dolmuyordu. Geçmişten gelen fiyatla hesaplanan maliyet "tahmini" işaretlenir. Adapter artık fiyat hesaplamaz, sadece bildirilen maliyeti verir.
  - Token sayısı bildirilmezse metinden tahmin edilir (0 değil).
  - Zaman aşımında rezerve edilen tahmin harcanmış sayılır (`budget.settle_as_reserved`); diğer başarısız istekler 0 kalır.
  - Yeniden denemeler ve yedeğe geçişler `daily_runs` için sağlayıcı başına tek koşu sayılır.
  - Rezervasyon bütçe yarışında reddedilirse bu bir deneme sayılmaz (`attempts/<n>/` yazılmaz).
  - Kullanılmayan `budget.check` kaldırıldı.
- **Fiyat listesi çekimi (D-028'e ek):** sadece görevin kapsamındaki, açık, **onaylı** ve (`--local-only` değilse) uzak sağlayıcılardan çekilir; istek API anahtarını taşıdığı için onaysız sağlayıcıya hiç gitmez. `doctor` da sadece onaylılara sorar. `ask --dry-run` hiç ağa çıkmaz, önbellekteki fiyatları kullanır (D-033'teki "tazelenebilir" notu geçersiz).
- **Router:** açıkça verilen `--model` profilin kademe aralığına takılmaz. Görev kademesi profilin üst sınırını aşarsa: profil açıkça verildiyse kullanım hatası (kod 2), varsayılan profilse aralık o kademeye daralır. Config'te listelenmeyen ama açıkça seçilen modelin fiyatı da çözülür. Snapshot sadece router'ın bakacağı sağlayıcıları okur (kod ajanları ve kapalılar hariç); geçmiş kullanımdan fiyat sorgusu sadece `daily_usd` olanlarda.
- **Devre kesici:** `providers enable` devreyi kapatır (yanlış anahtar düzeltilince 1 saat beklemek gerekmez).
- **Gizli bilgi:** istem metni de taranır (`ask "$(cat .env)"`). `sk-` deseni kelime içinde eşleşmez (`task-runner-…` artık anahtar sayılmaz). İşçinin cevabında sadece gerçek sırlar maskelenir; `password: …` örneği cevapta kalır ve şema doğrulaması maskelenmemiş cevaba yapılır (maskeleme geçerli JSON'u bozmasın). Kayıtlar ve loglar eskisi gibi tam maskelenir.
- **Yarıda kalan koşu:** Ctrl+C veya beklenmeyen hata olsa da `runs` satırı `error` ile kapanır ve `envelope.json` yazılır; rezervasyon serbest bırakılır.
Mimari §4.3, §5.1, §6.1, §6.2, §7, §7.1 ve §11 bu kararlarla güncellendi.

## D-038 – Görev dosyası ve doğrulama ayrıntıları (2026-11-10, Faz 5a)
- **Göreli yollar:** görev dosyasındaki göreli yollar (bağlam dosyaları/globs, şema dosyaları, `files_exist`, `command`'ın çalıştığı dizin) görevin taban dizinine göre çözülür: `workspace` verilmişse o, yoksa `orkestra`'nın çalıştırıldığı dizin. Görev dosyasının kendi dizini değil: şef görevi `.orkestra/tasks/` gibi bir yere yazıp depo kökünden çalıştırır, yollar depoya göre yazılır.
- **Kontroller geçmezse:** aynı model önceki cevabını (en fazla 8000 karakter) ve başarısız kontrollerin ayrıntısını (en fazla 2000 karakter, `prompts/retry_feedback.md`) alıp `max_retries` kez daha dener. Hâlâ geçemezse **üst kademeye** geçilir ve aynı kademedeki diğer adaylar atlanır (CANNOT_DO'daki gibi, D-036); aynı yetenekteki başka modeli denemek genelde aynı sonucu verir ve bütçe harcar. Sağlayıcı hataları ise eskisi gibi aynı kademede yedeğe geçer. Failover kaydında hata sınıfı `VerificationFailed`.
- **Sonuç durumu:** son sorun başarısız kontrolse ve son cevap kademe 3'teyse `escalate`, değilse `failed` (Mimari §8: "kademe 3 denendiyse escalate"). Son sorun CANNOT_DO ise `escalate`. İkisi de kod 1; son cevap `output.md`'de ve envelope'ta `verification` ile durur.
- **Geri bildirim dili:** işçiye giden metin her zaman İngilizce (AGENTS.md), envelope'taki `detail` arayüz dilinde. Bunun için `i18n.t_in(lang, key)` eklendi; doğrulayıcılar mesajı anahtar + parametre olarak üretir ve iki kez işler. Geri bildirim, kayıtlar gibi maskelenir (komut çıktısında sır olabilir).
- **`limits`:** `timeout_s` istek başına zaman aşımı (verilmezse sağlayıcınınki); `max_retries` verilmezse `defaults.max_retries`.
- **JSON çıktı:** `output.format: json` ise görevde yoksa `json_schema` doğrulayıcısı kendiliğinden eklenir (şema varsa ona göre, yoksa sadece JSON mu diye). `output.schema` sadece `format: json` ile geçerli.
- **`ask` aynı yaşam döngüsünü kullanır:** `orkestra ask` seçeneklerinden `id: ask` bir görev oluşturur; yani `--schema`'ya uymayan cevap artık geri bildirimle tekrar denenir (eskiden hemen `failed`).
- **`command` doğrulayıcısı:** kabuk yok; POSIX'te `shlex.split`, Windows'ta metin olduğu gibi `CreateProcess`'e gider (`list2cmdline` ile uyumlu bölme). `shell: true` açıkça yazılırsa kabuk (AGENTS.md'deki tek istisna). stdin kapalı, çıktı UTF-8 (hatalı bayt `�`). Zaman aşımında ve Ctrl+C'de süreç ağacı `psutil` ile öldürülür. Komut bulunamazsa başarısız sonuç (hata değil). Tam çıktı `attempts/<n>/verify.log`'a, son 2000 karakter `detail`'e.
- **`files_exist`:** glob karakteri (`*?[`) içeren yol için en az bir eşleşme yeterli. Değişiklik doğrulayıcıları (`max_changed_files`, `max_diff_lines`, `protect_paths`, `forbid_paths`) `.gitignore` söz dizimiyle eşler; değişiklik listesi 5b/5c'de dolacak, `ask` görevlerinde boş olduğu için kendiliğinden geçer.
- **Modüller:** Mimari §2'deki `verify/base.py`, `command.py`, `schema.py`, `files.py` yanına `verify/regex.py` eklendi (çıktı deseni ne şema ne dosya).
- **Bağlam:** `context.globs` desteklendi. Glob sonuçları `.gitignore` ve `security.ignore_file` (`.orkestraignore`) ile süzülür, `.git/` hiç alınmaz; açıkça verilen dosyalar sadece `.orkestraignore` ile süzülür (`.gitignore`'daki bir dosyayı kullanıcı bilerek isteyebilir). Atlanan dosya uyarı olarak gösterilir. Şimdilik sadece taban dizindeki ignore dosyaları okunur (alt dizinlerdeki `.gitignore`'lar değil). Mutlak glob kullanım hatası.
- **Görev kimliği:** harf/rakamla başlar, sonra harf, rakam, `.`, `_`, `-` (koşu kayıtlarında ve dosya adlarında güvenli).
- **`kind: edit`:** 5c gelene kadar açık bir kullanım hatası (kod 2); şema bunu zaten kabul ediyor, varsayılan doğrulayıcıları (`forbid_paths`, `max_diff_lines: 2000`) da tanımlı.
Mimari §4.2, §8, §10 ve §11 güncellendi.

## D-039 – Faz 5a kod denetimi düzeltmeleri (2026-11-10)
`/code-review` (PR #6) bulgularına göre (10/10 düzeltildi):
- Envelope'taki `verification[].detail` (komut çıktısı dahil) maskeleniyor; önceden sadece diskteki `envelope.json` maskeliydi, `--json` stdout'u değildi.
- Windows'ta `command` doğrulayıcısı programı kabuk gibi `PATH` + `PATHEXT` ile bulur (`shutil.which`); `npm test` (`npm.cmd`) artık kabuksuz çalışır. Komut satırının geri kalanı değişmeden gider.
- Zaman aşımından sonra öldürülen sürecin çıktısı en fazla 5 sn beklenir; ağacın dışında kalıp boruyu açık tutan bir süreç (ör. arka plana atılmış sunucu) Orkestra'yı kilitlemez.
- Görevdeki `json_schema` doğrulayıcısının kendi şeması yoksa `output.schema`'yı kullanır; başka bir şemayla `json_schema` verilmişse `output.schema` yine ayrıca denetlenir.
- İşçiye denetleneceği şema söylenir: şema `output.schema`'da değil de bir doğrulayıcıda olsa bile. `format: json` ama şema yoksa "tek bir JSON değeri yaz" denir. Şema bir kez yüklenir.
- Envelope `usage` artık koşunun bütün cevaplarının toplamı (geri bildirimli denemeler ve önceki adaylar da ödendi); `runs.worker_output_tokens` da öyle.
- `regex` bütün başarısız desenleri bir arada bildirir (bir geri bildirimle hepsi düzeltilebilsin).
- `files_exist` mutlak yolları ve mutlak glob'ları kabul eder (önceden `NotImplementedError` ile çöküyordu).
- Glob gezintisi `.git/` ve ignore dosyalarının dışladığı dizinlere (`.venv/`, `node_modules/`) hiç girmez; eşleşme glob anlamıyla yapılır (`notes/*` alt dizine inmez). Atlanan dosya 5'ten fazlaysa tek satırlık uyarı.
- Glob karakteri denetimi tek yerde: `glob.has_magic`.
Mimari §10, §11 ve §13 güncellendi.

## D-040 – Worktree ayrıntıları ve `apply` stratejisi (2026-11-10, Faz 5b)
**Bağlam:** Mimari §9 `apply` için `git apply --3way --check` → `git apply --3way` diyordu. Denendi: `--3way`, `--index`'i de açar; kullanıcının o dosyada stage'lenmemiş değişikliği varsa (`git diff` ≠ dizin) `error: <dosya>: does not match index` ile reddeder. Yani tam da kabul kriterindeki "kirli çalışma ağacı" durumunda çalışmıyor, üstelik başarılı olursa kullanıcının dizinini (stage) değiştiriyor.
**Karar:**
1. Önce düz `git apply --check` / `git apply` (sadece çalışma ağacı, dizine dokunmaz). Baseline kullanıcının o anki diski olduğu için koşudan sonra kimse dokunmadıysa bu her zaman geçer.
2. Geçmezse dosya bazında üç yönlü birleştirme: taban = baseline'daki içerik (`git cat-file --filters`, yani checkout'taki satır sonlarıyla), bizimki = kullanıcının şu anki dosyası, onlarınki = işçinin worktree'deki dosyası; `git merge-file -p`. Sadece bir taraf değiştiyse o taraf alınır; iki tarafta da oluşturma, bir tarafta silip diğerinde değiştirme ve ikili dosyalar çakışmadır.
3. Herhangi bir dosya çakışırsa **hiçbir şey yazılmaz** (önce hepsi hesaplanır), `WorkspaceConflict` (kod 5) çakışan dosyaları `details`'te listeler, worktree durur.
4. Uygulama sonrası worktree silinir, `runs.applied = 1`, değişiklik maskelenmiş olarak `runs/<run_id>/changes.patch`'e yazılır (`show --diff` için).
**Diğer ayrıntılar:**
- Kayıt: `runs/<run_id>/worktree.json` (depo, worktree yolu, baseline commit, durum `active|applied|discarded`) ve `runs.workspace`/`runs.worktree` sütunları. Migration gerekmedi.
- Koruma: yıkıcı komutlar (`reset --hard`, `clean -fdx`, `worktree remove`, dizin silme) sadece worktrees dizinindeki, `.git`'i dosya olan ve `git-dir ≠ git-common-dir` olan bağlı bir worktree'de çalışır; değilse `WorkspaceGuardError`. Her git komutu açık `cwd=` ile; hook'lar hiç çalışmaz (`core.hooksPath` boş bir dizin), imzalama kapalı, baseline commit `--no-verify` ve sabit kimlik (`orkestra <orkestra@localhost>`).
- Baseline: `git diff --binary HEAD` (stage'li + stage'siz + silinmiş) worktree'ye uygulanır, `git ls-files --others --exclude-standard` ile izlenmeyen dosyalar kopyalanır (ignore edilenler değil), hepsi tek commit (`--allow-empty`). Commit'i olmayan depo ve git dışı dizin kullanım hatası (kod 2). Alt dizinden çağrılırsa depo kökü kullanılır.
- `diff`: `.orkestra_prompt.md` gibi iç dosyalar hariç, yeniden adlandırma tespiti kapalı; dosya başına eklenen/silinen satır ve durum (`A/M/D`).
- `gc`: worktrees dizinindeki her worktree, koşu kaydı yoksa, kaydı `active` değilse veya koşu `--older-than` günden (varsayılan 30) eskiyse silinir; o yaştaki koşu dizinleri de silinir (`runs` satırları istatistik için kalır); 1 saatten eski rezervasyonlar temizlenir. `--dry-run` sadece listeler.
- `show <run_id>`: `--diff`, `--output`, `--log`'dan en fazla biri; koşu kimliği `YYYYMMDD-HHMMSS-xxxx` biçiminde olmalı (yol enjeksiyonuna karşı).
- `doctor`: Windows'ta `core.longpaths` açık değilse uyarı.
- Modül: `workspace/service.py` (Mimari §2'de sadece `git_worktree.py` vardı); CLI iş mantığı içermesin diye `show`/`apply`/`discard`/`gc` orada.
Mimari §3, §9 güncellendi.

## D-041 – Faz 5b kod denetimi düzeltmeleri (2026-11-10, Faz 5b)
**Bağlam:** PR #7 için `/code-review`: 10 bulgu.
**Karar:**
- Orkestra'nın ürettiği ve uyguladığı patch'ler kullanıcının git ayarlarından etkilenmez: `diff.noprefix`/`mnemonicPrefix`/`relative` ve renk `-c` ile kapalı; `diff` komutlarında `--no-ext-diff --no-textconv --no-color --src-prefix=a/ --dst-prefix=b/`; her `git apply`'da `--whitespace=nowarn` (`apply.whitespace=error` işçinin değişikliğini reddetmesin).
- `changes.patch` sadece başarılı `apply`'dan sonra yazılır. `show --diff` koşu açıkken (kayıt `active`, worktree var) her zaman canlı diff'i gösterir, sonra kaydedilmiş patch'i.
- Patch'ler (`show --diff` canlı diff ve `changes.patch`) aynı maskeyle: yapılandırılmış anahtarlar ve anahtar desenleri maskeli, `password = …` satırları kod olduğu için maskelenmez (işçi cevabındaki `passwords=False` ile aynı).
- `gc`: koşu kaydı olmayan worktree, koşu kimliğindeki zaman 1 günden eskiyse silinir (hâlâ başlamakta olan koşuyla yarışmasın). Bir worktree silinemezse `gc` durmaz; diğerleri, eski koşu dizinleri ve rezervasyonlar işlenir, silinemeyenler `failed` olarak raporlanır (çıkış kodu 0).
- Worktree silme (`remove_path`) depoyu bilmeden çalışır: ortak git dizini worktree'nin kendisinden okunur (`git --git-dir=<ortak> worktree remove --force`, sonra `prune`); depo taşınmış/silinmişse, dizin yarım kalmışsa (`.git` yok) veya alt modül/çıplak depo worktree'siyse de silinir. Koruma: worktrees dizininin dışındaki hiçbir şey silinmez (`WorkspaceGuardError`); `reset --hard`/`clean` için eski koruma (bağlı worktree şartı) aynen duruyor. `main_repo_of` (ortak dizinin üstünü depo sayan tahmin) kaldırıldı.
- `apply`'ın `merged` listesi sadece kullanıcının koşudan sonra da değiştirdiği dosyalar (iki yolda da: düz `git apply` ve üç yönlü birleştirme).
- `show` eski sürüm veya bozuk bir envelope'u JSON olarak gösterir (önceden dahili hata).
- git zaman aşımı mesajı çevrili (`workspace.error.git_timeout`).
Mimari §9 güncellendi.

## D-042 – API işçisiyle düzenleme ayrıntıları (2026-11-10, Faz 5c)
**Bağlam:** Mimari §8.2 biçimi ve kuralları verdi; uygularken netleşmesi gereken noktalar çıktı.
**Karar:**
1. **Bozuk cevap = başarısız kontrol.** Biçim veya yol sorunu (`EditFormatError`, `ProviderBadOutput` alt sınıfı) envelope'ta `edit_format` adlı başarısız doğrulama olur ve aynı modele geri bildirimle döner; diğer başarısız kontroller gibi `max_retries`'tan sayılır, sonra üst kademe. (`ProviderBadOutput`'un yönlendirmedeki "sıradaki aday" kuralı burada uygulanmaz; Mimari zaten "geri bildirimle yeniden dene" diyordu.)
2. **JSON ayrıştırma:** ilk `{`'den başlayarak her konumda `json.JSONDecoder.raw_decode`; `files` anahtarı olan ilk nesne alınır (metin içindeki süslü parantezler ve içerikteki `}` sorun olmaz). Hiç nesne yoksa "JSON yok", varsa ilk ayrıştırma hatası geri bildirilir. Aynı yol iki kez → hata.
3. **Yol kuralları (her zaman, `verify_defaults: false` olsa da):** boş, NUL, mutlak, sürücülü (`C:x` dahil), UNC, `..` ve herhangi bir `.git` parçası reddedilir; `\` → `/`, `./` atılır; `resolve()` sonrası çalışma dizininin dışına çıkan (sembolik bağ) reddedilir; `forbid_paths` desenleri **yazmadan önce** denetlenir (ignore edilen `.env` gibi dosyalar git diff'inde görünmediği için sonradan yakalanamaz). Bağlamda verilmemiş **var olan** bir dosya asla değiştirilmez (işçi içeriğini görmedi). Yeni dosya `allow_new_files` (yeni alan, varsayılan `true`) ile.
4. **Silme yok:** tam dosya biçiminde dosya silinemez (v1); gerekirse kod ajanı (Faz 6).
5. **Her cevap baseline'dan başlar:** yazmadan önce `reset` (önceki denemenin izi kalmaz). Doğrulayıcılar çalıştıktan sonra yine `reset` + cevabın dosyaları yeniden yazılır: komutların bıraktığı `__pycache__`, derleme çıktısı gibi dosyalar değişikliğe ve `apply`'a girmez.
6. **Kesilme:** `finish_reason == "length"` → cevap kullanılmaz, geri bildirim de denenmez (`retry.Action.TOP_TIER`); sadece kademe 3 adaylar kalır. Failover hatası `OutputTruncated`. Kademe 3 de yoksa/olmazsa `status=escalate`, kod 1.
7. **Router:** `kind: edit` ve bağlam dosyalarının en uzunu `security.max_api_edit_lines`'tan uzunsa chat sağlayıcıları `edit_too_large` koduyla elenir (sağlayıcı düzeyinde, diğer nedenlerden sonra). Kod ajanları Faz 6'ya kadar zaten aday değil.
8. **`workspace` edit için zorunlu değil:** yoksa çalışılan dizin; o dizin git deposu değilse koşu başlamadan kullanım hatası (kod 2). Worktree depo kökünden açılır, `workspace` alt dizinse doğrulayıcılar worktree'deki karşılığında çalışır ve değişiklik yolları ona göre verilir.
9. **`changes.patch`** koşu sonunda yazılır (Mimari §8, envelope `changes.patch_path`) ve `apply` uygulanan hali yeniden yazar; açık koşuda `show --diff` canlı diff'i gösterir (D-041).
10. **Özet:** "N dosya değişti (+a/-b): dosya1, …" (en fazla 5 ad) + " — " + işçinin `note`'unun ilk 200 karakteri. İnsan özetinde `show --diff` / `apply` ipucu satırı.
11. İstek `json_mode` ile gider (edit cevabı her zaman JSON). İstem: `prompts/edit_format.md` (değiştirilebilir dosyalar, yeni dosya izni, korunan + yasak desenler).
**Bilinen sınır:** ignore edilen dosyalar (`node_modules/`, `.venv/`) worktree'ye taşınmaz; onlara ihtiyaç duyan `command` doğrulayıcıları başarısız olur (Python'da etkin yorumlayıcı çalışır).
Mimari §4.2, §7, §8, §8.2 güncellendi.

## D-043 – Faz 5c kod denetimi düzeltmeleri (2026-11-10, Faz 5c)
**Bağlam:** PR #8 için `/code-review`: 10 bulgu.
**Karar:**
- **Sadece okunur bağlam dosyaları:** UTF-8 olmayan dosyalar (işçi onları yerine geçme karakterleriyle gördü; tam dosyayı geri yazmak diğer satırları bozardı), git'in ignore ettiği dosyalar (değişiklik hiç uygulanamaz) ve `protect_paths`/`forbid_paths` desenlerine uyanlar düzenlenebilir listesine girmez; ilk ikisi için uyarı. `max_api_edit_lines` sadece düzenlenebilir dosyalara bakar (büyük bir referans/test dosyası adayları elemez).
- **Yol denetimi genişledi:** korunan yollar (`edit.error.protected`) ve git'in ignore ettiği yeni yollar (`edit.error.ignored`, `git check-ignore`) yazmadan önce reddedilir. Yazılamayan yol (`a.py/b.py`, Windows'ta geçersiz ad) koşuyu çökertmez, `edit_format` geri bildirimi olur.
- **JSON modunda CANNOT_DO:** edit istekleri JSON modunda gittiği için işçiye `{"cannot_do": "<neden>"}` biçimi söylenir; runner bunu düz `CANNOT_DO:` gibi değerlendirir (hemen üst kademe).
- **Doğrulanmamış değişiklik:** `status` `ok` değilse `apply` `--force` ister (kod 2); insan özetinde `apply` ipucu sadece `ok`'ta.
- **Değişikliksiz biten edit koşusu** (`escalate`, `error`, boş değişiklik) worktree'sini siler, kaydı `discarded` olur. Kesinti (Ctrl+C) ve kontrolleri geçmeyen değişiklikli koşu worktree'yi korur.
- Kesilme mesajı "kademe 3'e geçiliyor" demez (kademe 3 olmayabilir).
- Commit'i olmayan depo, koşu başlamadan kullanım hatası (`gw.check_repo` `_prepare`'da).
Mimari §8.2 güncellendi.

## D-044 – Kod ajanları: bayraklar, sürümler ve çalışma biçimi (2026-11-10, Faz 6)
**Bağlam:** Plan, Mimari §5.4/§5.5'teki bayrakların kurulu sürümün `--help` çıktısıyla doğrulanmasını istiyordu.
**Test edilen sürümler:** codex-cli 0.160.0, agy 1.5.3 (Windows 11).
**Codex (`codex exec --help`):** `--cd`, `-s/--sandbox read-only|workspace-write|danger-full-access`, `--json` (JSONL olaylar), `-o/--output-last-message`, `--output-schema`, `--skip-git-repo-check`, `-m/--model`, `--color never`; istem argümanı yoksa veya `-` ise stdin'den okunur. Kullanım: `codex exec --cd <workdir> --sandbox <...> --json --color never --output-last-message <attempt>/agent_output.md --skip-git-repo-check [--model m] [--output-schema s] [extra_args] -` + istem stdin'den. `--full-auto`, `--dangerously-*`, `--approve-for-me` kullanılmaz. Kimlik: `codex login status` doctor'da.
**agy (`agy --help`):** `--print/-p`, `--output-format text|json|stream-json`, `--sandbox`, `--mode accept-edits|auto|plan`, `--print-timeout`, `--add-dir`, `--model`, `--disable-slash-commands`, `--dangerously-skip-permissions`. İstem stdin'den sadece `--input-format stream-json` ile (biçimi belgesiz) alınabiliyor; bu yüzden Mimari'nin dosya yolu kullanıldı, ama dosya **worktree'ye değil koşu kayıtlarının yanına** (`attempts/<n>/agent_prompt.md`) yazılır, `--add-dir` ile erişim verilir ve kısa bir `--print "<dosyayı oku>"` argümanı gider (ask görevlerinde kullanıcının dizinine dosya düşmez). Düzenleme: `--mode accept-edits`, ask: `--mode plan`; her zaman `--sandbox`; `--dangerously-skip-permissions` asla. JSON çıktının şekli canlı denenmedi: `result/response/text/output/message/content` anahtarları aranır, JSON değilse düz metin alınır.
**Karar:**
1. `providers/cli_agent.py`: tek modül (Mimari §2'deki `codex.py`/`agy.py` ayrı dosyalar yerine sınıflar: `CliAgent` (generic), `CodexAgent`, `AgyAgent`). `generic` türü: istem stdin, son mesaj stdout (sahte ajan bununla çalışır).
2. Süreç: `asyncio.create_subprocess_exec`, tam yol `shutil.which` ile, çıktılar `attempts/<n>/agent.stdout|stderr` dosyalarına; zaman aşımı, Ctrl+C veya iptalde `psutil` ile süreç ağacına terminate → 5 sn → kill. Ortam: `ORKESTRA_*` silinir, `NO_COLOR=1`, `CI=1`.
3. Çıkış kodu ≠ 0 → `ProviderBadOutput` (stderr'in son 500 karakteri, maskelenmiş), boş son mesaj → `ProviderBadOutput` → sıradaki aday. Ajanlarda taşıma yeniden denemesi yok.
4. Router: ajanlar aday. Kurulu değilse `agent_missing`, agy `experimental: true` olmadan `agent_experimental` (deneysel kuralı gereği `enabled: true` de açıkça yazılmalı), edit + `sandbox: read-only` → `agent_read_only`. Bağlam penceresi ve `max_api_edit_lines` ajanlara uygulanmaz; gizlilik/gizli bilgi kuralları uygulanır (ajanlar `local: false`). Fiyat yok, bütçe `daily_runs`/`daily_requests` ile.
5. Runner: ajan her denemede worktree'yi baseline'a geri sarar, worktree'de (edit, `workspace-write`) veya taban dizinde (ask, `read-only`) çalışır. Değişiklik = baseline'a göre diff (ajanın commit'leri dahil); doğrulayıcılardan sonra geri sar + değişikliği yeniden uygula (`gw.restore`), artıklar girmez. Zaman aşımı varsayılanı `max(defaults.timeout_s, 1800)`.
6. **Dışarı yazma tespiti:** ajan koşusundan önce ve sonra kullanıcının deposunun `git status` + değişen dosya hash'leri (`gw.status_snapshot`); fark varsa `workspace_scope` kontrolü başarısız, kullanıcıya uyarı. Orkestra hiçbir şeyi geri almaz (kullanıcının dosyalarına dokunmamak için). Asıl koruma ajanın kendi sandbox'ı; bu bir ikinci savunma.
7. İstem (`prompts/agent_task.md` + `build_agent_prompt`): görev, değiştirilecek/okunacak dosya adları (içerik değil, ajan kendisi okur), commit yapma, dizin dışına yazma, korunan desenler, `CANNOT_DO`.
8. `doctor`: Codex için `codex login status`; agy için `~/.gemini/antigravity-cli/settings.json` `permissions.deny` içinde `rm`/`sudo` yoksa uyarı. `providers enable agy` aynı uyarıyı onay metnine ekler.
9. Testler gerçek ajan başlatmaz: `conftest` `cli_agent._which`'i sadece sahte ajana izin verecek şekilde değiştirir (`-m live` hariç). Faz 6 sırasında bu koruma yokken eski testlerdeki `codex` sağlayıcısı gerçek Codex'i birkaç kez çalıştırdı (geçici dizinlerde, salt okunur `ask`); koruma bunu kalıcı olarak kapattı.
Mimari §2, §5.3, §5.4, §5.5, §7 güncellendi.

## D-045 – Faz 6 kod denetimi düzeltmeleri (2026-11-10, Faz 6)
**Bağlam:** PR #9 için `/code-review`: 10 bulgu.
**Karar:**
- **Reddedilen cevap korunur:** edit görevinde bir cevap reddedildiğinde değişikliği (`rejected_patch`) saklanır; sonraki aday (ör. çöken bir ajan) worktree'yi değiştirmiş olsa bile koşu `failed`/`escalate` ile biterken worktree o cevaba geri getirilir, envelope ve `show --diff` raporlanan cevabı anlatır.
- **Dışarı yazma denetimi her durumda:** ajan hata verse, zaman aşımına uğrasa veya `CANNOT_DO` dese de deponun önce/sonra karşılaştırması yapılır ve gerekirse uyarı verilir.
- **Ajanın geri bildirim denemesi kendi değişikliğinden devam eder:** worktree sadece adayın ilk denemesinde baseline'a sarılır; sonraki denemelerde önceki değişiklik (doğrulayıcı artıkları atılmış hali) yerinde kalır ve isteme "önceki değişikliklerin çalışma ağacında, baştan başlama, düzelt" eklenir.
- **`--output-schema` kullanılmaz:** codex şemayı katı modda uygular (her alan `required`, `additionalProperties: false`), sıradan bir görev şeması reddedilir. Şema istemde zaten var, `json_schema` doğrulayıcısı sonradan denetler. `AgentRequest.output_schema` kaldırıldı (D-044'teki `[--output-schema]` geçersiz).
- **agy deny-list denetimi:** komut bir girdide ayrı kelime olarak geçmeli (`npm run format` `rm` sayılmaz); `permissions: null` gibi bozuk ayar çökertmez. Ayar dosyası `doctor` ve `consent.describe`'da enjekte edilebilir; `doctor`'ın `codex login status` sondası da (`login=`), testler gerçek Codex'i çağırmaz.
- **`status_snapshot`** dosya içeriğini değil `stat`'ı (boyut + mtime_ns) karşılaştırır: büyük izlenmeyen dosyalarda bile ucuz.
- Kullanılmayan `CliAgent.health()` ve tekrar eden `probe_version` kaldırıldı (sürüm `doctor.probe_version`'dan).
- **Bilinen sınır:** `generic` türdeki ajanın (codex/agy dışındaki her program) sandbox'ı yoktur; `ask` görevinde kullanıcının proje dizininde çalışır. Onay metni bunu söyler (`consent.describe.generic_no_sandbox`), yazdıkları `workspace_scope` ile raporlanır. Bilerek bırakıldı: genel bir programa sandbox dayatmanın taşınabilir yolu yok.
Mimari §5.3, §5.4 güncellendi.

## D-046 – Skill dosyası bugünkü CLI'ye göre (2026-11-10, Faz 9a)
**Bağlam:** Mimari "Ek: Skill dosyası" tam ürünü (Faz 7, 8, 10 komutlarıyla) anlatıyor; Faz 9 MVP sırasıyla Faz 7/8/10'dan önce yapılıyor. Plan, olmayan komutların geçici olarak çıkarılmasını istiyor.
**Karar:**
1. **Çıkarılanlar (o fazlar bitince geri eklenecek):** `status`, `map` (oturum başı) ve `review` + `show --only-flagged` (denetim) → Faz 8; `templates list`, `run --template/--files`, `plan expand` → Faz 8; `batch` → Faz 7; "Devir dosyasını güncel tut" bölümü (`handoff …`) → Faz 10. Bölümler yeniden numaralandı (Raporlama §7).
2. **Gerçek CLI'ye göre düzeltmeler:** `ask` için her dosyaya ayrı `--context` (Ek'teki `--context <dosyalar>` yanlıştı); oturum başı `doctor --json` + `providers list --json`; örnek görev dosyasında `workspace: .` yerine göreli yolların neye göre çözüldüğü yazıldı (D-038), `allow_new_files: false` eklendi; birden çok görev şimdilik sırayla `run` ile.
3. **Önceki fazların kararlarından eklenenler:** çıkış kodları tablosu ve `--json` hata belgesi (`{"error": {...}}`), `--dry-run`, görev alanları ve 8 doğrulayıcı, edit görevlerine kendiliğinden eklenen doğrulayıcılar (§10), worktree notları (en az bir commit, ignore edilen klasörler yok, D-040/D-043), `apply` sadece `ok` ve `--force` kullanıcı istemeden yok (D-043), `--allow-secrets` kullanıcı istemeden yok, başarısız koşunun worktree'si için `discard`, `show --log`, `gc`.
4. **Dil:** Ek'teki gibi Türkçe (Faz 14'te İngilizceye çevrilecek); ön bilgi (`description`) İngilizce.
5. **Test** (`tests/unit/test_skill.py`): skill'deki her `orkestra …` çağrısı (kod blokları ve satır içi kod) gerçek typer uygulamasına karşı denetlenir: komut, alt komut ve bayraklar var olmalı. Örnek görev dosyaları `parse_task` ile geçerli olmalı; dosya ≤ 500 satır. Böylece bir komut yeniden adlandırılırsa veya skill'e henüz olmayan bir komut yazılırsa test kırılır.
Mimari "Ek: Skill dosyası" hedef (tam) sürüm olarak kaldı; başına bu karara işaret eden not eklendi ve `--context` kullanımı düzeltildi.

## D-047 – Faz 9a kod denetimi düzeltmeleri (2026-11-10, Faz 9b)
**Bağlam:** PR #10 için `/code-review`: 10 bulgu (5'i skill metninde, 5'i skill testinde). Hepsi düzeltildi.
**Karar:**
- **Çakışmada değişikliğin tamamı elle uygulanır:** `apply` çakışmada hiçbir dosya yazmaz ve hata sadece çakışan dosyaları listeler. Skill önceden "çakışan dosyaları düzenle, sonra `discard`" diyordu, bu da çakışmayan dosyalardaki doğrulanmış değişiklikleri kaybettiriyordu. Artık diff'teki her dosya uygulanır, sonra `discard` çalıştırılır.
- **Hata biçimleri:** `--json` hatası her zaman `{"error": …}` değildir. Koşu başladıktan sonra bütün adaylar başarısız olursa sonuç zarfı gelir (`status: error`, nedenler `failovers` içinde, kod 3). Ayrıştırıcı hatasında (bilinmeyen bayrak, aralık dışı değer) stdout boştur, mesaj stderr'e yazılır (kod 2). Skill ikisini de anlatıyor.
- **Onay durumları:** skill `consent: changed` (onaydan sonra ayar değişti) ve `enabled: false` durumlarını da anlatıyor. `providers enable` etkileşimli terminal ister (yoksa kod 2, `consent.not_interactive`). Claude bu komutu kendisi çalıştırmaz, kullanıcıdan kendi terminalinde çalıştırmasını ister.
- **Görev alanları:** `id` harf veya rakamla başlar (hata mesajı da bunu söylüyor, en/tr). `verify_defaults`, `tags`, `depends_on` (şimdilik kullanılmıyor) alanları eklendi. 2000 satırı aşan meşru değişiklik için önce görev bölünür; bölünemiyorsa `verify_defaults: false` ve kendi `forbid_paths`.
- **Skill testi** (`tests/unit/test_skill.py`): komut satırı kelimeleri `shlex` ile ayrılır. Global seçeneklerin değer alıp almadığı click parametresinden okunur (`--lang=en` de olur). `--help` ve `--version` kabul edilir, kısa seçenekler de denetlenir. Kod bloklarındaki çağrılarda argüman sayısı denetlenir. Satır içi `orkestra …` ve önekleri olmadan geçen komut ve bayraklar (`apply --force`, `providers enable`, `--dry-run`, `--local-only`) da denetlenir; önekleri olmadan geçen bayrak en az bir komutta bulunmalıdır.
Mimari "Ek: Skill dosyası" (onay ve çakışma maddeleri) güncellendi.

## D-048 – İlk elle deneme (hesap makinesi) düzeltmeleri (2026-11-10, Faz 9b)
**Bağlam:** Claude Code (şef) + Ollama + agy ile gerçek bir React hesap makinesi projesi. Oturum yanlış klasörde açıldığı için skill yüklenmedi; bu yüzden bu deneme skill testi sayılmaz, ama Orkestra'da hatalar çıkardı.
**Karar:**
- **`gc`, deposu silinmiş worktree'yi hemen temizler.** Etkin bir kayıt, deposu olmasa da 30 gün tutuluyordu; böyle bir koşu hiçbir zaman `apply` edilemez.
- **Son worktree'si giden deponun klasörü silinir** (`worktrees/<depo-özeti>/`). Önceden sadece `gc` siliyordu; `apply` ve `discard` boş klasör bırakıyordu. Temizlik `remove_path`'e taşındı.
- **Satır sonları:** `core.autocrlf=true` ile checkout biçimi CRLF, araçların yazdığı dosya LF olabilir. `apply` bunu "kullanıcı dosyayı sonradan değiştirdi" sanıp yanlış "birleştirildi" mesajı veriyordu. Kullanıcı gerçekten LF ile düzenlediyse de `merge-file` her satırı farklı görüp yersiz çakışma veriyordu (test yakaladı). Artık sadece satır sonu farkı değişiklik sayılmaz. Satır sonları karışıksa üç taraf LF ile birleştirilir, sonuç kullanıcının dosyasının satır sonuyla yazılır.
- **agy istemine komut yasağı:** print modu kabuk komutlarını reddediyor ve agy boş cevapla çıkıyordu. İstem dosyasının başına "kabuk komutu çalıştırma, sadece dosya oku/düzenle, denetimi Orkestra yapar" kuralı eklenir. Codex'e eklenmez, çünkü Codex `workspace-write` sandbox'ında komut çalıştırabiliyor.
- **Bilinen sorun:** agy, istekten önce ayarlarındaki bütün MCP sunucularının bağlanmasını bekliyor. Bağlanamayan bir sunucu (ör. Unity editörü kapalıyken unity) her koşuyu ~90 sn bekletip boşa bitiriyor. `agy mcp list`'teki "disabled" durumu print modunda dikkate alınmıyor. Orkestra bunu engelleyemiyor. İleride `doctor` agy'nin MCP ayarlarında sunucu görünce uyarabilir. Şimdilik README/skill notu yok, PROGRESS'te bilinen sorun.
- **Görülen davranış (değişiklik yok):** görev dosyasındaki `model:` config'te olmayan bir Ollama modelini (`qwen2.5-coder:14b`) adlandırabiliyor. Router bunu kabul ediyor, bağlam penceresi varsayılandan (8192) geliyor.
Mimari §5.5 (agy), §9 (`uygula`, `gc`) güncellendi.

## D-049 – Skill ile elle senaryolar; çıktı kodlaması (2026-11-10, Faz 9b)
**Bağlam:** Skill genel olarak (`~/.claude/skills/orkestra`) kuruldu. Temiz bir Claude Code oturumu, yeni bir deneme klasöründe 4 istemle 5 senaryonun hepsini çalıştırdı. İşçiler Ollama (qwen2.5-coder 1.5b/14b) ve agy idi.
**Karar:**
- **Yönlendirilmiş çıktı UTF-8:** Windows'ta boruya ya da dosyaya giden çıktı ANSI kod sayfasıyla (cp1254) yazılıyordu. Okuyan taraf (Claude Code, Git Bash, editör) ise UTF-8 bekliyor, bu yüzden Türkçe harfler bozuk geliyordu (`ko�usu`). Şef çıktıyı `iconv -f cp1254` ya da `--lang en` + `PYTHONIOENCODING` ile çevirmek zorunda kaldı. Artık TTY olmayan stdout/stderr `utf-8` (`errors="replace"`) ile yazıyor. Konsol kendi kod sayfasında kalıyor, yazamadığı karakter `?` oluyor (eski davranış, D-016 dönemi).
- **Skill:** Windows'ta `node --test <klasör>` çalışmıyor, test dosyaları tek tek verilmeli. Bu not worktree notlarına eklendi.
- **Bilinen sorunlar (değişiklik yok):**
  - API ile edit tam dosya JSON'u kullanıyor (D-042). Küçük bir model sadece yorum eklerken bile kod satırlarını kaybedebiliyor: qwen2.5-coder:14b iki koşuda bir satırı çoğalttı, sonra bir tanımı sildi. Doğrulayıcılar yakaladı, hiçbir şey uygulanmadı. Daha güvenli bir edit biçimi (ara/değiştir) ileride düşünülebilir.
  - Ignore edilen klasörler (`node_modules/`) worktree'de yok. Şef `node_modules`'ü worktree'ye junction ile bağlayan bir doğrulama betiği yazdı. Bu yol işçiye kullanıcının `node_modules`'üne yazma imkânı verir, bu yüzden skill'de önerilmiyor. İleride config'te "worktree'ye salt okunur bağlanacak klasörler" düşünülebilir.
  - Dışarıdan öldürülen bir koşu (ör. MCP'de takılan agy) `runs` tablosunda `running` olarak kalıyor. Bütçe rezervasyonunu `gc` temizliyor, koşunun durumunu temizlemiyor.
Mimari §Teknoloji (Kodlama satırı) güncellendi.

## D-050 – Faz 9b değişikliklerinin kod denetimi (2026-11-10, Faz 9b)
**Bağlam:** PR #10 için ikinci `/code-review`, bu sefer D-048 ve D-049 değişikliklerini kapsadı: 10 bulgu. 9'u düzeltildi, 1'inin bir kısmı gerekçesiyle bırakıldı.
**Karar:**
- **`gc` bir gün bekler:** deposu bulunamayan worktree D-048'de hemen siliniyordu. Ama "bulunamayan" sadece takılı olmayan bir sürücü de olabilir ve uygulanmamış değişiklik yalnızca worktree'de duruyor. Artık kayıtsız worktree'deki gibi 1 gün bekleniyor.
- **Satır sonu karşılaştırması git'e bırakıldı:** iki sürüm, git o yol için aynı blob'u saklayacaksa aynı sayılıyor (`git hash-object --stdin --path=<yol>`: `core.autocrlf` ve `.gitattributes` uygulanır). Böylece `-text` ya da `eol=crlf` dosyada kullanıcının satır sonu değişikliği artık sessizce geri alınmıyor. Git yalnızca baytlar farklıysa çağrılıyor, dosya kopyaları da azaldı.
- **Karışık satır sonları:** "içinde CRLF var mı" yerine üç biçim ayırt ediliyor: hep CRLF, hep LF, karışık. Üç taraf aynı ve karışık değilse ham birleştirme yapılıyor. Değilse LF ile birleştiriliyor, sonuç sadece kullanıcının dosyası baştan sona CRLF ise CRLF yazılıyor. Böylece yersiz çakışma ve bütün dosyanın CRLF'e dönmesi engelleniyor.
- **Boş klasör:** `remove_path` worktree zaten yoksa da depo klasörünü temizliyor. `create` başarısız olunca boş klasör bırakmıyor. **Bırakılan kısım:** bir koşu boş klasörü silerken başka bir koşunun aynı klasöre worktree eklemesiyle oluşan yarış zararsız, çünkü `git worktree add` eksik üst klasörleri kendisi oluşturuyor (denendi).
- **agy kuralı kipe göre ve istem dosyasından:** kural artık `prompts/agy_edit.md` ve `prompts/agy_read.md`'den okunuyor ve istemin sonuna ekleniyor. Salt okunur (`ask`, `--mode plan`) koşuda "dosya düzenle" denmiyor, önceki çelişki kalktı.
- **Skill:** şefe "agy istemine komut yasağı yaz" demiyor. Sağlayıcıyı router seçiyor, görev Codex'e de gidebilir ve Codex komut çalıştırabilir. Kuralı adaptör kendisi ekliyor.
- **Akışlar:** UTF-8 akışlar da `errors="replace"` alıyor, böylece `surrogateescape` ile okunmuş git yolları çökertmiyor. Açıkça verilmiş `PYTHONIOENCODING` yönlendirilmiş çıktıda korunuyor.
- **Skill testi:** çağrılar artık kabuk sözcükleriyle ayrılıyor. Tırnak içindeki `|`, `;` ve `&` çağrıyı bitirmiyor. Düzyazıdaki kısa seçenekler (`-f`) denetleniyor. Birden çok değer alan seçeneklerin bütün değerleri atlanıyor.
Mimari §5.5 (agy), §9 (`uygula`, `gc`), §Teknoloji (Kodlama) güncellendi.

## D-051 – Ucuz modeller için ara/değiştir düzenlemesi (2026-11-10, Faz 9c)
**Bağlam:** Faz 9b'nin elle denemesinde `qwen2.5-coder:14b`, sadece JSDoc eklerken tam dosya biçiminde (D-042) iki koşuda da kodu bozdu: bir satırı çoğalttı, bir tanımı sildi. Doğrulayıcılar yakaladı ama iş şefe kaldı. Kullanıcı kararıyla plana yeni bir faz (9c) eklendi, Faz 10'dan önce.
**Karar:**
- **Yeni biçim `replace`:** işçi düz metin SEARCH/REPLACE blokları gönderir. Dosyanın geri kalanı hiç yeniden yazılmaz. JSON modu bu biçimde kapalı, kodu JSON kaçışıyla yazmak gerekmiyor.
- **Varsayılan `auto` (ölçümden sonra, kullanıcı kararı):** önce `replace` varsayılan olacaktı. Elle ölçüm (`qwen2.5-coder:14b`, deneme projesinin bir kopyası, AST doğrulayıcısıyla JSDoc): 4 dosyalı görevde `replace` 0/2 (model yine bir satırı çoğalttı, sonra vazgeçti; 9b'de `whole` da 0/2). Tek dosyalı görevde `whole` 2/2, `replace` 1/2. Model blokların içine fonksiyonun ya da dosyanın neredeyse tamamını kopyaladı, cevap tam dosyadan uzun çıktı (6,8 KB / 3,3 KB). Küçük dosyalarda `replace`'in daha iyi olduğuna dair kanıt yok. Kanıtlanmış faydası büyük dosyalarda: değişmeyen satırlar garanti korunuyor ve ucuz model bu dosyaları da düzenleyebiliyor. Bu yüzden `auto`: en büyük düzenlenebilir dosya `max_api_edit_lines`'a (400) kadarsa `whole`, daha büyükse `replace`.
- **Geri bildirim:** düzenleme görevlerinde yeniden deneme mesajı artık "önceki değişikliğin atıldı, dosyalar bağlamda gösterildiği gibi" diyor (`prompts/retry_edit.md`). Ölçümde model "duplicated export" hatasını orijinal dosyanın kusuru sanıp vazgeçmişti. `replace` istemine de "bir satırın üstüne ekleme" kuralı eklendi.
- **Eşleşme katı:** SEARCH tam satırlar olarak tam bir kez eşleşmeli. Satır sonu farkı her zaman, satır sonundaki boşluk ise ikinci denemede yok sayılır. Daha bulanık eşleşme yanlış yere uygulama riski taşıdığı için yok (kullanıcı onayı). Eşleşmeyen blokta dosyanın en yakın satırları işçiye geri bildirim olarak gider.
- **Güvenlik zinciri aynı:** önce yollar dosya okunmadan denetlenir, sonra bloklar bellekte tam dosyaya çevrilir ve mevcut `check_paths`/`write` kuralları (satır sonu, BOM, korunan/yasak/ignore edilen yollar) aynen uygulanır. Bir blok bile tutmazsa hiçbir şey yazılmaz.
- **Seçim:** görev dosyasında `edit_format` (`auto` | `replace` | `whole`), yoksa config'te modelin `edit_format` ayarı, yoksa `auto`. Biçimi router seçer ve adaya yazar. Runner, kuru çalıştırma ve envelope aynı değeri kullanır. `whole` kalır, ara/değiştirde zorlanan modeller ya da küçük yeni dosyalar için seçilebilir.
- **Router:** `max_api_edit_lines` (400) artık sadece açıkça seçilmiş `whole` biçimini sınırlıyor (`auto` büyük dosyada `replace` seçer) ve eleme model düzeyinde (`edit_too_large`, etiket `sağlayıcı/model`). `replace` biçiminde sadece bağlam penceresi sınırlar.
- **Envelope sürüm 3:** `edit_format` alanı eklendi. Saklanmış sürüm 2 zarflar okunmaya devam ediyor (`Literal[2, 3]`).
- **Skill:** `edit_format` alanı, ne zaman `whole` seçileceği, "mantığı değiştirme" işlerinde mantığı denetleyen doğrulayıcı. Skill testi, skill'deki alan listesinin `TaskSpec` alanlarıyla birebir aynı olmasını denetliyor.
Mimari §8.2, router (edit kuralı), `ModelSpec`, envelope örneği güncellendi.

## D-052 – Faz 9c kod denetimi düzeltmeleri (2026-11-10, Faz 9c)
**Bağlam:** PR #11 için `/code-review`: 10 bulgu, hepsi düzeltildi.
**Karar:**
- **Kod ajanına çelişkili talimat:** "değişikliğin atıldı, baştan başla" notu ajanların yeniden denemesine de gidiyordu. Oysa ajanın değişikliği yerinde duruyor ve ona "baştan başlama" deniyor. Not artık sadece API işçilerine gidiyor.
- **İçerikte `=======` satırı:** setext başlık alt çizgisi ya da çakışma işareti örneği bloğu bozuyordu. Artık bloktaki bütün `=======` satırları olası bölme noktası sayılıyor. Dosyada tam bir kez eşleşenler arasından SEARCH'ü en uzun olan seçiliyor, çünkü işçinin dosyadan kopyaladığı kısım odur. Bloklar dışındaki `=======` satırı düz yazı sayılıyor.
- **Yol satırları:** `### yol`, `File: yol` ve kalın yazı ya da ters tırnak içindeki yol biçimleri tanınıyor. Boşluk içeren yol ancak düzenlenebilir dosyalardan biriyse yol sayılıyor (`parse_replace(known=…)`). Uzantısı olmayan ve `/` içermeyen satır yol sayılmıyor (`Summary.` gibi düz yazı).
- **JSON `cannot_do` taraması** sadece `whole` cevaplarında yapılıyor. Ara/değiştir cevabı ham kod içerir, oradaki `{"cannot_do": …}` sadece içeriktir.
- **Biçim her zaman tek kaynaktan:** adayda biçim yoksa runner onu aynı kuralla çözüyor. İstem, JSON modu ve ayrıştırıcı hep aynı değeri kullanıyor. Biçimsiz bir API düzenlemesi iç hata. `build_edit_messages` biçimi zorunlu istiyor.
- **Bağlam bir kez işleniyor:** bağlam ve görev metni bir kez oluşturuluyor (`edit_body`), biçime göre sadece kurallar ekleniyor (`edit_rules`). Önceden bağlam her biçim için ayrı ayrı oluşturulup ikisi de bellekte tutuluyordu.
- **Okuma hataları:** okunamayan dosya (`cannot_read`) ve klasör yolu (`not_a_file`) artık çökme değil, geri bildirim.
- **Envelope**, `EditFormat` türünü `config/schema.py`'den alıyor; iki kopya yok.
- **Belgeler:** modül açıklaması ve test yorumu `auto` varsayılanını anlatıyor. PROGRESS/DECISIONS'tan kullanıcının yerel klasör adları ve not dosyası yolu çıkarıldı (AGENTS.md: kişisel yol commit'e girmez). Daha önce `main`'e girmiş iki commit'in geçmişinde bu adlar duruyor; geçmişi yeniden yazmak force-push gerektirdiği için dokunulmadı.
Mimari §8.2 güncellendi.

## D-053 – Batch motoru (2026-11-10, Faz 7a)
**Bağlam:** Faz 7, kota yüzünden 7a (batch motoru) ve 7b (tahmin, toplu apply, stats) olarak ikiye bölündü. Mimari §12 bazı ayrıntıları açık bırakıyordu.
**Karar:**
- **Batch dosyası:** `{tasks: [...], parallel: N}` dışında anahtar kabul edilmiyor. Her görev, tek görev dosyası gibi `parse_task` ile denetleniyor; hata mesajında `dosya tasks[i]` geçiyor. Tekrarlanan id, bilinmeyen ya da döngüsel `depends_on` → kod 2. Döngü hatası sadece döngüdeki görevleri listeliyor.
- **Sıra:** önce bağımlılıklar (topolojik), eşitlikte dosya sırası. Kesişen düzenleme görevleri bu sıraya göre sırayla çalışıyor ("after", bekleme ama `skipped` yok). Böylece dosya sırası bağımlılıkla çelişse bile döngü oluşmuyor.
- **Kesişim:** `context.files` ve `context.globs`'un `workspace`'e göre çözülmüş mutlak yollarıyla bulunuyor. Farklı `workspace`'teki aynı adlı dosyalar kesişmiyor. Uyarı, ikisini birden uygulamanın çakışabileceğini söylüyor, çünkü iki görev de kullanıcının dosyalarından başlıyor.
- **Bağımlılığın anlamı:** sadece sıra ve "başarısızsa atla". Bağımlı görev, bağımlı olduğu görevin uygulanmamış değişikliğini görmüyor. Değişikliğe ihtiyaç varsa önce `apply`, sonra ayrı bir batch. Bu README'de ve (7b'de) skill'de yazıyor.
- **Eşzamanlılık:** `--parallel` (varsayılan: dosyadaki `parallel`, o da yoksa 4) aynı anda çalışan görev sayısı. Ayrıca her sağlayıcı için `concurrency` boyutunda bir semafor (`runner.ProviderSlots`) bütün görevlerce paylaşılıyor, chat istekleri ve ajan koşuları ondan geçiyor. Tek koşu (`run`/`ask`) kendi semaforunu alıyor.
- **Hatalar:** bir görevin `OrkestraError`'ı (sağlayıcı yok, onay, bozuk bağlam) ya da beklenmeyen istisnası o görevin `error` maddesi oluyor, batch devam ediyor. `KeyboardInterrupt`/iptal yayılıyor. `--fail-fast`: ilk `ok` olmayan sonuçtan sonra başlamamış görevler `skipped`, çalışanlar bitiyor.
- **Çıktı:** `BatchEnvelope` (`batch_version: 1`): sonuçlar dosya sırasında, her biri görevin zarfıyla. İnsan modunda her görev bitince stderr'e bir satır, sonda stdout'a liste ve toplam. Çıkış kodu: hepsi `ok` ise 0, değilse 1 (2: batch dosyası hatası).
- **`runs.batch_id`** sütunu (ilk şemadan beri vardı) artık yazılıyor, yeni migration gerekmedi. Batch kimliği `b-` + koşu kimliği biçiminde.
Mimari §12, §13 güncellendi.

## D-054 – Faz 7a kod denetimi düzeltmeleri (2026-11-10, Faz 7a)
**Bağlam:** PR #13 için `/code-review`: 10 bulgu, hepsi düzeltildi.
**Karar:**
- **Önce yer, sonra bütçe:** istek önce sağlayıcının semaforunda yer bekliyor, sonra bütçeyi rezerve ediyor. Önceden bütün görevler bekleme sırasında rezervasyon tutuyordu ve sırayla çalışınca bütçeye sığacak görevler `BudgetExhausted` alıyordu. Yeniden deneme beklemesinde yer bırakılıyor, böylece diğer görevler beklemiyor.
- **Router bütçesi:** router'ın bütçe elemesi rezervasyonları saymıyor (`budget.used(reservations=False)`), sadece gerçekleşmiş kullanıma bakıyor. Bir rezervasyon, süren bir isteğe ait (batch'te aynı sağlayıcıyı bekleyen bir göreve) ve bu görev isteğini göndermeden önce kapanıyor. Rezervasyonları, istek gönderilirken yapılan `reserve` sayıyor; birden çok süreç birlikte yine bütçeyi aşamıyor. Tek bir koşu için davranış değişmedi.
- **Devre kesici yerde yeniden bakılıyor:** yer bulunca sağlayıcının sağlığı tekrar okunuyor. Başka bir görevin hataları devreyi açtıysa istek gönderilmiyor, koşu hemen sonraki adaya geçiyor (`failovers` içinde `CircuitOpen`). Önceden kuyruktaki her görev kendi zaman aşımını bekliyordu.
- **Fiyat listeleri tek kilitle:** batch'teki görevler fiyat listelerini sırayla çekiyor (`ProviderSlots.prices`). İlk görev çekip önbelleğe yazıyor, diğerleri taze önbelleği kullanıyor. Aynı liste 20 kez çekilmiyor, görevler birbirinin önbelleğini ezmiyor.
- **Glob'lar `run` ile aynı:** kesişim hesabı `context.glob_files` kullanıyor (`collect_context` ile aynı kurallar). `src/**.py` gibi bir desen batch'i çökertmiyor, mutlak desen kod 2 veriyor, `.gitignore`/ignore dosyası kapsamındaki dosyalar kesişim sayılmıyor.
- **Uyarılar:** görevlerin koşu sırasında ürettiği uyarılar (gizli bilgi, fiyatsız bütçe…) insan modunda da stderr'e yazılıyor.
- **Çöken koşunun `run_id`'si:** koşu kaydedildiği anda batch'e bildiriliyor (`run_task(on_start=…)`), sonradan çökse bile `error` maddesinde `run_id` var, `show`/`discard` kullanılabiliyor.
- **Koşu kimliği çakışması:** `new_run_id`, süreç içinde verdiği kimlikleri ve diskte var olan koşu klasörlerini atlıyor. Batch aynı saniyede birkaç koşu başlattığı için gerekli oldu.
- **Temizlik:** topolojik sıra bir kez hesaplanıyor (`BatchSpec.order`), `spec.read_document` tek okuyucu, CLI'de `spec` modül adı gölgelenmiyor.
Mimari §12 güncellendi.

## D-055 – agy'nin MCP sunucusu beklemesi (2026-11-11, Faz 6 düzeltmesi)
**Bağlam:** D-048'deki bilinen sorun: agy, istekten önce bütün MCP sunucularının bağlanmasını bekliyor. Unity editörü kapalıyken Unity'nin relay'i hiç bağlanmıyor ve her agy koşusu boşa bitiyor. Antigravity'nin bıraktığı not (`AGY_TO_CLAUDE.md`, repoya girmedi) üç çözüm önerdi; agy 1.5.5 ile denendi.
**Ölçülenler (agy 1.5.5, Unity kapalı, "Reply with exactly: OK"):**
- Değişiklik yokken koşu `--print-timeout`'a (150 sn) kadar bekledi, 0 token. 1.5.3'teki ~90 sn sınırı yok artık.
- agy CLI MCP ayarını `~/.gemini/config/mcp_config.json`'dan okuyor (`antigravity/mcp_config.json` ona sembolik bağ; `antigravity-cli/` ve `antigravity-ide/` dosyaları CLI'yi etkilemiyor). Oradaki `"disabled": true` print modunda yok sayılıyor.
- `--settings` (oturuma özel ayar) MCP'yi kapatamıyor: `mcpEnabled`, `allowedMcpServers`, `mcpServers` ve benzeri ~20 anahtar "unknown setting".
- `ANTIGRAVITY_CONFIG_REL_DIR` etkisiz. `ANTIGRAVITY_GEMINI_DIR` (notun önerdiği klasör izolasyonu) girişi düşürüyor ("You are not logged into Antigravity"); `settings.json`'daki izin listesini de devre dışı bırakırdı.
- Unity çalışmıyorsa hemen çıkan bir sarmalayıcı (`cmd.exe /d /c <betik>.cmd --mcp`, `tasklist` ile denetim) ile koşu 9 sn'de `SUCCESS`.
- `MCP_TOOL_TIMEOUT` (720000) araç çağrısı süresi; bağlantı beklemesiyle ilgisi yok, değiştirilmedi.
**Karar:**
- **Asıl çözüm kullanıcının makinesinde:** bağlanamayan sunucu, uygulaması kapalıyken hemen çıkan bir sarmalayıcıyla başlatılır. Kişisel yol içerdiği için repoya girmez; README'de genel bir örnek var.
- **Orkestra güvenlik ağı:** `AgyAgent` agy'nin günlüğünü `attempts/<n>/agent.log`'a yazdırır (`--log-file`). `run_process` isteğe bağlı bir gözcü alır (`CliAgent.watcher`, saniyede bir). agy'nin gözcüsü günlükte "MCP: … still connecting after 30s: …" satırını görünce süreç ağacı durdurulur ve sunucu adlarıyla `ProviderUnavailable` verilir: router sağlayıcıyı atlar, bütçe 0 ile kapanır, sağlık kaydına düşer (art arda olursa devre açılır). İlk raporda (30 sn) durmak seçilmişti; kod denetiminde yavaş başlayan sunucular yüzünden `mcp_wait_s` (varsayılan 60) ile değişti (D-056).
- **`doctor`:** `~/.gemini/config/mcp_config.json`'da `disabled: true` olan sunucular için uyarı (`provider:agy:mcp`). Dosya yok/bozuksa sessiz.
- **Yapılmayanlar:** uygulama klasörü izolasyonu (giriş ve izinler bozuluyor), MCP için config alanı (agy'de kapatma yolu yok).
Mimari §5.5 güncellendi.

## D-056 – agy MCP düzeltmesinin kod denetimi (2026-11-11, Faz 6 düzeltmesi)
**Bağlam:** PR #14 için `/code-review`: 10 bulgu. 9'u düzeltildi, 1'i kısmen (aşağıda).
**Karar:**
- **Bekleme süresi ayarlanabilir:** `cli_agent` için `mcp_wait_s` (varsayılan 60, `0` = hiç durdurma, ≥ 0). Koşu, agy'nin raporladığı bekleme süresi bu değere ulaşınca duruyor; agy 30 sn'de bir raporladığı için pratikte 60, 90… sn. 30 sn'de durmak `npx`/`uvx` ile ilk açılışta yavaş bağlanan sunucuları da öldürüyor, art arda olunca devreyi açıyordu. Onay özetine (`settings_hash`) girmiyor, çünkü verinin nereye gittiğini değiştirmiyor.
- **Günlük kaldığı yerden okunuyor** (`LogTail`): her saniye bütün dosya değil sadece yeni baytlar okunuyor; yarım yazılmış son satır, satır sonu gelene kadar değerlendirilmiyor (kesik sunucu adı çıkmıyor). Süre Go biçiminden (`30s`, `1m30s`) okunuyor.
- **Hata mesajında ev klasörü yok:** günlük yolu koşu klasörüne göre (`attempts/1/agent.log`); mesaj sağlık tablosuna ve log'a da giriyor.
- **Durdurulan süreç bekleniyor:** zaman aşımı ve gözcü durdurmasında `kill_tree`'den sonra `proc.wait()` (Windows'ta kapanmamış taşıma kalmıyor). Gözcü yoksa ek task oluşturulmuyor.
- **Onay metni:** `providers enable agy` artık `disabled` MCP kayıtları için de uyarıyor (`consent.describe.agy_mcp`), `doctor` ile aynı.
- **Testler ev klasörüne bakmıyor:** conftest `AGY_SETTINGS` ve `AGY_MCP_CONFIG`'i geçici yola çeviriyor; `doctor` bu yolları varsayılan argüman olarak değil çağrı anında okuyor. Önceden geliştiricinin gerçek agy ayarı bir testi kırabiliyordu.
- **Sürüm:** README test edilen agy sürümünü 1.5.5 yapıyor (bütün bayraklar, `--log-file` dahil, canlı koşuyla doğrulandı).
- **Kısmen:** `doctor` hâlâ sadece `disabled` kayıtlar için uyarıyor. Etkin ama bağlanamayacak bir sunucuyu başlatmadan bilmenin yolu yok; uyarı metni, sarmalayıcı seçeneğini de söyleyecek şekilde düzeltildi.
Mimari §4 (`CliAgentProvider`), §5.5 güncellendi.

## D-057 – Maliyet tahmini, toplu apply, stats (2026-11-11, Faz 7b)
**Bağlam:** Faz 7'nin ikinci yarısı. Mimari §12, §19 ve komut tablosu bazı ayrıntıları açık bırakıyordu.
**Karar:**
- **`batch --estimate`:** her görev için router'ın ilk adayı ve bütçe rezervasyonunun tahmini (istem karakteri/3,5 + `max_output_tokens`, modelin çözülen fiyatı). Sadece önbellekteki fiyatlar, hiçbir istek ve fiyat listesi çekimi yok (`--dry-run` gibi). İlk deneme olduğu açıkça yazılıyor. Kod ajanı ve fiyatı bilinmeyen uzak model `cost_usd: null` ve `unpriced`; fiyatsız yerel model 0 (gerçekten ücretsiz). Çalışamayan görev (bilinmeyen `provider`, bozuk bağlam, depo yok) hata ve çıkış koduyla listeleniyor, diğerleri yine tahmin ediliyor; `--estimate`'in çıkış kodu ilk böyle görevinki.
- **Eşik:** `estimate.confirm_above_usd` (varsayılan 0,50, `null` = kapalı) varsa batch çalışmadan önce aynı tahmin yapılıyor, bu kez fiyat listeleri tazeleniyor (koşu da tazeleyecekti). Aşılırsa: `--json` tahmin belgesini stdout'a yazıp kod 2 (şef kullanıcıya gösterir, kabul ederse `--yes-cost`); terminal varsa sorulur, hayır kod 2; terminal yoksa kod 2. Kod 2 seçildi, çünkü durum bir kullanım kararı ve hiçbir şey çalışmadı. Fiyatsız görevler toplama girmediği için eşiği tetiklemiyor; çıktı bunu söylüyor.
- **`apply --batch <id> [--only-ok]`:** batch'in `edit` koşuları `runs.started_at` sırasıyla (bağımlılık ve kesişen dosya sırası kendiliğinden korunur; batch dosyası kaydedilmediği için sıra koşulardan okunuyor). `--only-ok` geçmeyenleri, zaten uygulananları ve değişikliği olmayanları atlar. `--only-ok`/`--force` olmadan geçmeyen koşusu olan batch hiç uygulanmıyor: kısmi uygulama bilinçli seçim olsun. İlk çakışmada duruyor (kod 5), `applied`/`conflict`/`not_tried` raporlanıyor; çakışma çözülünce aynı komut kaldığı yerden devam ediyor (uygulananlar atlanır). `RUN_ID` artık isteğe bağlı; `RUN_ID` ile `--batch`'ten tam biri, `--only-ok` sadece `--batch` ile (kod 2).
- **`stats [--since 7d]`:** `state/stats.py`, sadece okur. Sağlayıcı ve etiket başına biten koşu, `ok/failed/escalate/error`, başarı oranı, ortalama deneme ve süre, token, maliyet, `estimated`. Token ve maliyet `usage`'ın `actual` satırlarından, isteğin gittiği sağlayıcıya (yedeğe geçişin tokenı harcandığı yerde). Koşu, cevabı veren sağlayıcıya sayılıyor. Zarfında sağlayıcı olmayan koşu (üst kademeye geçen, cevapsız biten) son isteğinin gittiği sağlayıcıya sayılıyor: gerçek veride `escalate` koşuları sağlayıcısızdı ve ollama'nın başarı oranını %80 gösteriyordu, doğrusu %55. Hiç istek göndermeyen koşu "sağlayıcı yok". `running` koşular ayrı sayılıyor, oranlara girmiyor. Çok etiketli koşu her etiketine sayılıyor, etiketsiz koşular "etiket yok". `--since`: `Nd`/`Nh`/`Nm` (N ≥ 1). Şef tasarrufu (Mimari §19 "Tasarruf sayacı") Faz 8a'da.
- **Skill:** `batch` geri eklendi (D-046): batch dosyası örneği (testte `load_batch` ile denetleniyor), bağımlılığın anlamı, `--estimate`, `--yes-cost` sadece kullanıcı kabul ederse, `apply --batch --only-ok`, `stats`.
- **Var olan test:** Faz 7a'nın bütçe rezervasyonu testi fiyatlı config kullanıyor; tahmini eşiği aştığı için `--yes-cost` aldı.
Mimari §3 (komut tablosu), §12, §19 güncellendi.

## D-058 – Faz 7b kod denetimi düzeltmeleri (2026-11-11, Faz 7b)
**Bağlam:** PR #15 için `/code-review`: 10 bulgu. 9'u düzeltildi, 1'i kısmen.
**Karar:**
- **Atılmış başarısız koşu engellemiyor:** `apply --batch` ön denetimi sadece değişikliği duran (etkin worktree kaydı olan) başarısız koşuları sayıyor. `discard` edilmiş, worktree'si hiç olmamış ya da `gc` ile silinmiş koşu batch'i boşuna kilitlemiyor.
- **Hata raporu kaybolmuyor:** çakışma dışındaki her `OrkestraError` (ör. `git worktree remove` hatası) da batch'i durduruyor: `error` alanı (`conflict` ile aynı biçim), kendi çıkış kodu, o ana kadar `applied` ve kalanlar `not_tried`. Önceden hata yayılıyor, uygulananların listesi kayboluyordu.
- **`not_tried` doğru:** sadece gerçekten uygulanacak koşular (zaten uygulanmamış, `--only-ok` ise `ok`, değişikliği duran).
- **Fiyatsız ücretli model onay istiyor:** fiyatı bilinmeyen uzak model `totals.unpriced_remote` sayılıyor ve eşik altında da onay gerekiyor (fiyat listesi çekilemediğinde 200 görevlik ücretli batch $0 görünüp sormadan çalışabilirdi). Mesaj ayrı: "fiyatı bilinen kısım … ama N görev fiyatı bilinmeyen modellere gidiyor". Kod ajanları sayılmıyor (kullanıcının kendi kotası). Öğelerde `agent` alanı.
- **Yerel kurulum tahmin yapmıyor:** sadece fiyatsız yerel modeller ve ajanlar varsa ön tahmin hiç yapılmıyor (görevler iki kez hazırlanmıyor). Ücretli sağlayıcı varken tahmin her görevi bir kez daha hazırlıyor: bilinen sorun (kısmen).
- **`--since` taşmıyor:** en fazla 36500 gün; daha büyüğü ve taşan değer kod 2.
- **Zamanlar an olarak:** `stats` ve `apply --batch` sırası saklanan ISO zamanları `datetime` olarak karşılaştırıyor (SQL sadece iki günlük payla daraltıyor). Yaz saati ya da saat dilimi değişince filtre ve sıra kaymıyor.
- **Token ve maliyet penceredeki koşuların:** `usage` satırları `created_at`'e göre değil, penceredeki koşulara göre seçiliyor; toplam, sağlayıcı ve etiket satırları birbirini tutuyor.
- **Temizlik:** hata metni tek yardımcıda (`_detail`), adaysız tahminin ölü dalı `InternalError`, `_total` `sum`, istem tokenı tek hesap.
Mimari §3 (komut tablosu), §12, §19 güncellendi.

## D-059 – Şef araçları: status, şablonlar, cevap önbelleği, tasarruf sayacı (2026-11-11, Faz 8a)
**Bağlam:** Faz 8'in ilk yarısı. Mimari §19 ayrıntıların bir kısmını açık bırakıyordu.
**Karar:**
- **`status`:** `chief/status.py`, bölümler `@section(ad, order)` ile kayıt oluyor; sonraki fazlar bu modüle dokunmadan satır ekleyecek. Bölüm başına sınır (3 koşu, 4 sağlayıcı satırı, kalanı "+N") ve merkezde 15 satır: aşarsa son satır `status --json`'u gösteriyor. JSON her şeyi taşıyor. Şef `ORKESTRA_CHIEF` ortam değişkeninden, yoksa `defaults.chief`; devir ve kuyruk satırları Faz 10/12'de.
- **Şablonlar:** biçim `description` / `params` / `task`. Ayrı bir `params` şeması yerine görev alanlarında `string.Template.safe_substitute` (Jinja yok, Mimari). İsteğe bağlı `check` parametresi boş kalınca o `command` doğrulayıcısı düşüyor: yerleşik şablonlar dil bağımsız kalıyor, kullanıcı kendi test komutunu veriyor. Yerleşik açıklamalar dil başına (`{en, tr}`), çünkü kullanıcıya görünüyor; parametre açıklamaları ve işçi istemleri İngilizce. Şablon görevleri `batch` ile aynı yardımcıdan (`cli._run_batch`) geçiyor, böylece maliyet eşiği ve `--yes-cost` geçerli; `run` bunun için `--yes-cost` aldı. `--dry-run` görevleri batch dosyası olarak yazıyor (şef çalıştırmadan görebilsin).
- **Cevap önbelleği:** `cache/responses.py`. Anahtara şema ayrıca girmiyor, çünkü system isteminde; bağlam dosyalarının içeriği user isteminde. Sadece görevin kendi istemi önbellekten okunuyor (geri bildirimli tekrar istemleri önceki cevaba bağlı). İsabette cevap yine doğrulanıyor; geçmezse işçiye normal soruluyor. İsabet bütçeye, `daily_runs`'a ve sağlık kaydına dokunmuyor. Kayıtta gizli bilgiler maskeli (koşu kayıtlarıyla aynı), istem yok. Kod ajanları dışarıda: cevapları çalışma dizinine bağlı.
- **Testler:** aynı soruyu bilerek tekrar soran iki eski test modülü (`test_state_cli`, `test_ask_doctor_cli`; yedeğe geçiş, bütçe, sağlık) önbelleği kapatan, nedenini yazan bir modül fikstürü aldı.
- **Tasarruf sayacı:** sütunlar Faz 0'dan beri yazılıyordu; `stats` penceredeki biten koşuların toplamını ve zarfın tahmini tokenını gösteriyor, hep "tahmini" etiketiyle.
- **Skill:** `status`, şablonlar, önbellek geri eklendi (D-046). `map`, `review`, `plan expand` 8b'de.
Mimari §19 güncellendi.

## D-060 – Faz 8a kod denetimi düzeltmeleri (2026-11-11, Faz 8a)
**Bağlam:** PR #16 için `/code-review`: 10 bulgu. 9'u düzeltildi, 1'i kısmen.
**Karar:**
- **Ajan cevabı önbelleğe sızmıyor:** önbellek anahtarı her adayda sıfırlanıyor ve kod ajanının cevabı hiç yazılmıyor. Önceden sohbet modeli başarısız olup görev bir ajana geçince ajanın cevabı sohbet modelinin anahtarıyla saklanıyor, sonraki koşuda onunmuş gibi dönüyordu.
- **Bayat cevap siliniyor:** önbellekten gelip doğrulamayı geçmeyen cevap siliniyor ve işçinin deneme hakkından (`max_retries`) sayılmıyor; işçiye geri bildirimle soruluyor. Anahtara görevin doğrulayıcıları da giriyor: aynı soruyu farklı denetleyen görevler aynı kaydı paylaşmıyor.
- **Saat dilimsiz kayıt** isabet sayılmıyor (önceden `TypeError` ile koşu çöküyordu).
- **`--files` sadece gerçek dosyalar:** `context.existing_files` var olmayan yolu, klasörü, ignore dosyalarının dışarıda bıraktığı dosyayı ve çalışma dizini dışını eliyor; eşleşen yoksa kod 2.
- **`params` denetimi:** sözlük değilse anlaşılır hata (kod 2); `ad: değer` kısa yazımı varsayılan sayılıyor (önceden sessizce zorunlu oluyordu).
- **Yerleşiği ezen proje şablonu duyuruluyor:** her `run --template` ve `templates show`'da stderr'e uyarı, JSON'da `overrides_builtin` ve `path`. Engellenmiyor, çünkü proje şablonu bilinçli bir özellik ve bir görev dosyası da aynı komutları çalıştırabilir; ama klonlanan depo sessizce kendi komutlarını çalıştıramıyor. Skill şefe önce `templates show` demesini söylüyor.
- **Tasarruf:** sadece `ok` koşular; oran 1'in altındaysa "tasarruf yok" satırı (önceden "0.3 kat az" yazıyordu).
- **Çeviri:** şablon hata metinleri ve `templates show` başlığı `t()` ile.
- **CLI:** `run --template --dry-run --json` JSON veriyor; `--yes-cost` görev dosyasıyla kod 2.
- **`status` (kısmen):** sağlayıcı özeti bir kez okunuyor (iki bölüm paylaşıyor), uygulanmamış koşu sorgusu worktree'si olmayanları SQL'de eliyor. `discard` edilen koşular hâlâ kayıt dosyası okunarak eleniyor; bunun için `runs`'a yeni bir durum sütunu (yeni migration) gerekir, şimdilik bilinen sorun.
Mimari §19 güncellendi.

## D-061 – Şef araçları: review, map, plan expand (2026-11-11, Faz 8b)
**Bağlam:** Faz 8b (Mimari §19, YAPILIS_PLANI.md 8b). Şef araçlarının ikinci yarısı: otomatik ön inceleme (`review`), repo haritası (`map`), taslak planı genişletme (`plan expand`).
**Karar:**
- **`review <run_id>`:** Pydantic `ReviewReport` (`risk`: low/medium/high/unknown, `flags`: file, start_line, end_line, reason, severity, `summary`, `model`). Şema dışı çıktıda model geri bildirimle 1 kez tekrar denenir; yine geçersizse `risk: unknown` ve boş flags döner (Mimari §19). 400 satırdan büyük diff'ler dosya dosya parçalanıp incelenir ve birleştirilir (`unknown` > `high` > `medium` > `low`). Sonuç `runs/<run_id>/review.json`'a yazılır, envelope'a `review: {risk, flags_count}` eklenir (`envelope_version` 3'ten 4'e çıkarıldı). `show --diff --only-flagged`: sadece işaretli satır aralıkları ±5 satır bağlamla filtrelenir; işaretli yer yoksa uygun bilgi mesajı verilir. `review.auto: true` ise başarılı `edit` koşusunda otomatik inceleme çalışır.
- **`map [yollar]`:** `chief/repomap.py`. (a) Modelsiz yapı bilgisi: Python'da `ast` ile fonksiyonlar, asenkron fonksiyonlar, sınıflar ve metot imzaları; diğer dillerde regex sezgiselleri. (b) 1-2 cümlelik amaç özeti: yerel modelle çıkarılır ve SHA256 içerik hash'iyle `.orkestra/cache/map/<hash>.json`'da saklanır. Değişmeyen dosyalar önbellekten okunur; değişen tek dosya yeniden özetlenir; silinen dosyalar haritadan düşer.
- **`map` gizlilik kuralı:** `map.privacy` varsayılan `local_only`. Yerel sağlayıcı yoksa uzak sağlayıcıya hiçbir dosya içeriği gönderilmez; model özetleri atlanır, sadece yapı bilgisi üretilir ve kullanıcıya uyarı bildirilir.
- **`map` dosya toplama performansı:** `collect_repo_files` içinde `Path.rglob("*")` yerine `os.walk` kullanılarak `.git`, `.venv`, `node_modules`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.orkestra` dizinleri tarama ağacında budanır; böylece büyük depolarda gereksiz dosya taraması ve asılmalar önlenir.
- **Önbellek temizliği:** `cache clear` komutu hem yanıt önbelleğini hem de repo haritası önbelleğini (`.orkestra/cache/map/`) temizler.
- **`plan expand <taslak> -o batch.yaml`:** `chief/plan.py`. Şef taslağı (+ varsa `.orkestra/MAP.md`) kademe-2 modele gönderilir; çıktı TaskSpec şemasına uygun batch YAML olarak pydantic ile doğrulanır. Geçersiz YAML'da en fazla 2 tekrar (toplam 3 deneme), yine olmazsa `PlanFormatError` (kod 2). Doğrulayıcısız `edit` görevlerine uyarı verilir. Çıktı dosyaya yazılır ancak **kesinlikle çalıştırılmaz**.
- **Skill:** `skill/orkestra/SKILL.md` güncellendi (`map --json`, `review <run_id> --json`, `show --diff --only-flagged`, `plan expand`).
Mimari §19 güncellendi.

## D-062 – Faz 8b kod denetimi düzeltmeleri (2026-11-11, Faz 8b)
**Bağlam:** PR #17 için `/code-review`: 10 bulgu; Claude'un kendi okumasından 7 not daha (geniş `except`, ilerleme göstergesi, `--max-files`, kısmi harita, `review.auto` yuvaları, zayıf test, gizli bilgili dosya). 9 bulgu düzeltildi, 1'i yanlış alarm çıktı (aşağıda); 7 notun hepsi düzeltildi.
**Karar:**
- **Diff ayrıştırma (`chief/patchparse.py`, yeni):** dosya bloğu `diff --git` satırında (düz diff'te `--- ` + `+++ ` çiftinde) başlıyor; hunk gövdesi `@@ -a,b +c,d @@` sayılarıyla okunuyor. Önceden her `--- ` satırı yeni blok açıyordu: 400 satırı aşan tek dosyalık diff "sadece başlık" + "başlıksız gövde" diye ikiye bölünüp iki kez inceleniyordu, silinen `-- yorum` satırı hunk'ı ortadan kesiyordu. Yol `+++ b/…` satırından (silinen dosyada `--- a/…`, ikili dosyada `diff --git`): sondaki sekme ve git'in tırnaklı/sekizli kaçışlı adları (`"b/\303\247ay.txt"`) çözülüyor. Büyük diff sadece birden çok dosya varsa dosya dosya inceleniyor.
- **`show --only-flagged`:** işaretli dosyanın başlığı ve sadece içinde işaretli satır olan hunk'lar (önceden her `@@` başlığı gövdesiz basılıyordu); boşluklu ve Türkçe karakterli yollar eşleşiyor; modelin yazdığı `a/`/`b/` öneki tolere ediliyor. `review.json` okunamazsa çevrilmiş hata (kod 2).
- **Şef çağrısı (`chief/call.py`):** bütün adaylar başarısız olunca son sağlayıcı (ya da bütçe) hatası yükseltiliyor; hiç aday denenemediyse router'ın hatası. Önceden `last_error` hiç atanmadığı için her hata "sağlayıcı yok"a dönüyordu. Başarıda `health.record_success` (önceden çağrılmıyordu; aralara başarılar girse bile dağınık 3 geçici hata devre kesiciyi 5 dk açıyor, normal görevleri de durduruyordu). `prompt_has_secrets` ortak yardımcı.
- **Yanlış alarm – "çöken kod ajanı başarılı sayılıyor":** `CliAgent.run` sıfır olmayan çıkışta ve boş cevapta zaten `ProviderBadOutput` fırlatıyor; kod değişmedi, yorumla belirtildi. Sohbet modelinin boş cevabı için ayrı önlem: `map` boş özeti önbelleğe yazmıyor, uyarı veriyor, bir sonraki koşuda yeniden soruyor.
- **`map` (`chief/repomap.py`):**
  - Hata ayrımı: sağlayıcı hatası sadece o dosyanın özetini atlıyor (`map.warning.summary_failed`); router/bütçe/onay hatası özetleri durduruyor ve gerçek nedeni yazıyor (`map.warning.summaries_stopped`). "Yerel sağlayıcı yok" uyarısı sadece gerçekten yokken.
  - Gizli bilgi: `map.privacy: normal` iken anahtar içeren dosya uzağa gitmiyor ve **sadece o dosya** atlanıyor (`map.warning.secret_skipped`); önceden ilk böyle dosya bütün özetleri kapatıyordu.
  - Yollar çalışma dizinine göre (önceden git köküne göre çözülüyordu); proje dışı ya da olmayan yol kod 2 (önceden yakalanmamış `ValueError` ile çöküyordu). Kök `resolve()` ediliyor (Windows sürücü harfi, `subst`). `map` ve `cache clear` aynı kökü kullanıyor (`project_root`); önceden alt klasörden `cache clear` harita önbelleğini silmiyordu.
  - `map <yollar>` haritanın geri kalanını koruyor: son haritanın kayıtları `.orkestra/cache/map/index.json`'da; verilen yolların dışında kalıp hâlâ var olan dosyalar MAP.md'de kalıyor (son haritadaki halleriyle). `--json`'da `files` bu koşunun dosyaları, `map_files` MAP.md'deki toplam. Önceden MAP.md sadece verilen yollarla üzerine yazılıyordu. `cache clear` indeksi de siliyor.
  - `--max-files` sınırına takılınca uyarı ve `--json`'da `truncated: true`; dosyalar sıralı yürünüyor (kararlı sonuç).
  - İlerleme göstergesi (Mimari §19): özet istenen her dosya için `[n/toplam] özetleniyor: yol`, sadece stderr terminalse ve `--json` yokken.
  - Verim: ikili dosya denetimi ilk 8 KB'ı okuyor (önceden her dosya iki kez tamamen okunuyordu); bir koşu tek veritabanı bağlantısı ve tek `ProviderSlots` kullanıyor.
- **`review` (`chief/review.py`):** sağlayıcı/router hatası `risk: unknown` diye gizlenmiyor, yükseltiliyor (`orkestra review` kendi çıkış koduyla, ör. 3); `review.json` yazılmıyor. Diff gönderilmeden önce yapılandırılmış anahtarlarla maskeleniyor (kayıtlı patch zaten maskeli, yine de). Zarf `ResultEnvelope` ile doğrulanıp güncelleniyor; bozuk zarf çevrilmiş hata (önceden `except Exception: pass`). Görev istemi `read_yaml` ile.
- **`review.auto`:** koşunun `ProviderSlots`'u ve bağlantısıyla çalışıyor (sağlayıcı eşzamanlılık sınırı aşılmıyor; işçinin yuvası incelemeden önce bırakıldığı için kilitlenme yok); `duration_s` incelemeyi de sayıyor. İnceleme başarısızsa (`OrkestraError`) koşu `ok` kalıyor, zarfta `review` yok, günlükte uyarı. İncelemenin bütçe kaydı aynı `run_id` ile; zarfın `usage` alanı sadece işçinin kullanımı (bilinen sorun).
- **`plan expand`:** sadece geçersiz cevap (`PlanFormatError`) tekrar deneniyor; router, bütçe ve sağlayıcı hataları ilk seferde kendi çıkış koduyla (önceden 3 kez denenip "YAML geçersiz", kod 2 diyordu). `parse_task`/`from_tasks` hataları `UsageError` olarak yakalanıyor.
- **Hata gizleme ve çeviri:** yeni koddaki geniş `except Exception`'lar dar türlere indirildi (`review.py`'deki `except Exception: pass` dahil); `"Review failed: …"` ve `"Could not read review…"` metinleri `t()` ile (en, tr). `EnvelopeReview.risk` artık `Literal`.
- **Testler:** `plan expand` uyarı testi tam metni ve yazılan dosyanın `batch` ile yüklendiğini denetliyor (önceden `"verify" in err or …`). 30 yeni test (birim + uçtan uca).
- **Skill:** `review`'un danışman olduğu ve hata verirse diff'in tamamının okunacağı; `map <yol>` ve `warnings`/`truncated`.
Mimari §19 güncellendi.

## D-063 – Faz 10a: şef devri dosyası, özet ve durum satırı (2026-11-12, Faz 10a)
**Bağlam:** Mimari §17 (tek doğruluk kaynağı) ve `DEEPSEEK_DEVIR_TESLIM.md` §2-§5. 10a: devir dosyası ayrıştırma/yazma, kilitli güncelleme, arşiv, redaksiyon, kural tabanlı özet, migration, `status` satırı, kılavuz, i18n, skill.
**Karar:**
- **Dosya biçimi:** İlk satır `<!-- orkestra-handoff v1 -->`, `# Devir: <proje>`, sabit İngilizce başlıklar (`Goal`, `Status`, `Done`, `In progress`, `Decisions`, `Open questions`, `Watch out`, `Last updated`). İçerik her dilde. Ayrıştırıcı `## ` başlıklarını kod bloklarının dışında arar; bilinmeyen bölümler, sıraları ve boş satırlar korunur (elle düzenlenen dosya bozulmaz). İşaretçi yoksa ayrıştırılır ve `missing_marker` uyarısı döner; dosya sessizce "düzeltilmez". Aynı başlık iki kez varsa ilki kullanılır, ikincisi silinmez (`duplicate_section`).
- **Satır sonu:** Dosyanın kendi satır sonu (CRLF/LF) parse edilir ve yazarken korunur. `Last updated` zamanı, dosyada dakika hassasiyeti varsa dakika olarak yazılır (elle yazılmış biçim bozulmasın).
- **`store.py`:** Yazma atomik (aynı klasörde geçici dosya + `os.replace`). Kilit yeni bağımlılık olmadan `os.open(O_CREAT|O_EXCL|O_WRONLY)` ile `HANDOFF.md.lock`; `POLL_S` aralıklarla tekrar, zaman aşımında `HandoffLocked` (yeni hata sınıfı; çıkış kodu **5**, dosya çakışması). 30 sn'den eski kilit bayat sayılır ve silinir. Okuma→değiştirme→yazma kilidin içinde. Saat/uyku enjekte edilebilir.
- **Arşiv:** `Done`/`Decisions` `handoff.max_lines`'ı aşınca en eski maddeler `.orkestra/HANDOFF.archive.md`'ye **eklenir** (üzerine yazılmaz, silinmez); her taşımada bölüm başlığı (`## Done (archived)`) yazılır.
- **Redaksiyon:** `update` metni ve arşive giden satırlar `Redactor(configured_secrets(config))` ile maskelenir.
- **Özet (`brief.py`):** LLM çağrısı yok. Sıra: Goal, Status, Open questions, Watch out → son 5 Done, son 5 Decisions → git (branch, `git status --short` ≤15 satır, son 5 commit) → uygulanmamış `edit` koşuları → kalan günlük bütçe → eskime uyarısı → sabit kılavuz (`prompts/chief_guide.md`, `importlib.resources`). Hiçbir koşulda `brief_max_lines` aşılmaz: sığmayan satırlar atılır, son satır `… (+N)` olur. Uzun satırlar 120 karakterde sarılır (sınır okurun gördüğü satırı saysın). Git yoksa tek satır not, çökme yok. Özet de redaksiyondan geçer.
- **In progress özetten çıkarıldı (Mimari §17'den sapma):** 10a testi (`test_a_non_git_directory_gets_a_note_and_does_not_crash`) git yokken özette `branch:` geçmemesini bekliyor; fixture'ın `In progress` metni `branch: faz-10a` içeriyor. Mimari §17 In progress'i özet listesine koyuyor. Testler esas alındı; In progress devir dosyasında duruyor, özette yok. Kullanıcı onayı alındı (2026-11-12).
- **`status` satırı:** `@section("handoff", order=20)`; dosya yoksa bölüm hiç üretilmez. Varsa Goal'ün ilk satırı (70 karaktere kısaltılmış) ve gerekirse eskime uyarısı; 15 satır sınırı korunur, `--json` tam veri verir (`goal`, `path`, `stale`, `commit`, `commits_after`).
- **`status --json` tek satır:** 15 satır sözünün `--json` çıktısında da geçerli olması için `status --json` kompakt JSON basar (diğer komutların `--json` biçimi değişmedi). İnsan çıktısı aynı.
- **Migration 0002:** `handoffs (id, from_chief, to_chief, at, commit, brief_path)` + `handoffs_at` indeksi. Tablo 10a'da gelir; satırı 10b yazar. Mevcut `0001` değiştirilmedi.
- **Bayraklar:** Mimari §17'de olanlarla sınırlı: `--section`, `--add`, `--set`, `--chief`, `--strict`, `--warn-only`, `--brief`, `--json`. Yeni bayrak icat edilmedi.
- **i18n:** 49 yeni anahtar en + tr; tüm kullanıcı metinleri `t()`; yeni hata sınıfının çıkış kodu `errors.py`'de belgelendi.
- **Testler:** 61 yeni test (birim + uçtan uca), iki ayrı süreçle eşzamanlı güncelleme ve 31 sağlayıcı + devir dosyasıyla `status` sınırı dahil. Mevcut testlerin beklenen değerleri değiştirilmedi; `tests/unit/test_skill.py`'de Faz 10a artık `handoff show`u bildiği için "olmayan komut" örneği `handoff delete` yapıldı ve `--strict` artık gerçek bir bayrak olduğu için "olmayan bayrak" örneği `--strictly` oldu (davranış bilerek değişti, testin amacı korundu).
- **Commit'lenmeyen yerel dosyalar:** `DEEPSEEK_DEVIR_TESLIM.md`, `GLM_DENETIM_*.md`, `GEMINI.md`, `AGY_*.md`, `docs/PROJE_DOKUMANTASYONU.md`, `docs/YAPILANLAR.md`, `.orkestra/`.
Mimari §17 ve §19 güncellendi (D-063).

## D-064 – Faz 10a kod denetimi düzeltmeleri (2026-11-12/13, Faz 10a)
**Başlangıç:** GLM denetimi (`GLM_DENETIM_10a.md`, commit `43f8013` / PR #18): 13 bulgu (B1–B14), genel karar "düzeltme gerekli". Düzeltmeden önce her bulgu için kırmızı test yazıldı (11 kırmızı, 5 yeşil çıktı; PROGRESS'te alıntılar var). Kullanıcı kararları: B3 repo kökü, B12 kompakt kalsın, B13 satır sonu reddi (2026-11-12).
**Karar:**
- **B1 (kritik) – CRLF gerçek yolda korunmuyordu:** `store.update` dosyayı `Path.read_text` ile okuyordu; evrensel satır sonu dönüşümü `\r\n`'yi bellekte `\n` yapıyor, `model.parse`'ın CRLF saptaması hiç çalışmıyordu. Yeni `store.read(path)` = `read_bytes().decode("utf-8")`; `update`, `brief.build`, `show`, `status` aynı yolu kullanıyor. Model düzeyindeki eski test gerçek okuma yolunu geçmediği için yanıltıcıydı; store düzeyinde CRLF gidiş-dönüş testi eklendi.
- **B2 – PR gövdesi:** var olmayan 3 test adı gerçek adlarla değiştirildi (Türkçe/emoji `test_parse_and_render_keep_every_byte_of_a_hand_edited_file`'ın `DOCUMENT` sabitinde).
- **B3 (kullanıcı kararı) – alt klasör:** dosya artık repo kökünden çözülüyor (`store.project_root` = `git rev-parse --show-toplevel`; git yoksa/başarısızsa cwd). `store.handoff_path(config, cwd, git)` tek çözüm noktası; `cli._handoff_target`, `cli init` proje adı ve `status._handoff` bunu kullanıyor. Alt klasörden `init/update/show/check/status` testi eklendi.
- **B4 – repo dışı yanıltıcı mesaj:** `Staleness.no_git` alanı; `staleness` önce `rev-parse --is-inside-work-tree` soruyor. Depo yoksa bilinmeyen-commit değil "git deposu yok" deniyor (`handoff.check.no_git`, `status.handoff.no_git`). Özette ayrıca uyarı basılmıyor: `_git_lines` zaten tek satır `handoff.brief.no_git` notunu veriyor. Depo içinde geçmişte olmayan commit davranışı korunuyor; test repo'lu fixture'a taşındı.
- **B5 – iş mantığı cli'de:** eskime uyarısı kararı tek yerde: `brief.warning_lines(state, keys)`; `handoff check` gövdesi yeni `handoff/check.py` servisine taşındı (`CheckResult`), `cli.py` yalnız çağırıp basıyor. Uyarı anahtarları çağıran katmanda (`BRIEF_WARNING_KEYS`, `CHECK_WARNING_KEYS`, `STATUS_WARNING_KEYS`).
- **B7 – kilit zaman aşımı testi hızlı:** `update` imzasında `lock_timeout_s`/`stale_after_s` artık `None`; varsayılan çağrı anında çözülüyor (monkeypatch edilebilir). CLI'de kilit varken `update` çıkış kodu 5 testi eklendi; süre 10 sn → <1 sn.
- **B6, B8, B11 – davranış doğruydu, test eksikti:** kombine özet stresi (devasa goal + 40 satır git status + 50 uygulanmamış koşu + `brief_max_lines: 10`), CLI `show --json` `marker: false`, bütçe satırında kesin `t(...)` karşılaştırması. Üçü de kod değişmeden yeşile döndü; dürüstçe raporlandı.
- **B9 – şef adı:** `|`, `:`, `\r`, `\n` içeren ya da boş ad `UsageError` (kod 2, `t("handoff.error.bad_chief")`); `update` dosyaya/kilide dokunmadan, `init_file` de reddediyor.
- **B10 – yerel Mimari §17:** numaralı listeden In progress çıkarıldı, D-063 numarasına bağlandı; §17'ye repo kökü, şef doğrulaması, `no_git` ve `handoff/check.py` notları eklendi. (Belge yerel, commit edilmez.)
- **B12 (kullanıcı kararı):** `status --json` kompakt tek satır kalıyor (D-063'teki gerekçe geçerli); değişiklik yapılmadı.
- **B13 (kullanıcı kararı):** çok satırlı `--add` reddediliyor (kod 2, `t("handoff.error.multiline_add")`); arşiv satır sayımı bir maddeyi bölemez.
- **B14:** kırmızı çıktı alıntıları `docs/PROGRESS.md` Faz 10a düzeltme bölümünde.
- **i18n:** 4 yeni anahtar (en + tr): `handoff.check.no_git`, `status.handoff.no_git`, `handoff.error.bad_chief`, `handoff.error.multiline_add`.
- **Testler:** 1049 → **1063** (+14). ruff, ruff format, pyright temiz. Commit `fix(faz-10a): address GLM review findings`; PR #18 gövdesi düzeltildi, birleştirilmedi.
Mimari §17 ve §19 güncellendi (D-064).

## D-065 - Faz 10b: devretme (`handoff to`) ve pre-commit kancası (2026-11-13, Faz 10b)
**Bağlam:** Mimari §17 ("Başlatma" ve hook), `DEEPSEEK_DEVIR_TESLIM.md` §3-§6 ve `docs/YAPILIS_PLANI.md` Faz 10b. 10a devir dosyasını/özeti bitirdi; 10b özeti hedef şefe ulaştırır, `handoffs` satırını yazar ve isteğe bağlı `install-hook` komutunu ekler.
**Karar:**
- **`launch.to` sırası:** hedef adı ve dosya doğrulanır → özet kurulur → `--print-only` ise yalnız özet döner (kayıt yok, süreç yok) → başlatıcı `shutil.which` ile bulunur (yoksa kod 2, hiçbir şey yazılmaz) → kirli ağaç denetimi (kod 5) → mod seçimi → (gerekirse) `.orkestra/BRIEF.md` yazılır → `handoffs` satırı **başlatmadan önce** yazılır → `before_start` geri çağrısı uyarıları basar → çocuk başlar. `execvp` hiç dönmediği için kayıt önce yazılmak zorunda.
- **`from_chief`:** `--chief` yok (10b'de bayrak yok); `ORKESTRA_CHIEF`, yoksa `defaults.chief`. `to_chief` hedef adı. `at` enjekte edilebilir saat, `commit` `HEAD` kısa hash'i (repo yoksa `NULL`), `brief_path` yalnız `file` modunda dolu.
- **Modlar ve geri düşüş:** `chiefs.<ad>.prompt_mode` (`arg`/`stdin`/`file`). `arg` modunda başlatıcı `.cmd`/`.bat` ise (Windows alıntılama tuzağı) veya özet `ARG_MAX_CHARS = 8000` karakteri aşarsa uyarıyla `file` moduna düşülür; `stdin`/`file` modlarında geri düşüş yok. `file` modu özeti repo kökündeki `.orkestra/BRIEF.md`'ye yazar ve çocuğa sabit İngilizce `BRIEF_INSTRUCTION` verir.
- **Gerçek makine doğrulaması (2026-11-13):** `claude` bu makinede `claude.cmd` (npm, 2.1.322) → config `arg` olsa bile fiilen `file`'a düşer; `agy` `agy.exe` (1.5.7, varsayılan `file`); `codex` `codex.exe` (codex-cli 0.160.0, varsayılan `arg`). Varsayılanlar (`claude: arg`, `agy: file`, `codex: arg`) değiştirilmedi; `.cmd` kuralı gereği Claude arg modu fiilen kullanılmaz.
- **Süreç:** `shell=True` yok. Windows'ta `subprocess.run` (stdin modunda `input=`), çıkış kodu `to`'nun çıkış kodudur; Unix'te stdin yoksa `os.execvp` (testte enjekte edilir), stdin varsa `execvp` sonrası beslenemeyeceği için alt süreç kalır. Çıktı yakalanmaz: terminal yeni şefe geçer.
- **Kirli ağaç:** `git status --porcelain`, repo kökünde; `.orkestra/BRIEF.md` (tam eşleşme veya `/<yol>` sonu) sayılmaz. Değişiklik varsa `HandoffNotClean` (yeni sınıf, kod **5**) ve `t("handoff.error.dirty", count=N)`; `--allow-dirty` ile devam. Repo yoksa kirli denetimi yok sayılır (özet "git deposu yok" der).
- **`--print-only`:** başlatıcı aranmaz, kayıt yazılmaz, `BRIEF.md` yazılmaz; `show --brief` ile aynı metni basar (test bunu birebir karşılaştırır).
- **`install-hook`:** `git rev-parse --git-path hooks` (worktree'de doğru yol); repo yoksa kod 2 (`t("handoff.error.no_git")`). Var olan `pre-commit` **ezilmez**: işaretli blok (`# >>> orkestra handoff >>>` / `# <<< orkestra handoff <<<`) sona eklenir, dosyanın satır sonu korunur, UTF-8 dışı baytlar `surrogateescape` ile aynen geri yazılır. Blok varsa hiçbir şey değişmez (idempotent). Blok `command -v orkestra` ile korunur ve `|| true` ile **commit'i asla engellemez**; hook yoksa `#!/bin/sh` ile oluşturulur ve mümkünse çalıştırma biti verilir.
- **Uyarı sırası:** uyarılar ve "devrediliyor" mesajı, terminal çocuğa geçmeden önce `before_start` ile basılır (10b kod denetiminde fark edilen sıra hatası; test `test_before_start_runs_with_the_final_mode_just_before_the_child`).
- **`brief._git_lines` düzeltmesi (10b'de bulundu):** commit'siz (unborn) bir depoda `rev-parse --abbrev-ref HEAD` başarısız olunca özet yanlışlıkla "git deposu yok" diyordu. Artık önce `rev-parse --is-inside-work-tree` sorulur, dal için `branch --show-current` yedeği var; gerçek depo commit'sizken de dal ve `git status` gösterilir (`test_a_repository_without_commits_still_shows_its_branch`).
- **i18n:** 15 yeni anahtar (en + tr): `cli.handoff.to.help`, `cli.handoff.install_hook.help`, `cli.handoff.arg.chief`, `cli.handoff.option.print_only`, `cli.handoff.option.allow_dirty`, `handoff.error.no_git`, `handoff.error.unknown_chief`, `handoff.error.launch_missing`, `handoff.error.dirty`, `handoff.to.starting`, `handoff.to.warning.cmd`, `handoff.to.warning.long`, `handoff.hook.created`, `handoff.hook.updated`, `handoff.hook.exists`.
- **`.gitignore` / `BRIEF.md`:** `init` yalnız `.orkestra/cache/` ekliyor (D-006); `.orkestra/BRIEF.md` üretilen bir dosya olduğu için `.gitignore`'a **dokunulmadı** (kullanıcının `.gitignore`'ında başka bir ajanın `.aider*` satırı var; global giriş eklemek `init` davranışını da değiştirirdi). Kirli ağaç filtresi `BRIEF.md`'yi tam eşleşme veya `/<yol>` sonuyla dışlar; böylece dosya izlenmese de devir engellenmez.
- **Kapsam dışı bırakılanlar:** yeni CLI bayrağı yok (`--chief` 10a'da `update` için var; `to` için yok), `review`/night queue/Faz 11 hazırlığı yok, mevcut migration dosyaları değiştirilmedi (0002 zaten tabloyu kuruyordu).
- **Testler:** 1063 → **1096** (+33: 25 birim + 8 uçtan uca, sahte şef fixture'ı ve unborn dal regresyonu dahil). ruff, ruff format, pyright temiz; gerçek CLI duman testi geçici repoda yapıldı (init, update, check, show --brief, to --print-only, install-hook x2, sahte şefle gerçek süreç başlatma, kirli ağaçta kod 5, `FAKE_CHIEF_EXIT=7` → kod 7).
Mimari §17 güncellendi (D-065).

## D-066 – Faz 10 Claude denetimi düzeltmeleri (2026-11-13, Faz 10a/10b)
**Başlangıç:** Kullanıcı "Faz 10 full test" istedi. Claude ruff/pyright/pytest'i (1096 geçti) ve geçici repoda gerçek CLI + sahte şefle iki duman testini koştu; Mimari §17 ve kabul kriterlerine karşı kod okundu. 10 kod bulgusu ve 1 süreç bulgusu çıktı; kullanıcı "hepsini çözelim" dedi. Önce kırmızı testler yazıldı (47 kırmızı: 36 yeni davranış + spawn imzası değişen 11 eski test; 3 yeni test baştan yeşildi: kapalı kod bloğundaki `## `, bölüm değişince yeni arşiv başlığı, kesme sayısı).
**Karar:**
- **Alt klasörden `handoff to` (`file` modu):** `BRIEF.md` repo köküne yazılıyor ama şef alt klasörde başlıyordu; talimattaki göreli yol bulunamıyordu (sahte şef `FileNotFoundError`). Şef artık **her zaman repo kökünde** başlar (`Spawn(argv, stdin, cwd, env)`; Unix'te `chdir` + `execvpe`).
- **Yeni şefin adı:** çocuk süreç eski şefin `ORKESTRA_CHIEF`'ini miras alıyordu (agy'nin `update`/`status` kayıtları "claude" görünürdü). Çocuğa `ORKESTRA_CHIEF=<hedef şef>` verilir, ortamın geri kalanı korunur.
- **Ctrl+C (Windows ve stdin modu):** `subprocess.run` `KeyboardInterrupt`'ta çocuğu `kill()` ediyordu (CPython kaynağı); yeni şefte Ctrl+C'ye basmak şefi öldürürdü. Çocuk çalışırken Orkestra SIGINT'i yok sayar, sonra (hata olsa da) eski işleyiciyi geri koyar.
- **Kirli ağaç:** olağan akış "`update` → `to`" kod 5'e takılıyordu, çünkü devir dosyasının kendisi kirli sayılıyordu. Devir dosyası, arşivi, kilidi ve `BRIEF.md` (repo köküne göre yolları) **kirli sayılmaz**; `git status --porcelain --untracked-files=all` (yeni `.orkestra/` klasörü tek satır olmasın). Hata mesajı dosyaları sayar (ilk 5, sonra "ve N tane daha"; `handoff.error.dirty` artık `{files}` alır, yeni `handoff.error.dirty_more`). Var olan iki testin beklenen mesajı bu yüzden `files="a.txt"` ile güncellendi.
- **Git kancası hatırlatmayı susturuyordu:** blok `check` çıktısını `>/dev/null 2>&1` ile atıyordu; eskimiş dosyada commit'te hiçbir şey görünmüyordu. Çıktı artık kullanıcıya gider (`orkestra handoff check --warn-only || true`, `HOOK_COMMAND`); gürültü olmasın diye **`--warn-only` uyarı yoksa hiçbir şey basmaz** (çıkış kodu yine her zaman 0). Gerçek `git commit` ile uçtan uca test eklendi.
- **Kanca commit'i engelliyordu:** kabuk bloğu bir Python kancasının sonuna ekleniyordu → `SyntaxError` → commit kod 1 (kabul kriteri "commit'i hiç engellemez" ihlali). Artık yalnız kabuk shebang'li (`sh, bash, dash, zsh, ksh, ash, mksh`, `env` ile de) kancaya eklenir; diğerlerinde (shebang'siz dahil) dosyaya dokunulmaz, kod 2 ve satırı elle eklemesi söylenir (`handoff.error.hook_not_shell`). Blok **shebang'in hemen altına** girer: eski kancanın sonundaki `exit`/`exec` hatırlatmayı atlatamaz (var olan test `startswith(existing)` yerine "blok çıkarılınca eski içerik aynen" diye güncellendi; amaç, eski kancayı ezmemek, korunuyor). CRLF kanca CRLF kalır.
- **`--set` yapıyı bozabiliyordu:** metindeki `## Done` satırı sahte bölüm açıyor, sonraki `--add` yanlış yere gidiyordu; kapanmamış ``` bloğu sonraki bütün başlıkları gizlerdi. `update`, değişiklikten sonra başlık listesini önceki listeyle (eksik bölüm eklendiyse onunla) karşılaştırır; farklıysa dosyaya dokunmadan kod 2 (`handoff.error.breaks_structure`). Kapalı kod bloğundaki `## ` serbest. `--set` metnindeki CRLF/CR, LF'ye çevrilir (CRLF dosyada `\r\r\n` oluşuyordu).
- **In progress özete geri döndü (D-063 geri alındı, kullanıcı kararı 2026-11-13):** sıradaki adım bu bölümde ve 10b elle kabul kriteri "agy özetteki sıradaki adımı anlıyor" diyor. Sıra: Goal, Status, In progress, Open questions, Watch out. D-063'teki çelişkinin nedeni testteki kaba `"branch:" not in text` assert'iydi; testin amacı "git yokken dal satırı basılmasın", assert `t("handoff.brief.branch")` satırına daraltıldı.
- **Özet kesilince önemli satırlar kalır:** eskiden sınır aşılınca sondan kesiliyordu; gerçekçi bir dosyada (~70 satır) 60 satırda önce kılavuz, sonra eskime uyarısı düşüyordu (10 satırlık denemede uyarı görünmedi). Artık: eskime uyarısı her zaman kalır; Orkestra kılavuzu en az `MIN_BODY_LINES = 20` proje satırı yanına sığıyorsa kalır (varsayılan 60'ta kalır); kesilen proje satırlarıdır ve son satır toplam gösterilmeyen satır sayısını verir. Mimari §17'deki sıra aynı, yalnız kesme kuralı değişti.
- **Küçükler:** arşive art arda taşımalar tek `## Done (archived)` başlığı altında (bölüm değişince yeni başlık); arşiv devir dosyasının satır sonunu kullanır; `Last updated` ve şablon zamanı saniye hassasiyetinde (mikrosaniye yok; dakikalı elle yazılmış dosya dakikalı kalır).
- **Skill §7:** Claude'a `handoff to`'yu kendisinin çalıştırmasını söylüyordu; komut aracında terminal yok, etkileşimli ajan takılır/kapanır. Artık: kullanıcıya oturumu kapattıktan sonra kendi terminalinde çalıştırmasını söyle; şef yalnız `--print-only` çalıştırabilir; önce commit (devir dosyası sayılmaz).
- **Süreç:** PROGRESS 10b'yi ✅ işaretlemişti ama 10b kabul kriterindeki elle senaryo (Claude Code → `handoff to agy` → agy devam ediyor) yapılmamıştı ve 10b GLM denetiminden geçmemişti. Tablo "⏳ elle senaryo bekliyor" oldu.
- **CI (Linux/macOS) 10b commit'inden beri kırmızıydı:** uçtan uca `handoff to` testleri Unix'te gerçek `execvp` çağırıp pytest sürecinin yerine sahte şefi koyuyordu (pytest şefin kodu 3 ile çıkıyordu); raporlarda geçmiyordu. Bu testlerde çocuk her zaman alt süreç olarak başlar (`child_as_subprocess` fixture'ı); `execvpe` yolu enjekte edilen birim testinde kalır.
- **i18n:** 3 yeni anahtar (`handoff.error.dirty_more`, `handoff.error.breaks_structure`, `handoff.error.hook_not_shell`), `handoff.error.dirty` ve `cli.handoff.option.warn_only` metni değişti (en + tr).
- **Bilinen, düzeltilmeyen:** bayat kilit temizliğinde iki süreç aynı anda bayat kilidi görürse ikisi de girebilir (yalnız çökmüş bir kilitten sonra, çok dar pencere); Windows'ta kilitsiz bir okuyucu (`show`/`status`) dosyayı açık tutarken `os.replace` `PermissionError` verebilir (çok dar pencere).
Mimari §17 güncellendi (D-066).

## D-067 – Windows'ta devir kilidi yarışı (2026-11-13, Faz 10a)
**Bağlam:** PR #20'nin CI'ında (windows-latest, py3.13) `test_two_processes_adding_twenty_items_each_keep_all_forty` bir kez kırmızı oldu: süreçlerden biri `PermissionError: [Errno 13] Permission denied: '…HANDOFF.md.lock'` ile çöktü. Windows'ta kilidin sahibi kilit dosyasını silerken (silme bekliyor) başka bir sürecin `os.open(O_CREAT|O_EXCL)` çağrısı `FileExistsError` değil `PermissionError` alır; `_acquire` yalnız `FileExistsError` yakaladığı için `handoff update` aynı anda iki şef yazarken rastgele çökebiliyordu. 10a, GLM ve Claude denetimlerinde gözden kaçmıştı (yerelde 1134 test geçiyordu).
**Karar:**
- Windows'ta (`os.name == "nt"`) `PermissionError` "kilit meşgul" sayılır: aynı bekleme/zaman aşımı yolu (`HandoffLocked`, kod 5). Bayat kilit denetimindeki `stat`/`unlink` için de aynı kural.
- Unix'te `PermissionError` gerçek bir hatadır (klasör yazılamıyor); beklemek bunu gizlerdi, olduğu gibi yükselir.
- `_acquire`'a enjekte edilebilir `opener` ve `platform` eklendi; üç birim testi (Windows'ta bekleyip alıyor, hiç bırakılmazsa zaman aşımı, Unix'te gerçek hata). İki süreçli test yerelde 30/30 geçti.
Mimari §17 güncellendi (D-067).

## D-068 – Faz 11a: algılama, kurulum sihirbazı (`--plain`, `--defaults`) ve config yazma (2026-11-14, Faz 11a)
**Bağlam:** Mimari §22, plan Faz 11. Plan fazı iki oturuma bölüyor; kullanıcı Faz 11'i Claude'a verdi. **11a** = `tui/detect.py`, sihirbaz akışı (`init --plain`, `init --defaults`), config yazma servisi; **11b** = Textual arayüzü (`orkestra ui`, sihirbaz ekranları, `textual` bağımlılığı), de/es/fr çevirileri, 5 dilli tamlık testi, `TERM=dumb`. 11a'da `textual` eklenmedi (hazırlık kodu yok).
**Karar:**
- **`config/writer.py` (Mimari "config/loader.py" diyor):** yazma ayrı modülde; `loader`'a yalnız `read_yaml_text` eklendi. ruamel round-trip (`indent(2, 4, 2)` örnek dosyanın biçimi, `width=4096`, tırnaklar korunur, `null` `null` kalır) → **kaydetmeden önce doğrulama** (proje dosyası, üzerine yazdığı base config ile birleştirilerek) → eski dosya `<ad>.bak` (**tek, dönen yedek**; sihirbaz ve 11b arayüzü sık kaydeder; `init --force`'un numaralı yedekleri değişmedi — **D-069 ile geri alındı**: hiçbir yedek ezilmez) → aynı klasörde geçici dosya + `os.replace`. Dosyanın CRLF'si korunur. Geçersiz config hiç yazılmaz, `.bak` ve geçici dosya da kalmaz.
- **ruamel sınırı:** `anahtar:` sonrasındaki hizalama boşlukları korunamıyor (`cheap:     {…}`). Örnek config (ve `examples/` kopyası) hizasız yazıldı ki round-trip bayt bayt aynı olsun; kullanıcı dosyalarında yorumlar ve sıra kalır, yalnız bu hizalama kaybolur.
- **Algılama:** Ollama `GET /api/tags`, 2 sn; ağ/biçim hatası "çalışmıyor" demektir, istisna değil. `codex`, `agy`, `claude`: `shutil.which` + `--version` (doctor'ın `probe_version`'ı). Bilinen 6 OpenAI uyumlu API (`openrouter, openai, deepseek, groq, mistral, gemini`) için anahtar değişkeni yalnız `in` ile denetlenir; **değer hiç okunmaz** (test: değer okunursa patlayan bir ortam nesnesi).
- **Sihirbaz akışı (`tui/wizard.py`, arayüzden bağımsız):** dil (seçilince hemen o dile geçer) → algılama özeti → sağlayıcılar (bulunanlar seçili gelir, en az biri) → Ollama modelleri ve kademeleri / API model kimliği, kademe, günlük USD / ajan günlük koşu → her **açık** sağlayıcı için `consent.describe` + açık onay → varsayılan şef (yalnız bir şef bulunduysa sorulur) → genel/proje → (plain) `doctor` çalıştırılsın mı. Yanlış cevap nedeniyle tekrar sorulur (negatif bütçe, kademe 4, olmayan numara, boş model kimliği). Soru soran taraf enjekte edilir (`Prompter`); 11b'nin ekranları aynı servisi kullanacak.
- **Evet/hayır her dilde:** `typer.confirm` yalnız `y/n` biliyor ve İngilizce "invalid input" diyordu (gerçek denemede Türkçe `e` reddedildi). Sihirbaz kendi sorusunu sorar: `y/yes/e/evet/j/ja/s/sí/o/oui` ve `n/no/h/hayır/nein/non`, ipucu seçili dilde (`[e/H]`).
- **Yeni dosya / var olan dosya:** yeni dosya örnekten başlar; seçilmeyen örnek sağlayıcılar silinir ve örneğin bütçe sınırları (openrouter `daily_tokens`) seçim sayılmaz, bütçe tam sorulan olur. Var olan dosyada hiçbir şey silinmez: seçilmeyen sağlayıcı `enabled: false` olur, sorulmayan bütçe sınırları ve yorumlar kalır.
- **`--defaults`:** soru yok; çalışan Ollama'nın bütün modelleri kademe 1, bulunan `codex` açık, bulunan `agy` deneysel olduğu için **kapalı** yazılır. Model kimliği bilinmediği için API sağlayıcısı eklenmez; anahtarı tanımlı olanlar için not basılır. **Hiçbir onay verilmez**, `doctor` çalışmaz. Var olan dosyanın üzerine yalnız `--force` ile yazar (`.bak`).
- **Düz `init`:** terminalde (stdin ve stdout) sihirbazı açar (11a'da düz sorular, 11b'de arayüz); terminal yoksa, `--json` ya da `--force` ile eski davranış (örnek kopyalanır), böylece var olan testler ve betikler değişmedi. `--plain --defaults` ve `--plain --json` kod 2. Girdi yoksa (kapalı stdin, Windows NUL) anlaşılır hata, kod 2, hiçbir şey yazılmaz.
- **i18n:** 45 yeni anahtar (en + tr); `cli.init.help` değişti, yeni davranışı anlatıyor.
- **Bilinen sınırlar:** algılama Ollama'yı varsayılan adreste arar (config'teki farklı `base_url` kullanılmaz); sürüm sondası sırayla çalışır (bu makinede ~5 sn); `providers enable`'ın kendi onay sorusu hâlâ `typer.confirm` (y/n).
- **Testler:** 1137 → **1195** (+58).
Mimari §22 güncellendi (D-068).

## D-069 – Faz 11a kod denetimi düzeltmeleri (2026-11-14, Faz 11a)
**Başlangıç:** `/code-review` (PR #21): 10 bulgu; hepsi gerçek. Önce kırmızı testler yazıldı (19 kırmızı), sonra kod.
**Karar:**
- **Düz `init` var olan dosyayı asla düzenlemez:** terminalde dosya varsa eskisi gibi "zaten var" der ve `init --plain` ipucunu verir. Var olan dosyayı düzenlemek yalnız açık `--plain` ile olur (yorumlar kalır, yedek alınır); `--plain --force` örnekten (proje dosyasında boş dosyadan) yeniden başlar. Yardım metinleri buna göre.
- **Hiçbir yedek ezilmez:** D-068'in "tek dönen `.bak`" kararı geri alındı; `init --force`'un sakladığı gerçek config sonraki bir sihirbaz kaydıyla siliniyordu. Yazıcı `loader.free_backup_path` kullanır (`.bak`, `.bak.1` …). Atomik yazma, yedek adı ve aynı dosya denetimi tek yerde (`loader.atomic_write`, `free_backup_path`, `same_file`); `loader`'ın eski sabit adlı geçici dosyası da benzersiz `mkstemp` oldu.
- **Var olan dosyada kullanıcının yazdıkları kalır:** bir girdinin kimliği (`type`, `base_url`, `command`, `api_key_env`, `local`, `experimental`) yalnız yoksa doldurulur; `models` kimliğe göre birleşir (var olan model `context_window`, fiyat, yorum gibi alanlarını korur, yalnız kademesi değişir); iç içe eşlemeler birleşir (`extra_args` vb. dokunulmaz).
- **Sihirbazın sunmadığı sağlayıcıya dokunulmaz:** yalnız listelenen yerleşik adlar (`ollama`, 6 API, `codex`, `agy`) seçilmeyince kapatılır; `lmstudio` gibi özel sağlayıcılar olduğu gibi kalır.
- **Varsayılanlar mevcut config'ten:** `--plain` (`--force`'suz) etkin config'i okur; dil, açık sağlayıcılar (algılananlarla birlikte seçili), model kademeleri, API model kimliği, günlük USD/koşu, agy'nin açık olup olmadığı ve varsayılan şef dosyadan gelir. Her soruda Enter'a basmak hiçbir şeyi değiştirmez.
- **Onay kayıttan sonra:** kaydedilen girdi `consent.describe` ile gösterilir ve onay o girdinin hash'iyle kaydedilir; gösterilen ile kaydedilen arasında fark kalmaz (önceden yalnız sihirbazın ayarları gösteriliyor, birleşmiş config kaydediliyordu). Mimari §22'deki sıra (onay, kayıt yerinden önce) bu yüzden değişti: kayıt → onay → doctor. `--defaults` hiç sormaz, hiç onay vermez.
- **Yeni proje dosyası yalnız cevapları taşır:** örneğin tamamı (dil, profil, şefler, güvenlik…) proje dosyasına yazılınca bütün global ayarları eziyordu. Artık `version` + seçilen sağlayıcılar (+ sorulan dil/şef); global config'teki seçilmeyen yerleşik sağlayıcılar bu projede `enabled: false`, özel olanlar global'e bırakılır.
- **Embedding modelleri işçi olmaz:** adında `embed` geçen ya da Ollama ailesi `bert`/`nomic-bert` olan modeller `skipped` listesine gider, sihirbazda sunulmaz ve `--defaults`'a girmez; algılama özetinde ayrıca yazılır.
- **`1,²` çökmez:** numaralar yalnız ASCII rakam (`"²".isdigit()` doğru ama `int("²")` hata veriyordu); yeniden sorulur.
- **i18n:** 2 yeni anahtar (`wizard.detect.embedding`, `wizard.hint.edit`), `cli.init.help` ve `cli.init.option.plain` güncellendi.
Mimari §22 güncellendi (D-069).

## D-070 – Faz 11b: terminal arayüzü, arayüzlü sihirbaz ve 5 dil (2026-11-14, Faz 11b)
**Bağlam:** Mimari §22, plan Faz 11 (2/2). 11a'nın servisleri (algılama, `tui/wizard.py`, `config/writer.py`) üzerine arayüz ve çeviriler.
**Karar:**
- **Bağımlılık:** `textual>=8.2,<9` (Mimari §1'de var; kurulan 8.2.8). Textual yalnız `orkestra ui` ve terminaldeki düz `init` yolunda içe aktarılır; diğer komutların açılışı yavaşlamaz.
- **`orkestra ui`:** sekmeler: Durum (`status` raporu), Sağlayıcılar (aç/kapat, "test et" = o sağlayıcının `doctor` denetimleri, `doctor.check_one`), Bütçeler (sınır yaz/boşalt), Profiller (varsayılan profil ve şef), Onaylar (`consent.describe` gösterilir, açık onay/geri alma), Devir (devir dosyası varsa özet), Ayarlar (dil). **Kuyruk sekmesi yok** (Faz 12'nin işi, hazırlık kodu yazılmadı); bildirim ayarı da Faz 12'ye kaldı.
- **Ekranlarda iş mantığı yok:** tek değer değişikliği yeni `config/edits.py` (değer hangi dosyada tanımlıysa orada, yoksa base config; yorumlar kalır, yazmadan önce doğrulanır, yedek, atomik). Geçersiz değer (negatif bütçe) yazılmaz; hata seçili dilde ekranda.
- **Metin paylaşımı:** sağlayıcı satırı ve bütçe metni `providers/display.py`'ye (CLI'deki özel fonksiyonlar taşındı); sihirbaz sonuç satırları `wizard.outcome_lines`/`consent_lines`, doctor satırları `doctor.report_lines`; evet/hayır sorusu `wizard.confirm_by_asking`. CLI ve arayüz aynı metni üretir.
- **Arayüzlü sihirbaz:** 11a'daki `run_plain` akışının kendisi; bir iş parçacığı onu sürer, her soru küçük bir ekran (`QuestionScreen`, giriş kutusu `AUTO_FOCUS` ile odakta; boş cevap varsayılan; Escape iptal → `WizardCancelled`, kod 2). Uygulama kapanırsa bekleyen soru iptal olur, iş parçacığı asılı kalmaz (kapanışta takılma hatası pilot testte bulundu). Sonuç satırları uygulama kapanınca terminale yeniden yazılır.
- **Düz `init`:** terminalde ve dosya yokken arayüzlü sihirbazı açar; `TERM=dumb` gibi arayüzün çizilemediği bir terminalde düz sorulara (`--plain`) düşer. `orkestra ui` terminal yoksa/`TERM=dumb` ise kod 2 ve `--plain` önerisi.
- **Dil anında değişir:** Ayarlar'da kaydedilince arayüz tümüyle yeniden kurulur (`recompose`). Yeniden kurulum düğme işleyicisinin dışına (`call_later`) alındı: işleyici kendini silen yeniden kurulumu bekleyince kilitleniyordu (pilot testte bulundu).
- **Çeviriler (`de`, `es`, `fr`):** Orkestra'nın kendisiyle: üç `edit` görevlik bir batch, işçi `agy`; her görev yalnız kendi katalogunu değiştirebilir, `en.yaml` ve sözlük korumalı; doğrulayıcı `tests/fixtures/check_catalog.py <dil>` (anahtarlar, yer tutucular, boş değer, biçimlenme, İngilizcenin kopyası olmama). Terim sözlüğü ve kurallar `src/orkestra/i18n/locales/README.md`'de. Bundan sonra her yeni anahtar beş dile eklenir (AGENTS.md kuralı).
- **Testler:** i18n tamlık testleri 5 dile genişledi (`CATALOG_LANGUAGES = SUPPORTED_LANGUAGES`); "katalog İngilizcenin kopyası değil" ve `--lang de/es/fr` testleri eklendi.
- **Çeviri sonucu:** batch `b-20261114-014020-0888`, 3/3 `ok`, yeniden deneme yok, toplam 45 dk (agy, günlük 10 koşudan 3'ü); `orkestra apply --batch … --only-ok` ile uygulandı. Claude örnek satırları okudu: sözlük terimleri tutarlı, komutlar/yer tutucular/dosya adları yerinde, hitap `du`/`tú`/`tu`, Fransızca noktalama doğru. Ana dili konuşan biri tarafından gözden geçirilmedi.
- **Değişen var olan testler:** `CATALOG_LANGUAGES` beş dile genişledi (planın istediği); `test_t_language_without_catalog_uses_english` artık Almanca katalog olduğu için boş bir katalogla aynı davranışı doğruluyor (beklenen değer aynı).
- **Testler:** 1205 → **1229** (+24).
Mimari §22 güncellendi (D-070).

## D-071 – Faz 11b kod denetimi düzeltmeleri (2026-11-14, Faz 11b)
`/code-review` (PR #22): 10 bulgu, hepsi düzeltildi; önce 9 kırmızı test. Bozuk config'te `ui` çökmüyor (boş Select yok, hata gösteriliyor); `config/edits.py`: değer tam tanımlandığı dosyaya yazılır, `None` her tanımlandığı dosyadan siler ve hiçbir yerde yoksa hiçbir şey yazmaz, aynı dosyaya giden değerler tek kayıt (`set_values`); Profiller yalnız değişeni yazar; bir değişiklikten sonra bütün sekmeler yenilenir; test sonucu yeniden kurulan sekmeye gider, kaybolan sekmede çökmez; sihirbaz ve sağlayıcı testi daemon iş parçacığında (Ctrl+Q beklemez); beklenmeyen hata `init`'i 0 ile bitirmez, `exit_code_for` ile doğru kod; sihirbaz akışı tek serviste (`wizard.run_and_save`, CLI ve arayüz ortak). Testler 1229 → 1238.

## D-072 – Faz 12a: gece kuyruğu ve bildirimler (2026-11-15, Faz 12a)
**Bağlam:** Mimari §6, §21; plan Faz 12 (1/2). Faz 12 ikiye bölündü: 12a kuyruk + bildirim, 12b öğrenen yönlendirme + arayüzde Kuyruk sekmesi + skill (yerel YAPILIS_PLANI.md).
**Karar:**
- **Migration 0003 (`queue`, `queue_lock`).** Mimari §6'daki `queue` tablosuna üç sütun eklendi: `workdir` (işin eklendiği klasör), `file_hash` (§21 hash'i kaydetmeyi istiyor ama tabloda sütunu yoktu) ve `note` (başarısızlık/atlama nedeni). Kilit için ayrı tek satırlık `queue_lock` tablosu (pid + süreç başlama zamanı + başlangıç).
- **İş eklendiği klasörde çalışır.** Görev yolları ve proje config'i (`orkestra.yaml`) çalışma dizinine göre çözülüyor; cron/Görev Zamanlayıcı başka klasörde başlatır. `queue run` her iş için `contextlib.chdir(workdir)` içinde config'i yeniden yükler ve `run`/`batch` ile aynı servisleri çağırır (`runner.run_task`, `batch.run_batch`). Alt süreç yerine süreç içi: kesinti/kurtarma ve testler basit, bütçe/rezervasyon aynı. Klasör yoksa iş `failed` (not ile).
- **Kilit:** `BEGIN IMMEDIATE` içinde okunur; sahibi yaşıyorsa `QueueBusy` (yeni hata, kod 5, `HandoffLocked` gibi). "Yaşıyor" = pid var **ve** süreç başlama zamanı kayıtla aynı (±1 sn): pid yeniden kullanılmışsa kilit ölü sayılır. `AccessDenied` yaşıyor sayılır. Kilit `finally` ile bırakılır (Ctrl+C dahil).
- **Kesinti:** kilidi alan çalıştırma önce `running` → `pending` yapar (kilit tek sahipli olduğu için `running` kalan her iş öksüzdür).
- **`--until HH:MM`:** başlangıçtan sonraki ilk o saat (22:00'de `08:00` = ertesi sabah; tam o saatte başlatılırsa ertesi gün). Her yeni işten önce bakılır, çalışan iş kesilmez. Saat enjekte edilebilir (`now`).
- **`--max-cost-usd`:** her yeni işten önce harcanan ≥ sınır ise durur. Ücretli sağlayıcı varsa iş başlamadan tahmin edilir (`batch.estimate_batch`, fiyatlar tazelenir); tahmin kalan tutarı aşıyor veya fiyatı bilinmeyen ücretli model varsa iş **atlanır**. Çalışan iş sınırı aşabilir (sağlayıcı bütçeleri asıl korumadır).
- **Gece maliyet onayı yok:** `--max-cost-usd` verilmemişse `estimate.confirm_above_usd`'yi aşacak iş atlanır. **Atlanan iş `pending` kalır** (notuyla), bir sonraki çalıştırmada yeniden denenir; aynı çalıştırmada sıradaki işe geçilir. Döngü `id > son_id` ile ilerler, çalışırken eklenen iş de alınır.
- **Profil:** `--profile` verilmeyen iş `queue.default_profile` ile çalışır, ama bu profil *varsayılan* gibi davranır (config kopyasında `defaults.profile` değişir): yüksek kademe isteyen görev açık `--profile` gibi kullanım hatası vermez (router.tier_range). `queue add --profile` bilinmeyen profili reddeder.
- **Bozuk iş diğerlerini durdurmaz:** beklenmeyen hata işi `failed` yapar (not: hata metni); `KeyboardInterrupt` döngüyü durdurur, iş `running` kalır ve sonraki çalıştırmada kurtarılır. Çıkış kodu: başarısız iş varsa 1, yoksa 0; kilit doluysa 5; `--until` hatalıysa 2.
- **Bildirim (`notify/notify.py`):** masaüstü `desktop-notifier` (`orkestra-cli[notify]` ekstrası, `importlib` ile tembel yükleme; yoksa `skipped`), ntfy `https://ntfy.sh/<konu>` httpx POST, konu `notify.ntfy_topic_env`'deki değişkenden; konu yalnız `[A-Za-z0-9_-]{1,64}` (URL'ye başka yol/sorgu eklenemez). Metin yalnız sayılar (`notify.counts`); konu hiçbir çıktıya yazılmaz. Hiçbir kanal hatası komutu düşürmez. `queue run --notify` sonunda sayıları, beklenmeyen hatada kısa "kuyruk hata yüzünden durdu" gönderir (kilit doluyken, kullanım hatasında ve Ctrl+C'de göndermez). `batch --notify` aynı metin. `notify test`: her kanal için satır; hiçbiri gönderilmezse kod 1.
- **`status`:** `queue` bölümü (order 40): bekleyen/çalışan/başarısız sayısı; hepsi sıfırsa satır yok.
- **Bağımlılık:** `desktop-notifier>=6.0` yalnız `notify` ekstrasında (Mimari §1'de var; kilitlenen 6.2.0, API'si elle denendi).
- **Testler gerçek bildirim göndermez:** conftest `no_real_notifications` masaüstünü kapatır, ntfy'ye gidecekleri kaydeder.
- **Değişen var olan testler:** `test_state.py`'deki şema sürümü beklentileri 2 → 3 (yeni migration; plan gereği), `examples/orkestra.example.yaml` örnek config yorumlarıyla eşitlendi.
- **Bilinen sınır:** işin notu çalıştığı andaki dilde saklanır (hata metinleri çevrilmiş üretiliyor); başka dilde `queue list` notu o dilde gösterir. Bitmiş işler `queue remove` ile çıkarılana kadar listede kalır.
- **Testler:** 1238 → 1286 (+48).
Mimari §6 ve §21 güncellendi (D-072).

## D-073 – Faz 12a kod denetimi düzeltmeleri (2026-11-15, Faz 12a)
`/code-review` (PR #23): 10 bulgu, hepsi düzeltildi; önce 14 kırmızı test.
- **ntfy başlığı** HTTP başlığı yerine ntfy'nin `?title=` sorgu parametresinde: başlık ASCII olmak zorundaydı, "Orkestra kuyruğu" `UnicodeEncodeError` veriyordu (Türkçe arayüzde telefon bildirimi hiç gitmiyordu).
- **Göreli `--config`/`ORKESTRA_CONFIG`** `queue run` başında mutlak yola çevrilir (`service.absolute_config_flag`); işler kendi klasöründe çalıştığı için göreli yol başka yeri gösteriyordu. Varsayılan genel dosya `None` kalır (yoksa varsayılanlar).
- **`mark_running` yalnız `pending` işi alır**; okunduktan sonra `queue remove` edilen iş çalışmaz (döngü atlar).
- **Sahipsiz `running` iş çıkarılabilir:** kilidin canlı sahibi yoksa (Ctrl+C/çökme) `queue remove` izin verir. Var olan `test_remove_hides_a_pending_item_but_never_a_running_one` artık canlı kilit tutarak reddi doğruluyor (davranış bilerek değişti).
- **`--max-cost-usd 0`** = yalnız ücretsiz iş: sınır 0 iken harcanan > 0 olunca durur (önce hiç iş başlamıyordu).
- **`--until` DST'de kaymaz:** duvar saatinde hesaplanır, sonra kendi UTC ofsetiyle yerelleştirilir (`localize`, testte DST'li sahte saat dilimi; Windows'ta tzdata yok).
- **Tek görev maliyet onayı beklemez:** `orkestra run` hiç sormadığı için kuyruktaki tek görev de sormaz; onay kapısı yalnız batch için (`cost_skip(confirm=)`). D-072'deki "sınır yoksa onay isteyecek iş atlanır" kuralı yalnız batch'e daraltıldı. Atlanan iş sayısı bildirime de girdi (`notify.counts_skipped`, 5 dil).
- **`psutil.AccessDenied` artık "bizim koşucumuz değil":** kendi sürecimizin başlama zamanı her zaman okunur; okunamıyorsa başka kullanıcının/sistemin süreci, kilit ölü sayılır (D-072'deki "yaşıyor sayılır" geri alındı; aksi halde yeniden kullanılan pid kuyruğu kalıcı kilitliyordu).
- **`status` kuyruk satırı** yalnız son 24 saatin başarısızlarını sayar (`counts(failed_since=)`); eski bir başarısızlık satırı sonsuza dek tutmuyor. `queue list` hepsini göstermeye devam eder.
- **`mark_finished`** yanlış durumda `InternalError` (çıplak `ValueError` değil).
- **Testler:** 1286 → 1300 (+14).
Mimari §21 notu güncellendi (D-073).

## D-074 – Faz 12b: öğrenen yönlendirme, arayüzde kuyruk ve bildirim ayarı (2026-11-15, Faz 12b)
**Bağlam:** Mimari §7, §20, §22; plan Faz 12 (2/2).
**Karar:**
- **`routing/adaptive.py` saf fonksiyonlar:** `laplace`, `score_for`, `scores`; veritabanına yalnız `load_outcomes` dokunur. Kaynak: son 30 günün bitmiş koşuları (`ok`, `failed`, `escalate`, `error`). Koşu, son sonucu veren (provider, model) için sayılır; olmayanlar (`escalate`, cevaptan önce düşen) son yerleşmiş isteğin sağlayıcısına (`usage`), `orkestra stats` gibi. Hiç istek göndermeyen koşu sayılmaz.
- **Grup:** (provider, model, etiket); etiketsiz görev etiketsiz koşuları kullanır. **Birden çok etiketli görev:** etiketlerinden herhangi birini taşıyan koşular, her koşu bir kez (aynı koşu iki etiket grubunda iki kez sayılmasın). Tek etiketli görevde Mimari'deki grupla aynı.
- **Kod ajanları** yalnız sağlayıcı adıyla eşleşir (modeli koşudan koşuya değişebilir); aday kimliği router'daki gibi `model or kind`.
- **Sıralama:** kademe ↑ → skor ↓ → `priority` ↓ → config sırası (Mimari §7 adım 4 ile aynı; skor priority'den önce). `min_samples` altı nötr 0.5: skoru 0.5'in altında olan model, hiç denenmemiş modelin arkasına düşer. Kademe asla değişmez (tablo testi).
- **`take_snapshot(tags=)`:** skorlar yalnız `routing.adaptive: true` iken okunur (bir sorgu + sağlayıcısız koşu başına bir `usage` sorgusu). Şefin model sorgusu (`chief/call.py`) etiket vermez, etiketsiz grubu kullanır.
- **`--dry-run`:** her adayda `score` (≈ başarı oranı), `score_samples`, `score_used` (JSON); metinde "skor 0.80 (3/3 başarılı)" veya "skor nötr (koşu 0/10, henüz az)". Adaptive kapalıyken bu alanlar `null`, sıra eskisi gibi.
- **Arayüz Kuyruk sekmesi:** liste (no, durum, tür, profil, dosya, sonuç), Yenile, Çıkar (`queue_store.remove`, sahipsiz `running` dahil). **Arayüzden `queue run` yok:** saatler sürebilir ve terminal/zamanlayıcıda çalışmalı; sekme komutu gösterir.
- **Ayarlar'da bildirim:** masaüstü açık/kapalı, ntfy değişken adı (boş = kaldır), "Deneme gönder" (arka plan iş parçacığında `notify.send`, kanal satırları). İki değer tek kayıtta yazılır: hatalı ad varsa hiçbir şey yazılmaz.
- **Şema:** `notify.ntfy_topic_env` artık ortam değişkeni adı olmalı (`^[A-Za-z_][A-Za-z0-9_]*$`). Arayüzde bu kutuya konunun kendisi yazılırsa config dosyasına (gizli sayılması gereken) konu girerdi. Bu değeri ad olmayan eski bir config artık doğrulamadan geçmez (bilerek: o değer zaten sızıntıydı).
- **Skill:** gece kuyruğu paragrafı (kuyruğu şef çalıştırmaz, kullanıcıya komutu ve `docs/recipes.md`'yi önerir; sonuçlar `queue list --json` → `result_ref`) ve öğrenen yönlendirme notu (tutarlı `tags`, `--dry-run --json` skoru).
- **Testler:** 1300 → 1337 (+37).
Mimari §20 ve §22 güncellendi (D-074).

## D-075 – Faz 12b kod denetimi düzeltmeleri (2026-11-15, Faz 12b)
`/code-review` (PR #24): 10 bulgu, hepsi düzeltildi; önce 14 kırmızı test.
- **Değiştirilen model artık sayılıyor:** bir koşuda cevap verip (`usage`'da completion token > 0) yerini başka modele bırakan her model (aynı modelle tekrar değil; başka modele tekrar, yedeğe geçiş, üst kademe) o koşu için bir kez **başarısız** sayılır. Önce yalnız son sonucu veren model sayılıyordu: kademe 1'de hep doğrulamayı geçemeyen model hiç veri almıyor, sonsuza dek nötr kalıp önde deneniyordu. Cevap alınamayan istek (çevrimdışı, reddedilen) sayılmaz. Son modeli olmayan koşu, son cevap veren modele başarısızlık. Bu, `orkestra stats`'ın sayımından bilerek farklı (stats koşu başına tek sağlayıcı).
- **`error` koşuları sayılmaz** (Ctrl+C, disk/worktree hatası, bütün sağlayıcılar çevrimdışı): model kalitesi hakkında bilgi değil; bir akşamlık kesinti iyi bir modeli 30 gün geriye atıyordu.
- **Şema geri gevşetildi:** D-074'teki `ntfy_topic_env` deseni, bu alanda konu yazan eski config'i tümüyle doğrulamadan düşürüyor ve arayüz bunu düzeltemiyordu. Artık düz `str`; ad olmayan değeri `notify` hiç kullanmaz ve göstermez (`env_invalid`, "konuyu değil değişkenin adını yaz"), arayüz kaydetmez (`ui.error.ntfy_env`). Arayüzde kutu boşaltılıp kaydedilince eski değer silinir.
- **Kuyruk sekmesi çökmüyor:** kilitli `state.db` (`sqlite3.Error`) veya `OrkestraError` sekmede mesaj olur; açılış ve başka sekmedeki kayıt (`refresh_panes`) uygulamayı düşürmez.
- **Açıkça seçilen modelin geçmişi görünüyor:** kod ajanı skoru her zaman config kimliğiyle (`model or kind`) aranır; config'te olmayan API modeli (`extra_model`) de skorlanır.
- **Tek sorgu:** cevap veren istekler pencere için tek `usage` sorgusuyla okunur (önce koşu başına bir sorgu). `load_outcomes` en fazla iki SELECT (test). Batch'te görev başına okuma kaldı (iki sorgu; önbellek gerekmedi).
- **Ortak yardımcılar:** `stats.parse_tags`, `stats.parse_started`, `stats.OFFSET_MARGIN` açıldı, `adaptive` bunları kullanır (kopya yok).
- **Bildirim ayarı tek kayıt:** `edits.set_values` içinde `None` aynı kayıtta anahtarı siler (yoksa hiçbir şey); masaüstü + değişken adı tek yedek, tek yazma.
- **Deneme bildirimi iş parçacığı** hatayı yakalar ve ekranda gösterir ("Gönderiliyor..." sonsuza dek kalmaz).
- **Kuyruktan çıkarma onay ister** (`ConfirmScreen`); `ids` panelde tanımlı.
- **Testler:** 1337 → 1346 (+13 yeni, şema desen testlerinin 4'ü kaldırıldı: karar geri alındı).
Mimari §20 ve §22 notları güncellendi (D-075).

## D-076 – Faz 13a: benchmark aracı ve 20 görev (2026-11-15, Faz 13a)
**Bağlam:** plan Faz 13. Faz 13 ikiye bölündü: **13a** araç + görevler (masrafsız), **13b** gerçek koşu (180 koşu, 120'si Claude oturumu; kullanıcının kotasıyla, Ollama açıkken) + sonuçlar + README tablosu.
**Karar:**
- **Görev biçimi** `bench/tasks/<id>/`: `task.yaml` (id, difficulty, category, prompt, files, isteğe bağlı `check`, `allow_new_files`), `project/` (başlangıç), `hidden/` (gizli testler), `solution/` (referans çözüm). Plan "küçük proje + gizli testler + açıklama" diyordu; **referans çözüm eklendi**: test takımı her görevde gizli testlerin başlangıçta *kaldığını* ve çözümde *geçtiğini* doğrular (görev zaten çözülmüş ya da çözülemez değil). Görünür `check` hem başlangıçta hem çözümde geçer.
- **Test yazma görevi** (10) mutasyonla değerlendirilir: gizli test, işçinin yazdığı testleri gerçek koda (geçmeli) ve 7 bozuk sürüme (her biri kalmalı) karşı koşar.
- **Sızıntı koruması:** çalışma dizini yalnız `project/` (git deposu); koşu başlamadan `check_no_leak` dizinde gizli test (ad veya içerik) / çözüm dosyası ya da istemde gizli testten bir satır görürse durdurur; mod C'de `check_orkestra_task` bağlam yolu/glob'u dizinden çıkabiliyorsa durdurur. Gizli testler yalnız koşudan sonra ayrı bir değerlendirme kopyasına konur. Sınır: A/B'de Claude Code mutlak yolla depo dosyalarını okuyabilir (belgede).
- **Modlar:** A `--disable-slash-commands --strict-mcp-config`; B skill'i çalışma dizinine proje skill'i olarak koyar ve `Bash(orkestra:*)` izni + kısa ipucu ekler; ikisi de `--setting-sources project --no-session-persistence --permission-mode acceptEdits` ve aynı araç izinleri (read/edit/write/glob/grep, python, pytest, git). C: `orkestra run --profile cheap --json` (+ `ok` ise `apply`). Kurulu `claude` 2.1.325'in `--help`'iyle doğrulandı.
- **Bench Orkestra evi:** koşu başına ayrı `ORKESTRA_HOME` (yalnız yerel Ollama, `cache.enabled: false`: aynı görev tekrarlanıyor; `routing.adaptive: false`: tekrarlar aynı yoldan; masaüstü bildirimi kapalı), onay programla verilir.
- **Ölçüler:** gizli testler (geçti/kaldı; tekrarlar arası ortalama, min, max), Claude token'ı (input + output + cache creation; cache read ayrı; birincil ölçü), Claude maliyeti, işçi maliyeti/koşu sayısı ve `stats` tasarruf tahmini (koşu süresi penceresinde) — B'deki tahmin gerçek A − B farkıyla karşılaştırılır.
- **Sonuç dosyaları** her koşudan sonra yazılır (çökme yapılanı korur): `bench/results/<tarih>.json` + `.md`.
- **Yer ve araçlar:** `bench/` paket değil (wheel'e girmez), testler `pythonpath = ["."]` ile içe aktarır; pyright `bench`'i denetler, ruff/pyright `bench/tasks`'ı denetlemez (başlangıç kodu bilerek kaba). Geliştirici aracı olduğu için çıktısı yalnız İngilizce (i18n yok).
- **Görevler** Claude tarafından sıfırdan yazıldı (mevcut setlerden kopya yok); tek seferlik üretici betikler, görev dosyaları yazıldıktan sonra silindi (iki kopya kalmasın).
- **Testler:** 1346 → 1390 (+44; bench doğrulamaları normal koşuya girdi, ~55 sn ekler).

## D-077 – Faz 13a kod denetimi düzeltmeleri (2026-11-15, Faz 13a)
`/code-review` (PR #25): 10 bulgu, hepsi düzeltildi; önce 9 kırmızı test (2'si baştan yeşildi, regresyon koruması olarak kaldı).
- **İstem stdin'den, izinler `--settings` dosyasından:** bu makinede `claude` npm `claude.CMD`; çok satırlı/tırnaklı istem argümanı cmd.exe'de kesilir ve arkadan gelen bayraklar kaybolurdu (bütün A/B koşuları geçersiz olurdu). Artık hiçbir argümanda istem, yeni satır veya tırnak yok; mod B ipucu istemin başına eklenir (`--append-system-prompt` yerine). `--setting-sources project` ile `--settings` dosyasının birlikte çalıştığı 13b'nin ilk gerçek koşusunda doğrulanacak.
- **Takılan görünür kontrol** (`run_check`) 124 döner; benchmark'ı durdurmaz.
- **Claude zaman aşımı/çökmesi:** çıkış kodu ve stderr hatada kalır; kullanım yoksa kayıt `claude=None` ve token ortalamalarına **0 olarak girmez** (`runs_without_usage` sayısı).
- **Görev 10:** mutantlar ve "gerçek kod" koşusu, gizli testin içine gömülü **özgün** `stack.py`'den; işçinin `stack.py`'yi yeniden biçimlendirmesi ya da zayıf testlere uydurması puanı bozmaz.
- **Görev 07:** listeli frozen dataclass hash'lenemez; istemden "hashing" çıkarıldı.
- **Görev 20:** gizli test önbellek nesnesini değiştirmiyor (`service.CACHE.clear()`); önbelleği adıyla içe aktaran doğru çözüm de geçiyor. Süre dolması birim testte (enjekte saatle).
- **Sızıntı koruması tetiklenince** (`LeakError`) koşu hatası sayılmaz: bütün benchmark durur (kod 3).
- **`--ollama-model-2`** yalnız mod B'de kullanılabilir (C `cheap` = kademe 1); yardım metni, README ve sonuç başlığı bunu söylüyor.
- **Bench config'i** ruamel (`loader.dump_yaml`) ile yazılıyor; tuhaf model adları (": ", "#") bozmuyor.
- **`BenchError`** artık `OrkestraError`'dan türüyor (AGENTS.md hata hiyerarşisi kuralı).
- **Testler:** 1390 → 1400 (+10).

## D-078 – Faz 13b: kota korumaları (2026-11-15, Faz 13b)
**Bağlam:** kullanıcının 5 saatlik Claude limiti 120 oturuma yetmez; limit koşu ortasında dolarsa araç bunu "görev başarısız" sayar ve sonuçları bozardı. Kullanıcı Faz 13'ün kalanını 13b (korumalar) / 13c (deneme ve ölçüm) / 13d (ilk tur) / 13e (2.–3. tur ve sonuçlar) olarak böldürdü.
**Karar:**
- **Limit algılama:** koşu başarısızsa (çıkış kodu ≠ 0 veya JSON `is_error`) ve çıktıda kullanım limiti / 429 / aşırı yük (529) izi varsa `UsageLimitReached`: koşu kaydedilmez, sonuç dosyası yazılır, benchmark kod 4 ile durur ve devam komutunu yazar. Başarılı bir cevapta aynı kelimeler limit sayılmaz (yalnız başarısız koşuda bakılır). Aşırı yük de durdurur: geçici ama sonuçları "başarısız" diye bozmasın.
- **`--resume <dosya>`:** bitmiş (görev, mod, tekrar) koşuları atlar, aynı dosyaya ekler; görevler, modlar ve modeller dosyanın `meta`'sından gelir (`task_ids`, `modes`, `ollama_model`, `ollama_model_2`, `claude_model`; makinece okunur alanlar). Farklı `--tasks`/`--mode` kod 2; `--repeat` büyüyebilir (yeni turlar eklenir).
- **`--max-claude-runs N`:** bu çağrıda en fazla N Claude oturumu; sınıra gelince bir sonraki Claude koşusundan önce temiz durur (kod 0) ve devam komutunu yazar. Mod C koşuları sayılmaz.
- Sürüm sorguları (`claude --version`, `orkestra --version`) da koşturucu üzerinden: testler gerçek program başlatmaz; `which` enjekte edilebilir.
- Her çağrı kendi bench evini kurar (işçi istatistikleri koşu süresi penceresinde okunduğu için devam eden koşuyu etkilemez).
- **Testler:** 1400 → 1410 (+10; 1'i baştan yeşil: başarılı cevaptaki "rate limit" kelimesi).

## D-079 – Faz 13b kod denetimi düzeltmeleri (2026-11-15, Faz 13b)
`/code-review` (PR #26): 10 bulgu, hepsi düzeltildi; önce 15 kırmızı test.
- **Limit deseni yalnız sonuç metninde ve stderr'de** aranır (JSON'daki kullanım sayıları değil: `"output_tokens": 529` benchmark'ı durdurup her `--resume`'u aynı yerde kilitliyordu) ve özel ifadelerle (`usage limit`, `5-hour/weekly limit`, `limit reached … reset`, `rate_limit_error`, `overloaded`, `API Error: 429/529`); "context limit reached" model hatasıdır.
- **Olay listesi biçimi** ve **normal sonuç olarak gelen limit mesajı** (çıkış 0, `is_error` false, kısa metin) da limit sayılır; sonuç olayı tek yardımcıdan (`result_event`).
- **Sonuç dosyaları atomik** (geçici dosya + `os.replace`): bütün pencereler tek dosyada, kesilen yazma hepsini kaybettirmesin.
- **Devam edilemeyen dosya** (yok, JSON değil, 13a biçimi) kod 2 ve açık mesaj.
- **`--version` başarısız/zaman aşımı** → "unknown" (stderr sürüm yazılmaz).
- **Devamda farklı model/zaman aşımı** (`--ollama-model`, `--ollama-model-2`, `--claude-model`, `--timeout`) reddedilir; varsayılanları açıkça verilmemiş sayılır. **Sürümler pencere başına** `meta.windows`'ta (tarih, claude, orkestra, koşu sayısı); değişirse uyarı.
- `--tasks` sonundaki virgül boş önek üretmiyor.
- **Yarım kalan tur puanlanmaz** (`complete_repeats`, `partial_runs`; tabloda "partial").
- Rapor başlığı okunur: `None` yerine `-`/`default`, görev listesi virgüllü, pencereler satır satır.
- **Testler:** 1410 → 1425 (+15).

## D-080 – Faz 13c: ilk gerçek deneme ve ölçüm (2026-11-15, Faz 13c)
**Bağlam:** 2 görev (01 kolay, 09 orta) × 3 mod × 1 tekrar, gerçek Claude Code 2.1.325 ve Ollama `qwen2.5-coder:14b`; sonuçlar `bench/results/trial/`.
**Sonuç:**
- 6/6 geçti. A: 18 / 23 sn, 4 / 7 tur, oturum başına ~75–115 bin token (çoğu önbellekten okuma), Claude token'ı (girdi+çıktı+önbelleğe yazma) ~7,2 bin/görev, API karşılığı $0.085–0.097. B: 18 / 19 sn, ~9,9 bin/görev, $0.112–0.115, **Claude hiç delege etmedi** (işçi koşusu 0). C: 74 / 11 sn, işçi ~800–1.000 token, $0.
- **Benchmark Windows'ta gerçekten çalışıyor:** istem stdin'den gidiyor (`claude.CMD` sorunu yok), Claude dosya düzenleyip testleri çalıştırabiliyor (mod B'de ölçülen `permission_denials` 0: `--settings` izinleri `--setting-sources project` ile birlikte okunuyor; mod A denemesi bu alan eklenmeden önce koşuldu, orada ölçülmedi — D-081), mod B'nin önbelleğe yazdığı fazladan ~2,8 bin token skill açıklaması + ipucunun boyutuna uyuyor (skill'in yüklendiğine dolaylı kanıt).
- **İlk bulgu (dürüst):** küçük tek dosyalı görevlerde skill Claude'a iş devrettirmiyor; B, A'dan ~%23 pahalı (skill metni). 20 görevin çoğu küçük olduğu için tam koşuda B'nin A'ya yakın ya da biraz pahalı çıkması beklenir. Kullanıcıya soruldu: B'yi olduğu gibi (skill'in doğal kullanımı) ölçmek ve/veya "uygunsa değil, mümkünse orkestra kullan" diyen ek bir mod eklemek (karar 13d'den önce).
**Koddaki değişiklikler (denemenin gösterdikleri):** reddedilen araç izinleri (`permission_denials`) kayıtta ve raporda; her koşunun ham Claude çıktısı `claude-output.json` (iş klasöründe, repoda değil); değerlendirmede pytest-asyncio eklentisi kapalı (uyarı gürültüsü); **kayıtlarda kişisel yol yok** (`scrub`: iş klasörü, repo, geçici klasör, ev dizini yer tutucuya) — ilk deneme dosyasında venv yolu vardı, temizlendi.
- **Testler:** 1425 → 1429 (+4).
- **Açık:** kullanıcının `/usage` farkı (4 Claude oturumunun 5 saatlik limitten payı) — gelince 13d'nin pencere planı ona göre.

## D-081 – Faz 13c kod denetimi düzeltmeleri (2026-11-15, Faz 13c)
`/code-review` (PR #27): 10 bulgu, hepsi düzeltildi; önce 8 kırmızı test.
- **Yol temizleyici yeniden yazıldı (`Scrubber`):** her yer (iş klasörü, repo, geçici klasör, ev dizini) parçaları **herhangi bir eğik çizgi dizisiyle** birleşen, büyük/küçük harf duyarsız tek desen (tek/çift ters eğik çizgi, JSON'daki kaçışlı biçim, `c:/users/...`); yalnız tam klasör eşleşir (`...\\x2` başkasının); en uzun önce; çalıştırma başına bir kez derlenir. Göreli `--work-dir` mutlak yola çevrilir (`.` sıradan metni bozmaz).
- **Önce temizle, sonra kes** (`clean_tail`): kesilen bir yolun kalan parçası artık sızmıyor; stderr kuyrukları da (`claude`, `orkestra run/apply`).
- **Yazılan her dosya bütünüyle temizlenir** (`write_results`): `--resume` ile geri yazılan eski kayıtlar ve meta dahil.
- **Ölçülmemiş `permission_denials` bilinmiyor (None), 0 değil:** 13c'nin mod A deneme dosyası bu alandan önce yazıldı; D-080/PROGRESS'teki kanıt yalnız mod B'ye dayandırıldı.
- **Eski `claude-stderr.txt`** yeniden denenen koşuda silinir (devam sonrası yanlış ipucu vermesin).
- **pytest-asyncio uyarısı** eklentiyi kapatarak değil, değerlendirme ini'sine `asyncio_default_fixture_loop_scope = function` yazarak susturulur: ileride async gizli test de çalışır.
- **Testler:** 1429 → 1437 (+8).

## D-082 – Faz 13d hazırlığı: mod D (devretme istenir) ve Windows araç izinleri (2026-11-15, Faz 13d)
**Bağlam:** 13c'de mod B küçük görevlerde hiç devretmedi. Kullanıcı devretmenin kendisinin de ölçülmesini istedi ("mod B'yi de yap").
**Karar:**
- **Mod D – Claude + Orkestra, devretme istenir:** B gibi (skill + `orkestra` izni) ama ipucu "işi Orkestra işçisine ver, yalnız Orkestra yapamazsa (işçi yok ya da iki kez başarısız) kendin yap" der. `--mode all` planın üç modu (A, B, C) olarak kalır; D `--mode d` ile ayrıca seçilir. Rapor A − D Claude token farkını ve D'deki `stats` tahminini de verir.
- **Gerçek deneme (01, 09; `bench/results/trial/2026-11-15-0418.*`):** 2/2 geçti; Claude **gerçekten devretti** (görev başına 1 işçi koşusu, yerel 14b ilk denemede, $0), sonucu kendi yazdığı denetimle doğruladı ve uyguladı. Ama Claude'un harcaması arttı: görev başına ~26,5 bin Claude token'ı (A: ~7,2 bin; ~3,7 kat), 14–16 tur, 53–68 sn (A: 18–23 sn), API karşılığı $0.31–0.33 (A: $0.09). **Küçük görevlerde devretmek şefe kazandırmıyor, pahalıya geliyor** (görev dosyası, denetim betiği, sonucu okuma ek iş). Kazancın hangi görev büyüklüğünde başladığını tam koşu gösterecek.
- **Windows araç izinleri:** D'de 6 araç çağrısı reddedildi: Claude Windows'ta komutları PowerShell aracıyla ve `cd … && …` gibi zincirlerle çalıştırıyor, izin listesinde yalnız Bash kalıpları vardı. Her ret tur ve token harcatıyor (yukarıdaki maliyetin bir kısmı). Artık bütün Claude modları aynı komutları (python, pytest, git; B/D'de orkestra) **iki kabukta** ve birkaç salt okunur komutu kullanabilir (liste D-083'te düzeltildi: `echo`/`Write-Output` çıkarıldı, PowerShell kısaltmaları eklendi). 13c'nin A/B denemeleri eski listeyle koşuldu (karşılaştırmada not).
- **Testler:** 1437 → 1441 (+4).

## D-083 – Faz 13d hazırlığı kod denetimi düzeltmeleri (2026-11-15, Faz 13d)
`/code-review` (PR #28): 9 bulgu, hepsi düzeltildi; önce 7 kırmızı test.
- **Mod listesi:** `--mode` artık `all`, tek mod ya da liste (`a,d`, `ad`) alır; A ile D aynı dosyada koşulabilir, rapordaki A − D farkı gerçek koşuda da çıkar (önce D yalnız tek başına koşulabildiği için çıkamıyordu). Bilinmeyen mod kod 2.
- **İzinler:** PowerShell'de yazılan kısaltmalar (`cd`, `ls`, `dir`, `cat`, `type`, `pwd`, `Get-Location`) eklendi; yönlendirmeyle dosya yazabilen `echo` ve `Write-Output` **çıkarıldı** (düzenleme Edit/Write ile ölçülsün; D-082'deki "salt okunur" iddiası düzeltildi).
- **Sonuç dosyası hangi izin listesiyle ölçüldüğünü yazar** (`meta.claude_tools`, `meta.orkestra_tools`); 13c/13d deneme dosyalarına eski (yalnız Bash) liste ve not eklendi: yeni koşularla doğrudan karşılaştırılmamalı.
- **Her mod tek yerde** (`Mode`: etiket, Claude başlatır mı, skill, ipucu, `all`'a dahil mi); `PLANNED_MODES`, `CHIEF_MODES`, `SKILL_MODES` ondan türer, `--disable-slash-commands` skill'siz modlara.
- Mesajlar ve belgeler D'yi de anıyor: "claude gerekli: a, b, d"; `--ollama-model-2` yardımı "B ve D"; README'de A, B ve D aynı yalıtım ve izinlerle.
- **Testler:** 1441 → 1448 (+7; izin testi tam listeyi denetliyor).

## D-084 – Faz 13f: kota bitince kesintisiz devam (2026-11-17, Faz 13f)
**Bağlam:** kullanıcının asıl hedefi süreklilik: bir AI'nın kotası bitince iş kendiliğinden başka birinde sürsün. Önceden ajan sıfır olmayan kodla çıkınca `ProviderBadOutput` → aynı komutta sıradaki aday vardı, ama kota tanınmıyordu: sağlayıcı duraklatılmıyor, sonraki her görev önce yine onu deniyordu (her seferinde bir boşa ajan koşusu).
**Karar:**
- **`ProviderQuotaExhausted(message, pause_s)`** (`ProviderError` alt sınıfı, `ProviderRateLimit` değil: yeniden denenmez). `retry.classify` → `SKIP_PROVIDER`: iş aynı komutta, kademe atlamadan sıradaki sağlayıcıya geçer; zarfın `failovers` kaydında `error: ProviderQuotaExhausted` ve sağlayıcının kendi cümlesi.
- **Desenler tek yerde, `providers/quota.py`** (testli tablo). Planda "ajan türüne göre" deniyordu; tek liste seçildi: `generic` her ajanı sarabilir ve desenler birbirini dışlamıyor. **Sert** (kota/kullanım sınırı: `usage limit`, `insufficient_quota`, `RESOURCE_EXHAUSTED`, `quota … exceeded/exhausted/reset`, `exceeded/exhausted … quota/capacity`, `free-models-per-day`) ve **yumuşak** (`rate limit exceeded`, `too many requests`, `HTTP/status 429`). Çıplak sayı (`429 files`) ve alt çizgili adlar (`test_quota_exceeded.py`) sayılmaz.
- **Yalnız başarısız koşuda bakılır** (13b dersi): ajan sıfır olmayan kodla çıktıysa ya da son mesajı boşsa; stdout ve stderr'in **son 4000 karakteri** (uzun dökümdeki ajanın kendi işi sayılmasın) ve agy'de kendi günlüğünün son 20 satırı. Kotadan söz eden başarılı cevap hiçbir şeyi duraklatmaz. Tanınmayan mesaj eskisi gibi `ProviderBadOutput` → sıradaki; yalnız duraklatma olmaz.
- **Süre:** mesajdaki yenilenme zamanı (`try again in 2 days 3 hours`, Go süresi `reset after 2h30m15s`, JSON `resets_in_seconds`, Google `retryDelay`, API'de `retry-after`); yoksa sert için sağlayıcının **`quota_pause_s`**'i (yeni alan, `ProviderBase`'te, varsayılan 3600; planda tek `quota_pause_s` deniyordu, sağlayıcı başına seçildi çünkü agy günlük, Codex 5 saatlik/haftalık sınırla çalışıyor), yumuşak için 5 dk. Devre kesicide en az 1 dk, en çok 7 gün. Onay hash'ine girmez (işletimsel ayar).
- **API'ler de (planın ötesinde, aynı hedef):** OpenAI uyumlu ve Ollama'nın HTTP 429'unda gövde sert kota diyorsa (OpenRouter günlük ücretsiz istekler, OpenAI `insufficient_quota`, Ollama bulut saatlik/haftalık sınır) `ProviderQuotaExhausted`; diğer 429'lar eskisi gibi `ProviderRateLimit` (kısa bekleme ve yeniden deneme).
- **Duraklatmanın nedeni:** migration 4 `health.open_reason` (`quota` | `auth` | `errors`). `status` ("agy (kota, açılış 14:30)"), `providers list` (+ `--json` `health.reason`), `doctor` (uyarı + `providers enable` ipucu), `--dry-run` (eleme kodu `quota_paused`) kotayı ayrıca gösterir; yenilenme başka gündeyse tarihle (`health.until_text`). `providers enable` duraklatmayı kaldırır (eskisi gibi).
- **Batch ve kuyruk:** ek kod gerekmedi: duraklatma `state.db`'de; sonraki görevler (aynı batch, sonraki kuyruk öğeleri) router'da ve koşu döngüsünde onu atlar. Yuva bekleyen görev kota duraklatmasını görürse `QuotaPaused` kaydıyla sağlayıcıyı bu koşuda atlar. `batch --notify` ve `queue run --notify` sayılara tek satır ekler: kota yüzünden duraklatılan sağlayıcılar ve açılış saatleri (iş içeriği yok).
- **Ölçüm (ağsız, `tests/integration/test_continuity_cli.py`):** 10 görevlik batch, sahte ajan 4. görevde Codex'in kota mesajıyla çıkıyor → 10/10 bitti (1–3 ajan, 4–10 Ollama), ajan 4 kez başlatıldı ve sonra hiç, 4. görevin zarfında tek `ProviderQuotaExhausted` failover'ı, 5–10'da failover yok, duraklatma mesajdaki 5 sa 19 dk'ya göre; tüm batch ~0,5 sn (geçişin bedeli bir başarısız ajan koşusu, bekleme yok). README "When an AI runs out" / "Bir AI'nın kotası bitince" bölümü; skill'e not.
- `go_seconds` `cli_agent.py`'den `quota.py`'ye taşındı (döngüsel içe aktarma olmasın; `cli_agent.go_seconds` adı duruyor).
- **Testler:** 1448 → 1487 (+39: kota tablosu, sağlık, ajan, API, uçtan uca süreklilik; şema sürümü ve `providers list --json` beklentileri 4'e/`reason`'a güncellendi).

## D-085 – Faz 13f kod denetimi düzeltmeleri (2026-11-17, Faz 13f)
`/code-review` (PR #29): 10 bulgu, hepsi düzeltildi; önce 9 kırmızı test.
- **Ajanın kısa istek sınırı kota değil:** yumuşak eşleşme (`429 Too Many Requests`, `rate limit exceeded`) ajanda artık `ProviderRateLimit` (yeni `agent.error.rate_limited` metni); devre kesici eskisi gibi art arda 3'te 5 dk açar, "kota bitti" denmez, bildirime girmez. D-084'teki "yumuşak için 5 dk duraklatma" kaldırıldı (`RATE_PAUSE_S` yok).
- **Ajanın kendi işi sayılmaz:** kota mesajı stdout'un son 5, stderr'in son 10, agy günlüğünün son 20 satırında aranır (önce son 4000 karakter); dosyalar sondan okunur (`_tail`, 16 KB), uzun döküm iki kez baştan okunmaz.
- **Tek modelin kotası** (`model_only`: OpenRouter `free-models-per-day`, Gemini `RESOURCE_EXHAUSTED`, Google "quota metric") yalnız o modeli atlar (`NEXT`) ve devreyi açmaz: aynı sağlayıcının ücretli/diğer modelleri çalışmaya devam eder.
- **API gövdesi bütünüyle okunur** (anahtar maskelenir, 300 karaktere kesilmez) ve süre desenleri Python repr'deki tek tırnağı da tanır (`'retryDelay': '34s'`); `try again in 2h30m15s` büyük harfle de okunur.
- **Mesajdaki yenilenme zamanı `retry-after`'dan önce gelir** ("3 gün" bir dakikalık başlıkla kısalmaz).
- **Süre `timedelta`'dan önce sınırlanır:** `inf`/`nan`/çok büyük değer çökertmez (`nan` → 7 gün).
- **Bildirim yalnız o koşuda biten kotayı** söyler: batch'te zarflardaki `ProviderQuotaExhausted` failover'larından (`batch.quota_pauses`; state.db okunamazsa saatsiz adlar), kuyrukta başlangıç ve bitiş anlık görüntüsünün farkından (`health.quota_snapshot` / `new_quota_pauses`). `notify` artık veritabanı açmıyor.
- **Tek yerden gösterim:** `health.pause_kind(reason)` (`quota_paused` | `circuit_open`) ve `health.until_text` `providers list`, `doctor`, router ve koşu döngüsünde ortak; `doctor` verisinde her duraklatmada `reason` ve `hint`. `quota_paused` tek sorgu.
- **Testler:** 1487 → 1496 (+9).

## D-086 – Faz 13h: token haritası (2026-11-17, Faz 13h)
**Bağlam:** 13c/13d'de Claude'un token'ının çoğunun yazmaya değil bağlama gittiği tahmin edilmişti; neyin kısılacağı tahminle değil veriyle seçilsin. Kota harcamaz.
**Karar:**
- **`orkestra tokens [--session id | --since 7d] [--project yol] [--top n] [--json]`** (`chief/tokens.py`): Claude Code'un oturum dökümlerini okur (`$CLAUDE_CONFIG_DIR` ya da `~/.claude`/`projects/<harf-rakam dışı '-' olan yol>`); varsayılan en son oturum. Orkestra config'i gerekmez (yoksa varsayılan ağırlıklar).
- **Döküm biçimi (Claude Code 2.1.312–2.1.325'te görüldüğü gibi):** her `assistant` mesajı bir istek; aynı `message.id` içerik bloğu başına tekrar yazılır, `usage` bir kez (son satırınki) sayılır. Araç sonuçları `user` girdilerinde `tool_result`; alt ajanlar `<oturum>/subagents/*.jsonl` (ana bağlamdan ayrı sayılır); `system`/`compact_boundary` sıkıştırma. Bilinmeyen girdi türleri atlanır, okunamayan satırlar sayılır, sürümler raporda.
- **Maliyet modeli:** bir öğe sonraki istekte önbelleğe yazılır, sonra sıkıştırmaya ya da oturum sonuna kadar her istekte okunur: `token × cache_write + token × cache_read × yeniden_okuma`. Ağırlıklar `tokens.weights` (girdi 1, çıktı 5, yazma 1,25, okuma 0,1 — API fiyat oranları; abonelik sınırının ağırlığı bilinmediği için ham token da gösterilir).
- **Planın ötesinde, ilk gerçek raporun gösterdiği:** (1) planın "okuma / komut / yazma / düşünme" bölmesi maliyetin ancak ~%38'ini açıklıyordu; **Claude'un sonradan geri giden cevapları** (metin + araç girdisi; düşünme hariç), **sonraki mesajlar ve ekler** (hatırlatmalar), **sabit başlangıç** (ilk isteğin bağlamı: sistem istemi, araçlar, CLAUDE.md × her istek) ve **önbellek kaçırma** (önbellekten okunan, önceki isteğin bağlamından ≥ 2000 token az; ek bedel fark × (yazma − okuma)) ayrı kategoriler oldu. (2) `karakter/4` tahmini ölçülen yeni bağlamın 1,3–1,9 katı altında kalıyordu; boyutlar **oturum başına ölçülen yeni bağlama ölçeklenir** (`input + cache_write`, başlangıç ve kaçırmalar hariç; 0,25–4 arası; katsayı rapordadır, `calibrate=False` ham tahmin). Sonuç: atanamayan "geri kalan" %62'den %4'e indi.
- **Gizlilik:** etiketlerde dosyalar projeye göre göreli, proje dışındakiler yalnız adıyla; komutlarda proje `.`, ev klasörü `~` (her eğik çizgi, büyük/küçük harf); oturum kimliği ve sürüm dışında yol yok. README örneği bu deponun kendi 12 oturumundan.
- **İlk bulgu (README'de):** bu projenin 12 oturumunda (2.793 istek) ağırlıklı maliyetin ~%80'i bağlamın yeniden okunması: komut çıktısı %20, sonraki mesajlar/hatırlatmalar %18, yazma %14, Claude'un çıktısı %14, sabit başlangıç %11, cevapların yeniden okunması %11, okuma %7. En pahalı tek çağrı 650 satırlık bir plan dosyasının 269 istek boyunca taşınması (10 satır olsaydı ~%98 daha ucuz). 13i (bağlam süzgeci) ve 13j (kısa oturum) bu yüzden doğru kaldıraçlar.
- **Testler:** 1496 → 1514 (+18; sahte dökümlerle, ağsız).

## D-087 – Faz 13h kod denetimi düzeltmeleri (2026-11-17, Faz 13h)
`/code-review` (PR #30): 10 bulgu, hepsi düzeltildi; önce 10 kırmızı test.
- **Gizlilik:** `scrub` Windows yolunu Git Bash (`/c/Users/...`) ve WSL (`/mnt/c/Users/...`) yazımlarıyla da tanır; bu deponun ajanları komutları çoğunlukla böyle yazıyor, etiketlerde kullanıcı adı kalıyordu.
- **Sıkıştırma çağrıdan hemen sonraysa** sonuç hiç gönderilmemiş sayılır (önce bir sonraki sıkıştırmaya kadar yeniden okunuyordu).
- **Claude Code'un kendi yer tutucuları** (`<synthetic>` model, sıfır `usage`: API hatası, kesinti) istek sayılmaz; sahte önbellek kaçırması ve büyüme çizgisindeki 0 kalktı.
- **Görsel** (`image` bloğu) base64 uzunluğuyla değil sabit ~1600 token sayılır.
- **Ölçekleme:** ilk istekte yalnız yazılan (`input + cache_write`) çıkarılır; başka oturumun yazdığı önbellekten okunan sistem istemi artık ölçeği düşürmüyor. Her sıkıştırmadan sonraki yeniden başlangıç (özet) da çıkarılır.
- **Grep/Glob** `path` verilse de desenleriyle etiketlenir.
- **Eski biçimdeki alt ajanlar** (ana dökümde `isSidechain`) ana bağlama karışmaz, alt ajan olarak sayılır.
- **Ayarlar `--project`'in config'inden**; config yüklenemezse varsayılan ağırlıklar ve bir uyarı (komut config'siz de çalışır).
- **Belirsiz `--session` öneki** kullanım hatası ve eşleşen kimlikler; tam eşleşme önce gelir.
- Temizlik: bir isteğin mesaj ve ekleri tek öğe; `Call.raw()` kullanılmayan parametresiz; "10 satır olsaydı" yalnız sonucu küçültür (Edit/Write'ın gönderdiği girdi kalır).
- Gerçek raporda atanamayan pay %0'a indi; README örneği yenilendi (yeniden okuma ~%85).
- **Testler:** 1514 → 1524 (+10).

## D-088 – Faz 13i ikiye bölündü; 13i-a: `orkestra exec` (2026-11-17, Faz 13i-a)
**Bağlam:** 13h, maliyetin ~%85'inin bağlamın yeniden okunması olduğunu, en büyük payın komut çıktısında (%23) olduğunu gösterdi. 13i'nin planı (exec + read + find + proje fihristi) tek PR için büyük; önceki fazlardaki gibi bölündü: **13i-a** `exec`, kural tabanlı ayrıştırıcılar, model özeti ve skill kuralı; **13i-b** `read`, `find` ve proje fihristi.
**Karar:**
- **`orkestra exec [--max-lines n] [--no-model] [--timeout s] [--json] -- <komut>`** (`chief/execute.py`): kabuksuz (AGENTS kuralı; program `shutil.which` ile, Windows'ta `.cmd` de), stdout ve stderr birlikte, zaman aşımında süreç ağacı durdurulur. Tam çıktı anahtarlar maskelenerek `runs/<id>/output.log` + `exec.json` (koşu kimliği biçimi aynı, `gc` temizler; `runs` tablosuna satır yazılmaz). **Çıkış kodu komutun kendi kodu** (Claude başarısızlığı görür); program yok 127, zaman aşımı 124 — kabukların kodları.
- **Kural önce, model sonra** (`chief/outparse.py`): pytest (her `FAILED`/`ERROR` satırı, hata bölümündeki son `dosya:satır: Hata` ile; başarısız test adları **hiç kesilmez**), ruff (concise, tam biçim, `format --check`), pyright, derleyiciler/tip denetleyiciler (`dosya:satır: error`, tsc, rust `-->`). Diğer bulgular 30'da kesilir, kalanı sayılır. Yollar çalışılan klasöre göre. Örnek çıktılar gerçek araçlardan (`tests/fixtures/outputs`, yollar `/work/proj`).
- **Bilinmeyen uzun çıktı** `exec.tier`'deki (varsayılan 1) bir **sohbet modeline** özetletilir (son 400 satır / 40 bin karakter; sistem istemi: en çok 12 satır, her hata `dosya:satır` ile, adlar aynen, tavsiye ve tahmin yok). `query_chief_model`'e `agents=False` eklendi: düz metin özeti için kod ajanı başlatılmaz (elle denemede router agy'yi seçmişti). Sohbet modeli yoksa elenme nedeni (ör. "ollama: bağlanılamıyor") tek satır not olarak yazılır ve ilk 10 + son 30 satır gösterilir; `--no-model` ve `exec.model: false` da öyle. Orkestra config'i yoksa `exec` yine çalışır (modelsiz).
- **Config:** `exec: {max_lines: 40, tier: 1, model: true, timeout_s: 1800}`.
- **Skill:** testleri, linter'ı ve derlemeyi `orkestra exec` ile çalıştır, ayrıntı gerekirse işaretçideki satırları oku; "Asla yapma"ya kural. Skill denetleyicisi click'in `--` (seçeneklerin sonu) kuralını öğrendi.
- **Sınırlar:** kabuk yok (boru, `&&`, yönlendirme çalışmaz); özet kalitesi modele bağlı, ama kural tabanlı çıktılarda model yok. Kazancın ölçümü 13g'de (geri dönüp günlüğü okuma sayısı ayrıca).
- **Testler:** 1524 → 1551 (+27).

## D-089 – Faz 13i-a kod denetimi düzeltmeleri (2026-11-17, Faz 13i-a)
`/code-review` (PR #31): 10 bulgu, hepsi düzeltildi; önce 9 kırmızı test.
- **Süreç:** zaman aşımında süreç ağacı durdurulur ve çıktı en çok `KILL_GRACE_S` beklenir (çıktı borusunu tutan başıboş süreç `exec`'i sonsuza dek bekletiyordu; `command` doğrulayıcısındaki gibi). Komut kendisi bitmiş ama borusu tutuluyorsa kendi çıkış kodu döner. Ctrl+C ya da başka bir hata süreç ağacını durdurur. Bulunan ama başlatılamayan program (çalıştırma izni yok, `.txt`) traceback değil **çıkış kodu 126**.
- **Birden çok araç tek çıktıda** (`make check`, `pre-commit`): tanınan her aracın bulguları birleşir (`ruff+pyright`, başlıklar ` · ` ile); önce yalnız ilk eşleşen kalıyordu.
- **Derleyici biçimi** yalnız başka hiçbir araç tanınmadığında ve en az bir **hata** satırı varsa sayılır: tek bir uyarı satırı `cargo test`'in başarısız testlerini model özetinden saklıyordu.
- **pytest işaretçileri** hata bölümüne adıyla **ve dosyasıyla**, sırayla eşlenir: farklı dosyalardaki aynı adlı testler kendi dosyasını gösterir; `ERROR at setup/teardown of …` bölümleri de eşlenir.
- **"Kısa" karakterle de sınırlı** (`max_lines × 300`): tek satırlık 2 MB çıktı bağlama olduğu gibi girmiyor; ilk/son satırlarda her satır 300 karakterde kesilir.
- **İlk/son satırlar `--max-lines`'a göre** (dörtte biri baştan, kalanı sondan).
- **Bozuk config** "config'i yok" diye değil nedeniyle yazılır; **anahtar maskeleme config'siz de**: adı anahtar gibi görünen ortam değişkenlerinin değerleri (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*AUTH*` …; `security.redact.secret_env_values`) günlükte ve cevapta maskelenir.
- Hiç gösterilmeyen `exec.kind.model` / `exec.kind.digest` anahtarları kaldırıldı.
- **Testler:** 1551 → 1560 (+9).

## D-090 – Faz 13i-b: `orkestra read`, `orkestra find`, fihrist hook'u (2026-11-17, Faz 13i-b)
**Karar:**
- **`read DOSYALAR... SORU`** (`chief/reader.py`): dosyalar görev bağlamı gibi okunur (`.orkestraignore` ve ikili dosyalar gönderilmez, listelenir; `security.max_context_bytes`), numaralı satırlarla bir **sohbet işçisine** (`read.tier`, varsayılan 1; `agents=False`). Sistem istemi: en çok 8 satır, her ifade `yol:satır` ile, cevap yoksa tek satır. **İşaretçiler denetlenir** (`chief/pointers.py`): satır aralıkta mı, yol verilen dosyalardan biri mi (yalnız dosya adı verildiyse tek eşleşme varsa); geçerlinin gösterdiği satır yanına yazılır, geçersiz olan "güvenme" diye işaretlenir. Uzantısı harfle başlamayan (`3.12:1`) ve saat gibi ifadeler işaretçi sayılmaz. Cevap önbelleği (soru + dosya içerikleri; dosya değişince yeniden sorulur; `--no-cache`).
- **`find DESEN`** (`chief/finder.py`): planda "`find "<soru>"` + işçi özeti" yazıyordu; doğal dili arama desenine çevirmek ayrı bir model adımı ve hata kaynağı olacağı için **arama modelsiz** yapıldı (metin ya da `--regex`, büyük/küçük harfe duyarlı, `map`'in dosya yürüyüşüyle: `.gitignore`, `.orkestraignore`, ikili, Orkestra klasörleri dışında; `--glob`). `find.max_hits`'e (40) kadar `dosya:satır: metin`; fazlası dosya başına sayı, fihrist özeti ve ilk 3 sonuç. Soru gerekiyorsa `--ask`: sonuçlar ±2 satırla işçiye, işaretçiler denetlenir. Sonuç yoksa kod 1 (grep gibi). Satırlar anahtar maskeleriyle.
- **Proje fihristi** yeni bir yapı değil, `map`'in dosya başına özetleri (`index.json`; `repomap.read_index`). Güncel tutmak için **`orkestra map --install-hook`**: post-commit bloğu değişen (silinmemiş) dosyaları **arka planda** `orkestra map`'e verir, commit'i yavaşlatmaz. `map` konumsal yol aldığı için `map install-hook` alt komutu yerine bayrak. `handoff install-hook`'un kodu `install_block`'a genelleştirildi (hook adı, blok, işaret).
- **Skill:** büyük dosyayı yalnız bir soru için okuma, `read`/`find` kullan; fihrist hook'unu kullanıcıya öner.
- **Testler:** 1560 → 1575 (+15).

## D-091 – Faz 13i-b kod denetimi düzeltmeleri (2026-11-17, Faz 13i-b)
`/code-review` (PR #32): 10 bulgu, hepsi düzeltildi; önce 10 kırmızı test.
- **Gizlilik:** `find --ask` ve `read`'in işaretçi satırları da maskelenir (işçi maskeli bir anahtarı gösterirse satırı açık metin dönüyordu). Klasör dışındaki dosya işçiye mutlak yolla değil göreli yolla (`../other/x.py`; başka sürücüdeyse yalnız adıyla) gider; onun işaretçileri de denetlenir.
- **Fihrist hook'u Python'a taşındı:** blok yalnız `orkestra map --after-commit`'i arka planda başlatır. `after_commit` değişen dosyaları `git diff-tree -z -r -m --first-parent --root --diff-filter=d HEAD` ile alır (Türkçe/alışılmadık adlar tırnaksız, ilk commit ve merge de), bekleyen listeye ekler; **kilidi alan tek koşu** listeyi parti parti haritalar, diğerleri hemen çıkar (rebase'de 15 eşzamanlı `map` birbirinin fihristini eziyordu); sahibi ölmüş kilit devralınır; o arada silinen dosyalar atlanır.
- **`read`'de dosya kendi bloğunu kapatamaz:** `numbered` yolu kaçışlar ve içerideki `</file>`'ı `<\/file>` yapar (D-036 gibi).
- **`find` alt klasörden:** yollar bulunulan klasöre göre (`../README.md`), aynı adlı iki dosya karışmaz.
- **Bozuk config'te `find` durur** (kod 2, nedeniyle): ignore dosyası ve anahtarlar bilinmeden aramak saklananı gösterebilirdi.
- **Satır numaraları editörlerle aynı:** yalnız satır sonunda bölünür (`splitlines` form feed vb. yüzünden sonraki satırları kaydırıyordu); `find` BOM'u atar.
- **Önbellek anahtarı kademedeki modelleri içerir:** model değişince eski modelin cevabı dönmez.
- **Verim:** `find` dosya metinlerini yalnız `--ask`'te tutar, sonuçları dosya başına toplar, en çok 5000 sonuçta durur (`truncated`), 2 MB'tan büyük dosyaları atlar.
- **Testler:** 1575 → 1585 (+10).

## D-092 – Faz 13j: kısa oturum disiplini (2026-11-17, Faz 13j)
**Karar:**
- **`handoff to claude` için yeni kod gerekmedi:** `handoff to` aynı şefe devri zaten yapıyordu (kayıtta `from = to`); test eklendi. Claude Code içinde ikinci yol `/clear` + `orkestra handoff show --brief` (oturum açık kalır, bağlam boşalır).
- **Eşik önerisi** (`tokens.handoff_hint`): bağlam = en yeni dökümün son isteğinin bağlamı; yeni başlangıç = ilk isteğin bağlamı (sistem istemi, araçlar, CLAUDE.md) + ~3.000 token devir özeti; kazanç = (bağlam − başlangıç) × `cache_read` ağırlığı × 100 istek (sonraki her istek o kadar az okur). Kalan iş bilinmediği için "100 istek başına" verilir. Eşik `handoff.suggest_at_tokens` (varsayılan 120.000; bu projenin oturumları 47 bin ile başlayıp 400 bin+'ya çıkıyordu).
- **Nerede:** `status`'ta yeni `session` bölümü (yalnız son 6 saatte değişmiş döküm = süren oturum; eşik geçilince tek satır, JSON'da her zaman), `tokens`'ta aynı satır ve `handoff_hint`. Döküm proje klasöründen, yoksa git kökünden aranır.
- **Skill:** faz/alt görev sonunda `status`'ta bu satır varsa devir dosyasını güncelle, commit et ve yeni oturum öner; yarım işin ortasında önerme.
- **Testler:** `CLAUDE_CONFIG_DIR` artık bütün testlerde geçici klasör (gerçek dökümler okunmaz). 1585 → 1596 (+11).
- **İlk gerçek değer:** bu geliştirme oturumunun kendisi ~636 bin token bağlamdaydı; araç yeni oturumun her 100 istekte ~5,9 milyon ağırlıklı token kazandıracağını hesapladı. Ölçüm 13g'nin kısa oturumlu kolunda.

## D-093 – Faz 13j kod denetimi düzeltmeleri (2026-11-17, Faz 13j)
`/code-review` (PR #33): 10 bulgu, hepsi düzeltildi; önce 8 kırmızı test.
- **`status` hiç çökmez:** `session` bölümü en iyi çaba; döküm okunamazsa (silinmiş, izin yok) bölüm yazılmaz, `status` sürer.
- **Saat enjekte:** etkinlik penceresi `ctx.now` ile (`tokens.active`), gerçek saatle değil.
- **Hızlı:** `status` dökümü baştan sona ayrıştırmaz; `tokens.request_sizes` yalnız `assistant` + `usage` satırlarını okur (alt ajanlar, araç çağrıları yok). Git köküne yalnız bulunulan klasörde döküm yoksa sorulur.
- **Devam ettirilen oturum** (`--resume`): yeni başlangıç, projenin son 10 dökümünün en küçük ilk isteğinden (`tokens.fresh_start`); devam ettirilen dökümün ilk isteği eski geçmişi taşıdığı için kazancı olduğundan az gösteriyordu.
- **Kazanç yoksa öneri yok** (`over` = eşik geçildi **ve** kazanç > 0).
- **`tokens` yalnız süren oturum için** ipucu verir (son 6 saat); kapanmış bir oturuma "yeni oturuma geç" denmez.
- **Klasör adı çözülmemiş yoldan** (Claude Code'un kendisi gibi): eşlenmiş sürücü / junction'da döküm bulunur.
- **Skill** dile bağlı metin satırına değil `status --json` → `sections.session.over`'a bakar.
- Kullanılmayan `tokens.settings` yerine tek giriş `tokens.load`.
- **Testler:** 1596 → 1603 (+7).

## D-094 – Faz 13k: kota tahmini ve otomatik devir hazırlığı (2026-11-18, Faz 13k)
**Karar:**
- **Tahmin** (`state/forecast.py`): son `forecast.window_s` (3600) saniyenin hızı sınıra karşı. Bilinen sınır = `budget` (gece yarısı sıfırlanır; hız sınıra gece yarısından sonra varacaksa süre yok). Öğrenilen sınır = yazılmamış `daily_runs`/`daily_requests` için **migration 5 `quota_events`**'in son `learn_events` (5) olayının sıfır olmayan ortancası (30 gün); her biten kota (`model_only` hariç) pencerenin başından o ana kadarki `actual` kullanımı yazar. Pencere = yerel gece yarısı ya da önceki duraklatmanın bittiği an (hangisi sonraysa), böylece 5 saatlik kotalar da kabaca öğrenilir. Token öğrenilmez (ajanlarda tahmini).
- **Azalıyor** = `warn_within_s` (3600) içinde bitecek ya da sınırın `low_share`'i (0,1) veya azı kaldı. `status` (`forecast` bölümü; JSON'da her zaman), `doctor` (uyarı; duraklatılmışsa yalnız duraklatma), `batch/queue --notify` (tek satır), `statusline`.
- **Router (D-031'e istisna):** kotası azalan sağlayıcı **kademesinde sona** alınır (kademe kuralı önce; skor ve priority'den önce); hiçbir şey elenmez. `--dry-run --json`'da `quota_low`. Kapatmak: `forecast.enabled: false`. Bütçeyi saniyeler içinde tüketen testte (`test_budget_exhausted_moves_to_next_provider`) bu yüzden tahmin kapatıldı: test bütçe süzgecini sınıyor.
- **Şefin kotası — sapma:** plan "durum satırı devir özetini kendiliğinden günceller" diyordu. Orkestra şefin ne yaptığını bilmez; git durumu ve uygulanmamış koşular zaten `handoff to` anında brief'e canlı giriyor. Bunun yerine: `orkestra statusline` Claude Code'un `rate_limits`'ini (`five_hour`, `seven_day`) okur, satır basar, okumaları `~/.orkestra/chief_quota.json`'a yazar; pencere `handoff.prepare_at_percent`'i (85) geçince ya da `warn_within_s` içinde bitecekse `orkestra statusline hook` (`UserPromptSubmit` + `PostToolUse`) **şefin bağlamına pencere başına bir kez** "devir dosyasını güncelle, commit et, kullanıcıya `handoff to <sonraki>` de" notu ekler. Özeti şef yazar, kullanıcı yalnız `handoff to agy` der.
- **Ayar dosyasına yazılmaz:** `orkestra statusline config` settings.json parçasını basar; kullanıcının Claude Code ayarlarını kendimiz değiştirmiyoruz (mevcut statusLine'ı ezme riski).
- **Hızlı giriş:** konsol betiği `orkestra.cli:app` → `orkestra.entry:main` (D-002'deki `app` aynen duruyor). Tam olarak `statusline` ve `statusline hook` bütün CLI'yi (openai SDK, doctor) yüklemeden çalışır: ~1,35 sn → ~0,3 sn; `PostToolUse` her araç çağrısında koştuğu için gerekli. `_safe_streams` `console.safe_streams`'e taşındı (iki yol da kullanıyor). Hiçbiri hata vermez.
- **Testler:** 1603 → 1672 (+69).

## D-095 – Faz 13k kod denetimi düzeltmeleri (2026-11-18, Faz 13k)
`/code-review` (PR #34): 9 bulgu, hepsi düzeltildi; önce 10 kırmızı test.
- **Bir kez sorma yarışsız:** kancanın işareti artık `chief_quota.json`'da değil, `~/.orkestra/chief_quota.prompted/<pencere>-<anahtar özeti>` dosyasında; `O_CREAT|O_EXCL` ile atomik (aynı anda iki kanca → tek not). Durum satırı her mesajda yalnız okumaları yazar, işarete dokunmaz. İki durum satırının yarışı en çok bir okumayı kaybettirir.
- **`resets_at` yoksa** pencere anahtarı okumaların başladığı an (`started`; kullanım düşünce yeni pencere); eskiden sabit `-` idi ve bir daha hiç sorulmuyordu.
- **"Bugün" bütçeyle aynı:** bilinen sınırın kullanımı `budget.used(..., reservations=False)` (satırın `day`'i); router zaten hesapladığını `today=` ile veriyor.
- **Hiç çökmez:** `statusline`/`hook`/`status` `RuntimeError` (ev klasörü yok), `ValueError`, `TypeError`, `sqlite3.Error` dahil yutar; ev klasörü yoksa okuma kaydedilmez.
- **Taşma yok:** pencere sıfırlanması sayıyla karşılaştırılır (`eta >= (resets - last_at)`), `datetime + timedelta` değil.
- **Router ucuzladı:** duraklatılmış sağlayıcıya tahmin yapılmaz; kullanım tek sorguda, her satır bir kez (`forecast.usage_since`, birden çok başlangıç).
- **Duraklatma kuralı tek yerde:** `health.paused_names`; `forecast.low_now(skip=...)` kendi SQL'ini yazmaz.
- **Öğrenilen sınır:** sıfırlar SQL'de `LIMIT`'ten önce elenir; 30 gün sınırı `datetime` ile karşılaştırılır.
- **i18n:** `Claude`, `5h`/`7d` `t()` ile (`statusline.claude`, `limits.window.*`; tr `5sa`/`7g`).
- **Testler:** 1672 → 1682 (+10).

## D-096 – Faz 13l: işe göre model ve bilgisayar yükü (2026-11-18, Faz 13l)
**Karar:**
- **`routing.by_kind.<iş>.prefer`** (desen listesi: sağlayıcı, `sağlayıcı/model`, glob). İş türleri sabit: `summary` (exec), `read` (read, find --ask), `map`, `review`, `plan`, görev türleri `ask`/`edit`; bilinmeyen tür config hatası. Router sırası: kademe → kotası azalan sona (D-094) → **tercih sırası** → skor → priority → config sırası. Kademe, bütçe, gizlilik kuralları önce; tercih kademe aşmaz. Varsayılan boş (davranış değişmez); önerilen ayarlar README'de. `--dry-run --json`'da `prefer_rank`.
- **Plandan sapma:** plan `by_kind`'da "varsayılan kademe/model" diyordu. Kademe zaten araç başına ayarlı (`exec.tier`, `read.tier`, `map.tier`, `review.tier`); ikinci bir kademe ayarı çelişki yaratırdı. `by_kind` yalnız model tercihini taşır.
- `query_chief_model(work=...)` zorunlu: her şef aracı kendi türünü verir (unutulursa pyright yakalar).
- **Tek ağır yerel model:** plan "aynı anda tek ağır yerel model (`concurrency`)" diyordu; süreç içinde zaten öyleydi, süreçler arasında değildi (batch + şefin `exec`'i + kuyruk iki model yükleyebiliyordu). Yeni ayar yerine **var olan `concurrency` yerel sağlayıcılarda makine genelinde** uygulanır: migration 6 `local_slots`, `state/slots.py` (`BEGIN IMMEDIATE`, 0,5 sn yoklama; ölü süreç ya da 6 saat → geri alınır; state.db yoksa yalnız süreç içi sınır). `runner.Slot` iki yeri birlikte tutar. `process_alive`/`current_owner` `state/process.py`'ye taşındı (kuyruk kilidi de kullanıyor; `queue.store` → `tasks.batch` → `runner` döngüsünü önlemek için).
- **`doctor` donanım önerisi** (`hardware.py`, yalnız yerel sağlayıcı varsa): RAM (psutil) ve en büyük NVIDIA GPU belleği (`nvidia-smi`, kabuksuz, 5 sn); GPU yoksa RAM'in yarısı. Kullanılabilir GB < 6 → 3b, < 10 → 7b, < 20 → 14b, < 40 → 32b, yoksa 70b; hafif işler için 1.5b-3b. Model adındaki boyut (`:14b`) önerilenden büyükse uyarı. Bu makinede 32 GB RAM + 12 GB GPU → 14b. Testlerde `nvidia-smi` hiç çalışmaz (conftest).
- **Ağır işler gece kuyruğuna:** yeni kod yok; README `queue add`'i gösteriyor.
- **Testler:** 1682 → 1717 (+35).

## D-097 – Faz 13l kod denetimi düzeltmeleri (2026-11-18, Faz 13l)
`/code-review` (PR #35): 10 bulgu, hepsi düzeltildi; önce kırmızı testler.
- **Şef araçları beklemez:** `query_chief_model` yerel yuvayı en çok `LOCAL_WAIT_S` (2 sn) bekler, sonra sıradaki adaya geçer (`exec` özeti başka terminaldeki 30 dakikalık işin arkasında kalmaz). `MachineSlots.acquire(wait_s=)` → `TimeoutError`; `runner.Slot.acquire(wait_s=)` süreç içi yeri geri verir. Görevler (batch, kuyruk) eskisi gibi bekler.
- **Kendini kilitleme yok:** bırakma meşgul veritabanında 3 kez denenir; yine olmazsa satır sürecin `_HELD` kümesinde olmadığı için aynı sürecin sonraki isteği onu geri alır.
- **Kilitli veritabanı = dolu yuva:** "database is locked/busy" sınırı atlatmaz, beklenir; yalnız açılamayan veritabanı (başka hata, `OSError`) süreç içi sınırla sürdürür.
- **Anahtar sunucu:** yuva sağlayıcı adına değil `base_url`'in host:port'una bağlı (`localhost` = `127.0.0.1`); aynı Ollama'ya iki ad (ya da iki projenin farklı adları) aynı yuvaları paylaşır. Adresi olmayan yerel sağlayıcı adıyla.
- **Yoklama ucuz:** migration yalnız ilk bağlantıda (`db.connect(migrate_schema=False)`), SQLite işi `asyncio.to_thread`'de (olay döngüsü durmaz).
- **Donanım:** kullanılabilir bellek = en büyüğü (GPU belleği, RAM'in yarısı); küçük GPU bol RAM'i gizlemez (4 GB GPU + 64 GB RAM → 32b). Model boyutu önce etiketten, yoksa addan (`hf.co/...-32B-...:Q4_K_M` → 32); `8x22b` → 176.
- **`by_kind`:** önce birebir eşleşme (`[` içeren model adı), sonra glob; hiçbir sağlayıcı/modelle eşleşmeyen desen için `doctor` uyarısı (`router.unmatched_preferences`).
- `queue/service.py` süreç yardımcılarını `state.process`'ten alır; iş türü testi kaynak metne değil AST'ye bakar.
- **Testler:** 1717 → 1727 (+10).

## D-098 – Faz 13m: toplu devretme ve çapraz denetim (2026-11-18, Faz 13m)
**Karar:**
- **Çapraz denetim:** `review.by` (yazar sağlayıcı ya da `*` → denetçi listesi, sırayla; yazar listeden düşer) ve `review.independent` (varsayılan true; `by` yoksa yazar aday dışı). `query_chief_model(providers=, exclude=)` adayları süzer; süzgeç kimseyi bırakmazsa `NoProviderAvailable` → `review` yazarla yeniden dener ve `independent: false` yazar (kesintisizlik: denetimsiz kalmaktansa işaretli öz denetim). Sağlayıcı hatası (denetçi çöktü) yazara düşmez, eskisi gibi hata. Ajanlar denetçi olabilir (zaten salt okunur koşuyordu).
- **Zarf:** `review.by` ve `review.independent` isteğe bağlı alanlar; sürüm 4 kaldı (eski zarflar yüklenir, alanlar `null`).
- **"Risk düşükse diff'i okumadan uygula"** yalnız skill sözü olarak kalmasın diye `apply --max-risk low|medium|high`: denetim yoksa, bağımsız değilse (13m öncesi denetimler dahil) ya da riski üstündeyse (`unknown` hiç geçmez) kod 2; kontrol worktree'den önce. Batch'te bu koşular `skipped` (mevcut `UsageError` → atla yolu).
- **Patrona rapor:** zarfın kendisi yerine `show RUN --report` (`--json`): yapılan (özetin ilk satırı), denetlenen, değişiklik, denetim (risk, denetçi, bağımsız mı), işaretçiler (en çok 5 bayrak `dosya:satır neden`), sıradaki tek komut. Zarf biçimi değişmedi (13d/13g ölçümleri ve var olan okuyucular bozulmasın).
- **Skill:** tek küçük işi devretme; 5+ dosya ya da ~100+ satırlık mekanik iş tek batch / `run --template` ile; doğrulayıcı projenin kendi testleri, işe özel denetim betiği yok; denetim akışı `review` → `show --report` → `apply --max-risk low`, aksi halde işaretli ya da tüm diff. "İncelemeden apply etme" kuralına tek istisna bu.
- **Ölçüm** (Claude'un okuma tokenı ne kadar azaldı, denetçinin kaçırdığı hata) 13g'nin işi.
- **Testler:** 1727 → 1742 (+15).

## D-099 – Faz 13m kod denetimi düzeltmeleri (2026-11-18, Faz 13m)
`/code-review` (PR #36): 10 bulgu, hepsi düzeltildi; önce kırmızı testler.
- **Bağımsızlık bütün dosyalar için:** büyük diff dosya dosya denetlenince her parça ayrı damgalanır; birleşik rapor yalnız her dosyayı başka sağlayıcı denetlediyse `independent: true` (`review.merge_reports`). Denetçi `review_run` başına bir kez seçilir: yazar dışı kimse yoksa geri kalan dosyalar doğrudan yazara gider (dosya başına iki yönlendirme yok).
- **Sessiz geri dönüş yok:** `review.by` açıkça yazılmışsa denetçi bulunamazsa hata verilir; eksik onay (`ConsentRequired`) her durumda kullanıcıya gider. Yalnız `review.by` yokken ve başka hiçbir sağlayıcı denetleyemezken yazar denetler (`independent: false`). `doctor` sağlayıcı olmayan `review.by` adlarını uyarır.
- **`--max-risk` sıkılaştı:** denetimler koşmuş ve hepsi geçmiş olmalı, denetim işaret koymamış olmalı (`flags_count` 0) ve **denetlenen yama uygulanan yamayla aynı** olmalı (`review.patch_sha256`, worktree diff'iyle karşılaştırılır; eşleşmezse "yeniden denetle"). Geçersiz değer (`--max-risk lo`) batch'te de en başta kod 2.
- **Rapor:** `next` yalnız `--max-risk low` gerçekten uygulayacaksa onu önerir (aynı `risk_problem`); uygulanmış ya da atılmış koşuda `next: null` ve "sıradaki: yok"; `ok`/`failed` çevrili, JSON'da `verified` `{type, ok}`.
- **Tek okuyucu:** zarfı `service.envelope_data`, bayrakları `review.load_flags` okur (`_status`, `risk_problem`, `review._author`, rapor).
- **Testler:** 1742 → 1755 (+13).

## D-100 – Faz 13o: herhangi bir OpenAI uyumlu sağlayıcıyı komutla ekleme (2026-11-19, Faz 13o)
**Bağlam:** Kullanıcı EVREN API'yi (OpenAI uyumlu; DeepSeek V4.1 Flash, GLM-5.3) eklemek istedi ve bunun yalnız o servis için değil, her OpenAI uyumlu servis için genel bir yol olmasını istedi. Tek yol `config.yaml`'ı elle yazmaktı. Kullanıcı OpenCode kullanıyor; sağlayıcıları orada tanımlı. Plan: yerel YAPILIS_PLANI.md Faz 13o.
**Karar:**
- Servis koda gömülmez: `providers add` adres, model kimlikleri ve anahtar **değişkeninin adını** yazar (`type: openai_compat`). Varsayılan değişken `<AD>_API_KEY`; anahtarsız sunucu için `--no-key`. Varsayılan kademe 2 (sihirbazın API kademesi).
- `providers import opencode`: `$OPENCODE_CONFIG` › `$XDG_CONFIG_HOME/opencode` › `~/.config/opencode` (`opencode.json`, yoksa `.jsonc`). Yalnız `@ai-sdk/openai-compatible` + `baseURL` + model listesi olan girdiler; diğerleri "alınamaz" diye listelenir. `apiKey: "{env:X}"` → `X`; düz anahtar okunur okunmaz atılır, kullanıcıya hangi değişkene koyacağı söylenir. Dosyada tek uygun girdi varsa doğrudan alınır, birden fazlaysa listelenir (`--name` ile seçilir, kod 0).
- `--check` yeni kod değil, `doctor.check_one`: adres/anahtar/model kimliği. Başarısızsa girdi kalır, kod 3 (betikler anlasın); eksik model yalnız uyarı.
- `providers remove`: girdiyi dosyadan siler; sağlayıcı başka dosyada (genel/proje) tanımlı değilse onayı da geri alınır. `usage` satırları kalır (istatistik ve öğrenen yönlendirme geçmişi).
- Sihirbaz: sağlayıcı listesinin sonunda "başka bir OpenAI uyumlu servis" (`CUSTOM = "+openai_compat"`, geçerli bir sağlayıcı adı olamaz); ad (sihirbazın kendi adlarıyla ya da var olanla çakışamaz), adres, değişken, model, kademe, bütçe sorulur.
**Plandan sapmalar:**
- `add` eksik alanı sormaz; `--base-url` ve `--model` zorunlu. Etkileşimli yol sihirbazdır (`init --plain`, arayüzlü sihirbaz aynı akış). Gerekçe: tek soru akışı, iki yerde aynı doğrulama yok.
- Arayüzün Sağlayıcılar sekmesine "ekle" düğmesi eklenmedi; arayüzlü sihirbaz bu adımı zaten içeriyor.
- Yedek adı `config.yaml.bak-<tarih>` değil, writer'ın kuralı (`.bak`, `.bak.1` …; D-069).
- `.jsonc` desteği yalnız tam satır `//` yorumları.
- Kullanıcı isteğiyle düzeltme-fable'daki "Faz 13 bitene kadar yeni özellik yok" kuralına istisna.
- **Testler:** 1755 → 1792 (+37; live testi ayrı: gerçek OpenCode config'indeki ilk uygun sağlayıcı geçici config'e alınıp kısa istek, 2026-11-19 EVREN ile geçti).

## D-101 – Faz 13o kod denetimi düzeltmeleri (2026-11-19, Faz 13o)
`/code-review` (PR #37): 10 bulgu, hepsi düzeltildi; önce kırmızı testler.
- **Yapıştırılan anahtar yazılmaz:** `--api-key-env` ve sihirbazdaki değişken sorusu yalnız değişken adı kabul eder (`^[A-Za-z_][A-Za-z0-9_]*$`, notify ile aynı kural, D-075); aksi kod 2 ve değer hiçbir mesajda gösterilmez. Sihirbazda `-` = anahtarsız sunucu.
- **Proje dosyasında genel config'teki ad reddedilir** (`--force` ile de): proje girdisi onunla yalnız birleşirdi (eski anahtar değişkeni, başlıklar, bütçe kalırdı).
- **`remove` etkin config'e bakar:** etkin bütün dosyalar (genel + proje) silmeden sonraki haliyle birleştirilip doğrulanır; geçersiz kalacaksa (ör. projede yalnız `enabled: false` kalan girdi) hiçbir şey yazılmaz. Onay yalnız hiçbir dosya sağlayıcıyı tanımlamıyorsa geri alınır. Kural serviste (`RemoveOutcome`), CLI yalnız yazdırır.
- **`import --as NAME`:** Orkestra'nın kabul etmediği ya da çakışan OpenCode adları başka adla alınır; geçersiz ad önerisiyle reddedilir (`My.Lab` → `my-lab`).
- **OpenCode ayrıntıları:** `models.<id>.limit.context` → `context_window` (açık `--context-window` hepsini ezer); `{file:…}` anahtar "düz anahtar" sayılmaz, ayrı not; `{env:X}` `baseURL` ortamdan çözülür (adres gizli değil), yoksa alınamaz; `.jsonc` yorum satırları silinmez, boşaltılır (hata satır numarası doğru).
- **Tek kaynak:** düz veriden ruamel düğümü `writer.to_yaml` (sihirbaz da kullanıyor), sağlayıcı adı kuralı `schema.PROVIDER_NAME`; anahtar değişkeni seçimi `from_flags` / `plan_import`'ta, içe aktarma notu `ImportPlan.key_note`'ta.
- **Testler:** 1792 → 1810 (+18).

## D-102 – Faz 13n: Claude dışı şef (2026-11-19, Faz 13n)
**Bağlam:** Kullanıcı her zaman Claude'u şef yapmayacak. Claude Orkestra'yı skill'den öğreniyor; agy/codex ise yalnız devir özetindeki `prompts/chief_guide.md`'yi (13 satır, Faz 10) görüyordu ve 13i–13m araçlarını bilmiyordu. Plan: yerel YAPILIS_PLANI.md Faz 13n.
**Karar:**
- **Kılavuz skill'in özü:** bağlam süzgeci (`exec`, `read`, `find`, `map`), yalnız büyük/toplu işi devretme, `review` → `show --report` → `apply --max-risk low` (işaretliyse `--only-flagged`, batch'te `--only-ok`), devir dosyası, onay/kota/gizli bilgi kuralları; son satır tam kuralların skill'de olduğunu söyler.
- **Sınır 30 dolu satır, satır başına ≤ 120 karakter** (plan hedefi ≤ 25 idi): skill'in adını verdiği 22 üst komutun hepsi kılavuzda olmalı. 30 satır + başlıkla varsayılan 60 satırlık özette yanında en az 20 proje satırı kalıyor (D-066 kuralı); satırlar `WRAP_WIDTH`'i aşmadığı için hiçbiri sarılmıyor ve kesilmiyor.
- **Kopma testi** (`test_skill.py`): skill'deki her üst komut kılavuzda da var; kılavuzdaki her komut, bayrak ve düzyazı bayrağı CLI'de var (skill'in denetleyicisi); kural bayrakları kılavuzda; uzunluk sınırı. Özet testi: varsayılan sınırda dolu bir projeyle bile kılavuzun her satırı özette.
- **`handoff show --guide`:** devir dosyası olmadan da yalnız kılavuzu yazar (`--json`: `guide`, `lines`); `--brief` ile birlikte kod 2. Kendi açtığı agy/codex oturumuna kılavuzu vermek isteyen kullanıcı için. Proje dosyalarına (GEMINI.md, AGENTS.md) kendiliğinden yazılmaz; README bunu anlatır. `brief.guide_lines()` açık fonksiyon.
- **Benchmark mod E – agy şef + Orkestra:** `agy --output-format json --print <işaretçi>`, istem dosyası = ipucu (`AGENT_HINT`) + kılavuz + görev; `ORKESTRA_CHIEF=agy`. **`--sandbox` yok:** print modunda sandbox her kabuk komutunu reddediyor (D-048), şefin `orkestra`'yı ve testleri çalıştırması gerek; sandbox'sız varsayılan modda `orkestra --version` çalıştı. **Plandan sapma:** agy kendi tokenını veriyor (input, output, thinking, cache_read), bu yüzden token "—" değil, ayrı satırda raporlanıyor (Claude'unkiyle 1:1 karşılaştırılmaz). agy kota mesajı (`quota.detect`) benchmark'ı Claude sınırı gibi durdurur. `--mode all` içinde değil, `--max-claude-runs` saymaz.
- **İlk gerçek koşu** (`bench/results/trial/2026-11-19-1622`): görev 01 ve 02, 2/2 geçti, görev başına ~162 bin agy tokenı (input + output + thinking), ~6 dk; işçi koşusu 0 (küçük işler, kılavuz "kendin yap" diyor; Claude'un B modundaki davranışıyla aynı).
- **Bilinen sorun:** istem klasörü `--add-dir` ile agy'nin ikinci çalışma alanı oluyor; agy oraya da düzenlediği dosyanın bir kopyasını yazdı (değerlendirmeyi etkilemez, çalışma alanı ayrı).
- **Testler:** 1810 → 1822 (+12).

## D-103 – Faz 13n kod denetimi düzeltmeleri (2026-11-19, Faz 13n)
`/code-review` (PR #38): 10 bulgu, hepsi düzeltildi; önce kırmızı testler.
- **Gizli testler diskte kalmaz:** sandbox'sız agy (mod E) yan klasördeki bir önceki koşunun `eval/_hidden_tests`'ini okuyabilirdi. Değerlendirmeden hemen sonra silinir (her mod). Ayrıca agy'nin günlüğü ve çıktısı `_hidden_tests` ya da görevin kendi klasörünü (`bench/tasks/<görev>`) anarsa benchmark `LeakError` ile durur (kod 3).
- **Küçük özette kılavuz kaybolmaz:** 26 satırlık kılavuz ~48 satırdan küçük `brief_max_lines`'ta sığmıyordu; artık tek satır nerede olduğunu söyler (`orkestra handoff show --guide`).
- **Yalnız gerçek kota durdurur:** mod E'de `quota.detect` sonucunda yalnız `hard` (kota bitti) benchmark'ı durdurur; 429 / "rate limit" başarısız koşudur. Mesaj hangi sınır olduğunu söyler (agy / Claude).
- **agy kendi kendine zaman aşımına uğrar:** `--print-timeout` koşucunun öldürme süresinden önce (`max(t − 60, 0,9·t)`), böylece JSON'u ve harcadığı token yazılır.
- **Sonuç yoksa başarı yok:** başarı yalnız çıkış 0 ve `status: SUCCESS`; çıkış 0 ama sonuç yoksa hata ("no status") ve kota denetimi yapılır. JSON'dan önceki sürüm/uyarı satırı atlanır.
- **Token bilinmiyorsa 0 yazılmaz:** hiçbir koşu kullanım vermediyse `agent_tokens_per_task: null`, `agent_runs_without_usage` sayılır ve tabloda yazılır.
- **Kılavuzdaki her komut tam:** kılavuzda kod bloğu yok, satır içi komutlar da argümanlarıyla denetlenir (`check_call`); `providers enable <name>`, `providers add <name> --base-url <url> --model <id>`, `plan expand <plan.md>`. Tam kurallar için kurulu pakette olmayan `skill/` yolu yerine depodaki SKILL.md adresi.
- **Tek kaynak:** mod E'nin istemi `MODES[mode].hint`'ten (`agent_prompt(prompt, hint)`); her pencerede `agy --version` kaydedilir, sürüm değişince not düşülür.
- **Testler:** 1822 → 1836 (+14).

## D-104 – düzeltme-fable üçe bölündü; a: gc satırları, kuyruk, ntfy adresi, kurulum uyarısı (2026-11-20, düzeltme-fable a)
**Bölünme:** plan tek ek faz diyordu; 9 maddesi birbirinden bağımsız ve büyük, tek PR'da denetimi zor. (a) kod düzeltmeleri (madde 1, 2, 3, 5, 6), (b) `cli.py` / `runner.py` bölme (madde 4, davranış değişmez), (c) README kısaltma + "Bilinen sınırlar" + elle kullanım turu + temizlik (madde 7, 8, 9).
- **`gc` satır siler (madde 1):** yeni `state/retention.py`. `runs` + onların `usage` satırları, koşusuz `usage` satırları (gününe göre) ve `done`/`failed`/`removed` `queue` işleri. Satır kesimi `max(--older-than, 35 gün)`: öğrenen yönlendirme (`adaptive.WINDOW`) ve kota tahmini (`LEARN_DAYS`) 30 günü okur, `--older-than 7` dosyaları siler ama bu satırlara dokunmaz. Worktree'si diskte duran (silinemeyen ya da henüz uygulanmamış) koşunun satırı kalır; `--dry-run`'da bu `gc`'nin sileceği worktree'ler gitmiş sayılır. Rezervasyonlar eskisi gibi `purge_stale_reservations`'ta. `quota_events` ve `handoffs` silinmez (küçük, tahmin okur). Yeni migration gerekmedi. JSON'a `rows: {runs, usage, queue}`.
- **`desktop-notifier>=6.0,<7` (madde 2).**
- **`doctor` kurulum uyarısı (madde 3):** `orkestra/install.py` dağıtımın `direct_url.json`'undan düzenlenebilir kaynağı okur, dalı `git symbolic-ref` ile (`cwd=` kaynak). Çalışan ortam kaynağın içindeyse (`uv run`, projenin `.venv`'i) geliştirme sayılır, uyarı yok; değilse (ör. `uv tool install -e`) ve dal `main`/`master` değilse `install` uyarısı (ayrık HEAD dahil). Kalıcı çözüm Faz 14'ün normal kurulumu.
- **`notify.ntfy_url` (madde 5):** varsayılan `https://ntfy.sh`; konu sona eklenir (sondaki `/` atılır). Şemada doğrulanır: `https://`, ya da yalnız yerel/özel ağ adresine (localhost, `.local`, loopback, özel/link-local IP) `http://`; kullanıcı adı/parola, sorgu, parça reddedilir. Hata mesajı değeri yazmaz. Arayüzde ayar yok (config dosyasından).
- **`queue remove --finished` (madde 6):** biten ve başarısız işleri `removed` yapar (satırları `gc` siler); ID ile birlikte ya da hiçbiri verilmezse kod 2.
- Mimari: §4.1 `notify` örneği ve modeli, komut tablosunda `gc`, bütçe ve worktree notları, §21 kuyruk notu güncellendi.

## D-105 – düzeltme-fable a kod denetimi düzeltmeleri (2026-11-20, düzeltme-fable a)
`/code-review` (PR #39): 6 bulgu (1 önemli, 5 küçük), hepsi düzeltildi; önce kırmızı testler.
- **Öğrenilmiş fiyat kalır (önemli):** `pricing._from_history` fiyatı bütün `usage` geçmişinin en yüksek maliyet/token oranından öğreniyor. `gc` her (sağlayıcı, model) için o satırı silmez; yoksa 35 gündür kullanılmayan ücretli model fiyatsız kalırdı.
- **Başlangıcı okunamayan koşu kalır:** `started_at` boş ya da bozuksa yaşı bilinmez, silinmez. Kullanım satırı yalnız günü kesimden eskiyse silinir (bugünün bütçesi hiç eksilmez).
- **`doctor` yanlış uyarı vermez:** dal `git symbolic-ref --quiet` çıkış koduyla okunur: 0 dal, 1 ayrık HEAD (uyarı), diğerleri (depo değil, git yok, zaman aşımı) bilinmez → uyarı yok.
- **`gc --dry-run` yazma kilidi almaz** (`BEGIN IMMEDIATE` yok); çalışan bir işçiyi bekletmez.
- **Gün sayısı tek kaynaktan:** `gc --older-than` ve `stats --since` yardımında `{days}` = `retention.MIN_KEEP.days`; `stats --since` yardımı `gc`'nin eski satırları sildiğini söylüyor.

## D-106 – düzeltme-fable b: `cli.py` ve `tasks/runner.py` bölündü (2026-11-20, düzeltme-fable b)
Davranış değişmedi; yalnız taşıma. Var olan testlere dokunulmadı.
- **`cli.py` (1964 → ~200 satır):** `app()`, hata raporu, dil/config ön okuması, `build_app()` ve testlerin değiştirdiği kancalar (`_interactive`, `_at_terminal`; `t`, `build_app`, `_safe_streams`) yerinde kaldı. Komutlar `orkestra/commands/` altında: `providers` (+ `budget`), `setup` (`init`, `ui`, `config`), `tasks` (`ask`, `run`, `batch`, `show`, `apply`), `chief` (`stats`, `exec`, `read`, `find`, `tokens`, `status`), `handoff` (+ `statusline`), `tools` (`templates`, `cache`, `review`, `map`, `plan`, `discard`, `gc`, `doctor`), `queue` (+ `notify`); ortak yardımcılar `common`. Her modülün `register(...)` fonksiyonu var; `build_app` bunları eski sırayla çağırır (komut sırası ve yardım metinleri aynı: en + tr 108 yardım sayfası bayt bayt karşılaştırıldı). Komut modülleri `build_app` içinde içe aktarılır ve kancalara `cli._interactive()` / `cli._at_terminal()` ile çağrı anında bakar (testler onları `cli` üzerinde değiştiriyor).
- **`tasks/runner.py` (1533 → ~780):** hazırlık, seçenekler, run id, sağlayıcı yuvaları, yönlendirme, `plan_task`, `estimate_task` → `tasks/prepare.py`; koşunun durumu (`__init__`), kayıt yazma, cevap önbelleği, değişiklik özeti, zarf ve bitiş yolları → `tasks/run_record.py` (`RunRecord`). `runner._TaskRun(RunRecord)` denemeleri (aday, cevap, denetim, ajan, yedeğe geçiş) tutar. `run_task` ve `_sleep` `runner`'da kaldı (testler `runner._sleep` / `runner.run_task`'ı değiştiriyor); genel adlar `runner`'dan yeniden dışa veriliyor (`RunOptions`, `ProviderSlots`, `new_run_id`, `plan_task` …).
- En büyük dosyalar artık: `tui/app.py` 782, `tasks/runner.py` 780, `chief/tokens.py` 746 (hepsi ~800'ün altında).
- Mimari dosya ağacı güncellendi.

## D-107 – düzeltme-fable b kod denetimi düzeltmeleri (2026-11-20, düzeltme-fable b)
`/code-review` (PR #40): hata yok (sözdizimi ağacı karşılaştırması: taşıma birebir); 3 küçük not, hepsi düzeltildi.
- `commands/tasks.py` ve `commands/setup.py` `cli`'yi modül düzeyinde değil, kancayı kullanan fonksiyonun içinde içe aktarıyor (döngüsel import kırılganlığı yok).
- `run_record._auto_review`'daki tembel import yorumu doğru modülü anıyor (review → runner → run_record).
- `prepare.py` ve `run_record.py` belge dizgisi: alt çizgili adların (`_prepare`, `_route`, `_Prepared`, `_cannot_do`, `_Answer`) üç modül arasında paylaşıldığını söylüyor (yeniden adlandırma bu fazda yok: yalnız taşıma).

## D-108 – düzeltme-fable c: README kısaldı, ayrıntılar rehbere taşındı (2026-11-20, düzeltme-fable c)
- **README (en + tr) 995 → ~200 satır:** ne, neden (önce kesintisizlik, sonra şefin bağlamı), bugün çalışanlar tablosu, sağlayıcılar (Ollama, OpenAI uyumlu + `providers add`, kod ajanları Codex / agy deneysel / generic), kurulum (`uv tool install git+…`, PyPI'de yok, düzenlenebilir kurulumda `main` notu), hızlı başlangıç, **Bilinen sınırlar**, güvenlik, belgeler, yol haritası, geliştirme. Durum kutusu faz saymıyor (bayatlamasın); yol haritası tablosuna gönderiyor.
- **Ayrıntılar `docs/guide.md` + `docs/guide.tr.md`:** eski README'nin yönlendirmeden sonuç zarfına kadar bölümleri olduğu gibi taşındı; yalnız göreli bağlantılar `docs/`'a göre düzeltildi, örnek çıktı blokları ```` ```text ```` oldu, başa içindekiler eklendi. Yönlendirme sırası paragrafı güncellendi: kademe → kotası azalan sona → `by_kind` → öğrenen skor → `priority` → config sırası (`router._order_key`).
- **`tests/unit/test_readme.py`:** README'ler, rehberler ve tariflerdeki her `orkestra …` komutu ve bayrağı gerçek CLI'ye karşı (skill denetleyicisi, Faz 9a; ```` ```text ```` blokları atlanır, `\` ile süren satırlar birleşir); README ≤ 320 satır; "Bilinen sınırlar" başlığı var, faz sayan eski durum metni yok; beş dil ve bütün sağlayıcı türleri anılıyor; yerel bağlantılar ve başlık çapaları çözülüyor.
- Elle kullanım turu (madde 9) ve dal temizliği (madde 7) kullanıcıyla yapılacak; bu PR'da değil.

## D-109 – düzeltme-fable c kod denetimi düzeltmeleri (2026-11-20, düzeltme-fable c)
`/code-review` (PR #41): 6 bulgu (2 önemli, 4 küçük), hepsi düzeltildi; önce kırmızı testler.
- **Türkçe rehberde iki kırık bağlantı (önemli):** "İ" ile başlayan başlığın GitHub çapası küçük "i" + birleşik nokta (U+0307) içerir, bağlantılar düz "i" kullanıyordu. Başlıklar "İ" ile başlamayacak biçimde yeniden adlandırıldı ("Çapraz denetim: ikinci bir AI, şef için daha ucuz yazma", "Her iş türüne uygun model"). Test çapayı GitHub'a yakın kuruyor: birleşik işaretler ve `_` kalır, yinelenen başlık `-1`, `-2` alır.
- **PyPI'de olmayan paketi kuran satır (önemli):** rehber ve tariflerde `uv tool install "orkestra-cli[notify]"` yerine git adresi + `--with "desktop-notifier>=6.0,<7"`. Test: Faz 14'e kadar hiçbir belge `uv tool install orkestra-cli…` demez.
- **Yol haritası PROGRESS ile çelişmez:** 6b (⏳) satırı eklendi; "düzeltmeler" satırı elle kullanım turu bitene kadar ⏳.
- **PROGRESS tablosu:** düzeltme-fable c satırı yeniden dört hücre.
- **Beş dil testi:** iki harfli parçalar yerine tablodaki `--lang en\|tr\|de\|es\|fr` aranıyor.

## D-110 – Faz 13d: `--max-claude-runs` sınırında tur durmaz, Claude'suz koşular sürer (2026-11-20, Faz 13d)
**Neden:** 13d'nin 60 koşusunun 40'ı Claude oturumu (kullanıcının abonelik kotası), 20'si mod C (yalnız Ollama). Eski davranış ilk fazla Claude oturumunda turu durduruyordu; `--max-claude-runs 0` ile mod C'yi Claude kotası harcamadan bitirmek mümkün değildi, `--resume` de mod listesinin aynı kalmasını istediği için C'yi ayrı dosyada koşmak 13d'yi iki dosyaya bölerdi.
**Karar:** sınır dolunca yalnız Claude oturumları (`CHIEF_MODES`) atlanır; Claude'suz koşular (C, E) sürer. Tur sonunda "N Claude session(s) not started" ve `--resume` komutu yazılır, çıkış kodu 0. Atlanan oturumlar aynı sonuç dosyasına `--resume` ile eklenir. Kota dolunca durma (`UsageLimitReached`, kod 4) değişmedi.
**Kullanım (13d):** önce `--mode all --repeat 1 --max-claude-runs 0` (20 mod C koşusu, Claude yok), sonra her 5 saatlik pencerede `--resume <dosya> --max-claude-runs N` (`/usage` önce/sonra).


## D-111 – Faz 13d: bench'te işçi seçimi, `--worker agy` (2026-11-20, Faz 13d)
**Neden:** 13d'de mod B 20 görevin hiçbirini devretmedi; bench'in işçisi yalnız Ollama 14b idi ve tek başına 9/20 çözüyordu (mod C). Patron–çalışan düzeninin Claude tokenını azaltıp azaltmadığını görmek için güçlü bir işçiyle (agy) zorunlu devir (mod D) ölçülmeli.
**Karar:** `run_bench.py --worker ollama|agy` (varsayılan `ollama`, eski davranış). `agy` seçilince bench'in Orkestra ayarında tek sağlayıcı agy olur (`cli_agent`, `kind: agy`, kademe 1, `experimental: true` ve açıkça `enabled: true` — yoksa router deneysel sağlayıcıyı atlar; zaman aşımı bench'inki); Ollama eklenmez, böylece "en düşük kademe" agy'dir. Seçim sonuç dosyasının `meta.worker` alanına yazılır; `--resume` farklı bir `--worker` reddeder (eski dosyalar `ollama` sayılır). agy PATH'te yoksa koşu başlamaz (kod 2). Mod C de bu ayarla agy'yi kullanır; 13d'nin `--worker agy` koşusu yalnız mod D içindir.
**Sonuç (2026-11-20):** ilk deneme geçersiz (`enabled` yazılmamıştı, router agy'yi atladı, Claude işi kendisi yaptı; `bench/results/trial/2026-11-20-0709`). Düzeltilmiş koşu `bench/results/2026-11-20-0714`: 4/4 geçti, her görevde agy işi yaptı, Claude tokenı görev başına 28,1k (aynı görevlerde A: 13,5k). Claude'un çıktı tokenı bazı görevlerde düştü (ör. 18: 5,1k → 2,1k) ama `cache_creation` 2–3 kat arttı: skill (~28 KB) ve Orkestra komut çıktıları her oturumda ~15k token sabit ek yük. Küçük görevde devretmek Claude'a pahalı; kazanç ancak ek yükten büyük işlerde (13g) ya da ek yük küçültülünce (kısa skill) beklenir.

## D-112 – Faz 13d: PR #42 kod denetimi düzeltmeleri (2026-11-20, Faz 13d)
**Bulgular ve kararlar (6):**
1. agy işçisinin zaman aşımı koşununkiyle aynıydı (900 s): işçi temiz biçimde zaman aşımına uğrayamıyor, mod D'de Claude oturumu öldürülüp tokenı kaybolabiliyordu. Artık `worker_timeout` = koşunun 2/3'ü (en az 1 s; 1 s altı `--timeout` artık çökmez).
2. İşçinin kotası bitince bench durmuyordu, sıradan başarısızlık sayılıyordu. Orkestra kotayı `quota_events`'e yazıyor (Faz 13k); bench her koşudan sonra buna bakar ve kayıt varsa `UsageLimitReached` ile durur (kod 4, koşu kaydedilmez). Durma mesajı artık kimin limiti olduğunu söyler (`Claude`, `agy` ya da işçi adı). Denetim "Orkestra 3600 s bekler" dedi; bu doğru değil: `quota_pause_s` sağlayıcıyı duraklatır, süreç beklemez. Bu yüzden `quota_pause_s` değiştirilmedi.
3. `--worker agy` ile `--ollama-model`/`--ollama-model-2` sessizce yok sayılıyordu. Artık reddedilir (kod 2) ve `meta.ollama_model` boş yazılır. Eski `2026-11-20-0714` dosyası olduğu gibi kaldı (geçmiş kayıt).
4. Mod C/D'de hiç işçi koşusu olmazsa ilerleme satırı `no worker run` der (geçersiz ilk deneme fark edilmeden kalmasın). Geçersiz deneme dosyasının başına not eklendi.
5. Pencere satırı agy sürümünü de yazar (önceden yalnız JSON'daydı).

## D-113 – Faz 13p: skill kısa İngilizce çekirdek + `reference.md` (2026-11-20, Faz 13p)
**Neden:** 13d'de (D-111) mod D'de agy işi yaptığı halde Claude tokenı A'nın ~2 katıydı. `cache_creation` 2–3 kat artmıştı, ek yükün büyük kısmı her devreden oturumun yüklediği 28 KB'lık Türkçe `SKILL.md` idi.
**Karar:** `skill/orkestra/SKILL.md` ≤ 6000 bayt İngilizce çekirdek oldu (4,1 KB): ne zaman devredilir, run/ask/batch/template, yalnız zarfı oku, denetim ve apply kuralları, `exec`/`read`/`find`, devir dosyası, rapor, asla yapma. Eski Türkçe metnin tamamı aynı klasörde `reference.md` oldu, Claude onu yalnız gerektiğinde okur. Kurulum zaten klasörü kopyalar (`cp -r skill/orkestra`), bench iki dosyayı da kopyalar (`SKILL_FILES`). Testler: çekirdek boyutu ve çekirdek kuralları; komut/bayrak denetimi iki dosyayı da kapsar. Skill dili İngilizce oldu (Türkçe aynı metin için daha çok token tutar; skill şefe, yani modele yazılır, kullanıcıya görünmez).
**Ölçüm (`bench/results/2026-11-20-0750`, mod D, `--worker agy`, görev 17–20, 1 tekrar):** 4/4 geçti, her görevi agy yaptı. Claude tokenı görev başına 14,8k (uzun skill ile 28,1k, %47 düşüş; A 13,5k). Claude maliyeti görev başına $0,189 (uzun skill $0,336; A $0,191). Küçük görevde devretmek artık başa baş; Claude'un kendi çıktısı A'dan az (ör. 19: 5,4k → 2,7k). Tek tekrar, 4 görev: gürültü payı var.

## D-114 – Faz 13p: PR #43 kod denetimi düzeltmeleri (2026-11-20, Faz 13p)
**Bulgular ve kararlar (6):**
1. Kısa çekirdek batch'in maliyet onayını (`needs_confirmation`, `--yes-cost`) söylemiyordu; kural yalnız `reference.md`'deydi. Çekirdeğe çıkış kodu satırı (1–5, kod 2'de tahmini göster ve `--yes-cost`'u yalnız kullanıcı kabul ederse ekle) ve "Never" listesine `--yes-cost` eklendi.
2. Bench sonuç dosyası hangi skill ile koşulduğunu yazmıyordu; `--resume` uzun ve kısa skill'i fark edilmeden karıştırabilirdi. Her pencere artık `skill` (iki dosyanın içeriğinden 12 haneli sha256) yazar, değişince not basılır, rapor satırında görünür.
3. Çekirdekte yoktu: kod 3'te bütçe limitlerini kendin değiştirme, kod 4'te onayı kullanıcı verir, oturum başında `orkestra status --json` ve `unapplied` koşular. Eklendi (çekirdek 4,1 → 4,6 KB; 13p ölçümü 4,1 KB sürümle yapıldı, yeniden ölçülmedi).
4. Şef kılavuzunun "Full rules" bağlantısı yalnız çekirdeği gösteriyordu; artık klasörü (`tree/main/skill/orkestra`) gösterir.
5. `docs/guide.md`, `docs/guide.tr.md` ("skill şimdilik Türkçe") ve `bench/README.md` iki dosyalı yapıya göre güncellendi.
6. Toplu devir testi Türkçe cümleleri birleşik metinde arıyordu, çekirdekten silinen kuralı yakalamazdı; artık çekirdekteki İngilizce kuralları denetler. Korumalar için ayrı test eklendi.


## D-115 – Faz 13g: büyük görev takımı, F/G kolları, çapraz denetçi (2026-11-21, Faz 13g)
**Neden:** 13d/13p küçük görevlerde devretmenin en iyi ihtimalle başa baş olduğunu gösterdi (D-111, D-113). 13g'nin sorusu büyük, okumaya dayalı bir işte bölmenin Claude tokenını ≥ %25 azaltıp azaltmadığı.
**Karar:**
- `bench/tasks_big/` ayrı görev takımı, `run_bench.py --suite small|big` (varsayılan `small`, eski davranış). Seçim `meta.suite`'e yazılır, `--resume` dosyadakini kullanır ve farklı `--suite`'i reddeder (eski dosyalar `small`). Zorluk listesine `big` eklendi; rapordaki zorluk tablosu yalnız koşulan zorlukları gösterir.
- İlk büyük görev `g01-ledger`: ~1.200 satırlık bir defter paketi + 33 görünür test + 1.774 satırlık (160 KB) gece içe aktarma log'u. Yedi iş tek şartnamede: log'dan bulunacak tutar ayrıştırma hatası (muhasebe eksisi `(45.00)`, binlik ayırıcı; kötü veri atlanmaya devam eder), `budget.py` (devreden bütçe), `recurring.py` (ay sonuna kırpma, haftalık), CSV dışa aktarma, `budget` CLI komutu, iki modülün bütün açık adlarına docstring, iki yeni test dosyası (≥ 5'er test). Gizli testler (36) başlangıçta kalır, referans çözümde geçer; sızıntı denetimi geçer.
- Plandaki kollar mod olarak: (a) = mod A; (b) = **mod F** (skill + `exec`/`read`/`find` ile bağlamı küçük tut, işçiye iş verme); (d) = **mod G** (F + kalın ve denetlenebilir işleri tek batch'te işçiye ver, başka sağlayıcı denetlesin, `show --report` oku, `--max-risk low` ile uygula). İpuçları yalnız *nasıl çalışılacağını* söyler, çözüme dair bir şey söylemez. İkisi de `all`'a girmez.
- **Sapma (plan "4 kol"):** (c) kısa oturum kolu ayrı mod olarak koşulmuyor. `claude -p` oturumu kendini yeni bir oturuma devredemiyor (`handoff to claude` etkileşimli şef açar); ölçmek için çok oturumlu bir sürücü gerekir. Tek oturumun bağlamı 13j eşiğini geçerse sonuçta not edilir ve kol ayrı bir ek fazda ölçülür.
- `--reviewer none|ollama|agy`: denetçi işçiden başka bir sağlayıcı olarak kademe 2'ye eklenir, `review.by: {<işçi>: [<denetçi>]}`, `independent: true`. Denetçi işçiyle aynıysa koşu başlamaz (kod 2). `meta.reviewer`'a yazılır, `--resume` farklısını reddeder.

## D-116 – Faz 13g: Claude tokenı oturumun tamamından, `--rescore` (2026-11-21, Faz 13g)
**Neden:** 13g'nin ilk G koşusunda (1067 s) sonuç satırının `usage` alanı çıktı 5k, okuma 0,66M gösterdi; aynı satırın `modelUsage` alanı ve maliyeti (`total_cost_usd`) 22k / 2,26M. Arka plan işini bekleyen oturum birkaç döngüde bitiyor, `usage` yalnız son döngüyü sayıyor. Bench bu oturumda Claude tokenını ~4 kat eksik saymış olurdu.
**Karar:** `parse_claude` her token alanını `usage` ile `modelUsage`'ın modeller üzerinden toplamının büyüğünden alır (eski çıktılarda `modelUsage` yoksa `usage` kalır). `num_turns` için böyle bir toplam yok, uzun G oturumlarında tur sayısı eksik olabilir (raporda not edilir). `run_bench.py --rescore <sonuç.json> [--work-dir]`: her Claude koşusunun `--work-dir` altında saklanan `claude-output.json`'unu yeniden ayrıştırır, değişen kayıtları ve `.md` tabloyu yazar, hiçbir koşu başlatmaz. Klasörü silinmiş koşu eski sayısıyla kalır.
**Etki denetimi:** 13e'nin 81 Claude oturumunda ve 13p'nin 4 mod D oturumunda (`2026-11-20-0750`) iki alan aynıydı; bu sonuçlar geçerli. Etkilenen yalnız 13g'nin G koşuları; sonuç dosyası koşu bitince `--rescore` ile düzeltilir.
**Sonuç (D-115 ve D-116'ya, 2026-11-21):** `bench/results/2026-11-20-2346` (A/F/G × 2, 6/6 geçti): F Claude tokenında −%12, önbellekten okumada −%46, maliyette −%20; G −%12 / −%10 / −%13 (bir koşuda devretti ve A'dan pahalıydı, ötekinde hiç devretmedi). Planın ≥ %25 ölçütü tutmadı. Orkestra'nın Claude'a kazandırdığı şey bağlam süzgeci; işi devretmek büyük görevde de kazandırmadı. Konum: kesintisiz çalışma + bağlam süzgeci (README 13e ile).

## D-117 – Faz 13g: PR #44 kod denetimi düzeltmeleri (2026-11-21, Faz 13g)
**Bulgular ve kararlar (6):**
1. `--rescore` kaydın çıktısını `<görev>-<mod>-<tekrar>` klasöründen buluyordu; aynı `--work-dir`'deki her bench çağrısı bu adı yeniden kullanır, başka bir koşunun tokenı yazılabilirdi. Artık yalnız maliyeti (oturumun tamamını zaten sayıyordu, D-116) kayıttakiyle aynı olan çıktı kabul edilir; ötekiler "başka koşunun çıktısı" diye listelenir ve kayıt değişmez.
2. Denetçi kademe 2'de sıradan bir sağlayıcı: işçi `CANNOT_DO` derse ya da başarısız olursa yükseltme denetçiye gider ve işi o yazar. Denetçiyi yönlendirmeden çıkarmak (profilleri kısmak) denetçinin kendi sorgusunu da etkileyebileceği için yerine kayıt ve rapor seçildi: `workers.by_provider` (her koşuyu hangi sağlayıcı yazdı), ilerleme satırında `reviewer <ad> wrote N run(s)`, raporda "Worker runs written by the reviewer". 13g'nin G koşusundaki 4 işçi koşusunun hepsini agy yazmış (bench ev dizinindeki `runs` tablosundan denetlendi); ölçüm kirlenmemiş.
3. `--worker agy --reviewer ollama` ile `--ollama-model-2` kabul ediliyor, sonuca yazılıyor ama hiç kullanılmıyordu. Artık reddedilir (kod 2); denetçi yalnız `--ollama-model`'i kullanır.
4. agy yokken hata mesajı `--reviewer agy`'yi saymıyordu; eklendi.
5. G'de hiç devretmeyen koşu "no worker run" (işçi kullanılamadı) diye basılıyordu; G'de devretmek Claude'un seçimi, artık `did not delegate`.
6. `--rescore` bütün `claude` sözlüğünü karşılaştırdığı için eski biçimli kayıtları (ör. `permission_denials` yok) değişmiş sayıyordu; artık yalnız dört token alanına bakar, öteki alanlar korunur.

## D-118 – Faz 6b: `doctor --mcp` sondası (2026-11-21, Faz 6b)
**Neden:** D-056'da kısmen kalan bulgu: `doctor` yalnız `disabled` MCP kayıtları için uyarıyordu; etkin ama bağlanamayan bir sunucu (ör. Unity'nin "MCP istemcilerini yapılandır" düğmesi koruma betiği kaydını ezince) her agy koşusunu `mcp_wait_s`'ye kadar bekletir ve ancak koşu sırasında fark edilir.
**Karar:** `doctor --mcp` (varsayılan kapalı; kullanıcının gerçek sunucularını başlatır). Yeni modül `providers/mcp_probe.py`: agy'nin MCP ayarındaki etkin stdio sunucuları (`command` olanlar; URL sunucuları ve bozuk kayıtlar atlanır), Windows'ta çözülmüş komut `.cmd`/`.bat` ise `cmd.exe /d /c` ile (D-055), ortama kaydın `env`'i eklenir. Her sunucuya JSON-RPC `initialize` (tek satır) gönderilir, stdout satır satır okunur (stderr yok sayılır, bildirimler atlanır), `id: 1` cevabı `ok`; EOF `exited` (çıkış kodu), JSON olmayan satır ya da hata cevabı `bad_output`, 15 sn (`DEFAULT_TIMEOUT_S`) `timeout`, başlatılamayan `error`. Süreç ağacı her durumda `kill_tree` ile durdurulur. Sunucular aynı anda yoklanır. `doctor` satırları: `ok` → `ok`; `exited` → `info` (uygulaması kapalıyken hemen çıkan koruma betiği agy'yi bekletmez, yalnız araçları yok); öteki üçü `warn` (her agy koşusu onu bekler). Uyarılar `doctor`'un çıkış kodunu değiştirmez.
**Sapma yok;** plan "bağlanamayanları adıyla raporlar" diyordu, "hemen çıkan" ayrımı canlı denemeden çıktı (ilk sürüm onu da uyarı yapıyordu ve öneri metni yanlış yönlendiriyordu).
**Kod denetimi (PR #46, 2026-11-21):** 1 bulgu, düzeltildi: stdout kapandıktan sonra çıkış kodunu bekleme süresizdi; stdout'u kapatıp yaşamaya devam eden bir sunucu (ya da `cmd.exe /c` altında yaşayan çocuk) `doctor --mcp`'yi sonsuza kadar bekletirdi ve süreç ağacı hiç durdurulmazdı. Artık en çok `EXIT_WAIT_S` (3 sn) beklenir; çıkmazsa `bad_output` sayılır ve ağaç durdurulur. Test: stdout'u kapatıp uyuyan sahte sunucu.

## D-119 – Devir dosyası yazımı Windows'ta `os.replace` reddine dayanıklı (2026-11-21, Faz 6b PR #46 CI)
**Bağlam:** PR #46'nın CI'ında (windows-latest, py3.11) `test_two_processes_adding_twenty_items_each_keep_all_forty` kırmızı oldu: `PermissionError: [WinError 5] Access is denied: 'HANDOFF.md.<x>.tmp' -> 'HANDOFF.md'`. D-067 kilit dosyasındaki benzer hatayı kapatmıştı; bu, kilit altındaki atomik yazmanın son adımı: Windows, başka bir sürecin (kilit dışında okuyan) açık tuttuğu dosyanın üzerine `os.replace` yapmayı reddeder. İki şef aynı anda `handoff update` çağırınca biri seyrek de olsa çökebiliyordu.
**Karar:** `store._replace`: `PermissionError`'da 50 ms arayla en çok 20 deneme (~1 sn), sonra hata yükselir; geçici dosya her durumda silinir. Okumayı da kilide almak yerine yeniden deneme seçildi: okuyucuyu bekletmez, kilit sırasını değiştirmez. Testler: iki ret sonra başarı; hep ret → hata, geçici dosya kalmaz.
**Aynı CI'da:** yeni `doctor --mcp` testi yavaş Windows koşucusunda sahte sunucu açılmadan 2 sn'lik süre dolduğu için `timeout` gördü; testin amacı süresiz beklememek, süre 20 sn'ye çıkarıldı (sunucu 60 sn uyuyor).

## D-120 – Faz 6b kapatıldı; Unity elle testleri kapsamdan çıktı (2026-11-21, Faz 6b)
**Karar (kullanıcı):** 6b'nin 1. maddesi (Unity açıkken elle doğrulama) ve 2. maddesi (Unity sonradan açılınca bağlanma, MCP vekili araştırması) yapılmayacak; faz bitmiş sayılır. 4. madde (agy `permissions.deny`) ve 5. madde (makinedeki eski MCP yedekleri) repo dışı makine ayarı, kullanıcıya bırakıldı.
**Neden:** agy'nin takılması asıl sorundu ve D-055/D-056 ile çözüldü; etkin ama bağlanamayan sunucuyu `doctor --mcp` önceden gösteriyor (D-118). Unity açıkken davranış Orkestra'nın kodunu değil agy ile Unity relay'ini ilgilendiriyor.
**Bilinen sınır:** Unity iş sırasında açılırsa istemci o oturumda Unity'ye bağlanmaz (agy'yi yeniden başlatmak gerekir); README/rehberde bununla ilgili ek not yok, gerekirse ileride eklenir.

## D-121 – Faz 11c-a: Web sunucusu bağımlılığı olarak standart kütüphane http.server (2026-11-21, Faz 11c-a)
**Bağlam:** Faz 11c yerel bir web arayüzü ekler (`orkestra ui`). `YAPILIS_PLANI.md` bağımlılık seçiminin (Starlette + uvicorn ya da standart kütüphane) Mimari §1'e bakılarak yapılmasını ve DECISIONS'a yazılmasını ister.
**Karar:** Standart kütüphane `http.server.ThreadingHTTPServer` ve `BaseHTTPRequestHandler` seçildi (`orkestra/web/server.py`).
**Nedenler:**
1. *Sıfır ek bağımlılık:* Mimari §1'deki `sqlite3` kararıyla aynı felsefe; paketi büyütmez, ek bağımlılık ve kilit dosyası yükü getirmez.
2. *Olay döngüsü (event loop) çatışması yok:* Orkestra'nın servisleri senkron fonksiyonlardan `asyncio.run()` ile asenkron sağlayıcıları çağırır. `uvicorn` (ASGI) içinde istekler zaten çalışan bir `asyncio` olay döngüsünde koşar; orada senkron bir servis çağrıldığında `asyncio.run()` `RuntimeError: This event loop is already running` hatası verir. `ThreadingHTTPServer`'da her istek ayrı bir iş parçacığında koştuğu için thread içinde `asyncio.run()` sorunsuz çalışır.
3. *Güvenlik gereksinimlerinin tam denetimi:* Yalnız `127.0.0.1` dinleme, dinamik boş port (port 0), `Host` başlığı doğrulaması (`127.0.0.1:<port>`), DNS rebinding ve CSRF koruması için CORS'un kapalı olması ve tek kullanımlık oturum token'ı doğrudan işleyicide (`secrets.compare_digest`) uygulanmıştır.
**Sonuç:** `orkestra ui` varsayılan olarak yerel web sunucusunu açar; `--tui` eski terminal arayüzünü açar; `--no-browser` otomatik tarayıcı açmayı engeller; `--port` port belirtir.
**Kod denetimi (Claude, 2026-11-21, PR #48):**
1. `secrets.compare_digest` ASCII dışı `str`'de `TypeError` atıyor; `?token=%C3%A9` isteği yanıtsız kapanıyor, stderr'e iz basılıyordu. Token'lar UTF-8 bayt olarak karşılaştırılır, sonuç 403.
2. `HTTPServer.allow_reuse_address` Windows'ta `SO_REUSEADDR` demek; bu, dinlemedeki bir portu ikinci bir sokete de bağlatıyor (iki `orkestra ui --port N` aynı portta, istekler rastgele birine). Windows'ta `allow_reuse_address` kapalı ve `SO_EXCLUSIVEADDRUSE` açık; POSIX'te davranış aynı.
3. Dolu/izinsiz port `OSError` olarak iç hataya (kod 5) düşüyordu; artık `UsageError` (kod 2), `ui.web.error.port` 5 dilde.
4. Adres token taşıdığı için her yanıta `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.
5. `127.0.0.1` dışı host koruması `ValueError` yerine `errors.InternalError` (AGENTS kuralı), testi eklendi.
6. `--window` 11c-e'nin işi; 11c-a'daki yarım hâli (pywebview kuruluyken de tarayıcı açıyordu, mesaj yoktu) ve iki metin anahtarı çıkarıldı.
7. README (en + tr) terminal arayüzü satırı `orkestra ui --tui`.

## D-122 – Faz 11c-d: API anahtarlarının OS kimlik deposunda (keyring) saklanması (2026-11-21, Faz 11c-d)
**Bağlam:** Faz 11c web arayüzünde kullanıcıların sağlayıcı API anahtarlarını girmesi ve yönetmesi gerekir. Orkestra'nın kesin kuralı: "Anahtar hiçbir dosyaya girmez" (config, git, log, commit).
**Karar:** `keyring>=24.0` bağımlılığı eklendi. Anahtarlar işletim sisteminin güvenli kimlik deposuna (Windows Credential Locker, macOS Keychain, Linux SecretService) `orkestra` servis adı ve ortam değişkeni adıyla (`api_key_env`, ör. `OPENROUTER_API_KEY`) kaydedilir.
**Okuma önceliği:**
1. `os.environ` (öncelikli – CI, CLI, geçici kullanım ve komut satırı geçersiz kılmaları için).
2. `keyring` (ortam değişkeni yoksa veya boşsa sorgulanır).
**Güvenlik ve İzolasyon:**
- Anahtarlar asla config dosyasına, git'e, loglara ya da web arayüzü API yanıtlarına dönmez.
- Web arayüzü ve API (`/api/keys`) yalnızca `defined: bool` ve `source: "env" | "keyring" | "none"` döner.
- Keyring'de saklanan anahtarlar `security.redact` tarafından otomatik olarak toplanır ve log/çıktılarda maskelenir (`***`).
- Keyring servisi kullanılamıyorsa çökme yerine anlaşılır `KeyringUnavailable` hatası (kod 2) döner.
**Kod denetimi (Claude, 2026-11-21, 11c sonu):**
1. Anahtarlar ekranı `notify.ntfy_topic_env` değişkenini de listeliyor ve keyring'e yazdırıyordu, ama bildirim konuyu yalnız ortam değişkeninden okuyordu: ekrandan kaydedilen konu sessizce yok sayılıyordu. `notify.send` de aynı sırayla okur (ortam değişkeni, yoksa keyring; `chief.keys.get_key`).
2. Testler gerçek işletim sistemi kimlik deposunu okuyordu (yalnız `test_keys.py` sahte depo kullanıyordu): web arayüzünden bir anahtar kaydeden geliştiricide "anahtar yok" testleri değişirdi. `tests/conftest.py`'de her teste bellekte bir keyring (`memory_keyring`, autouse).

## D-123 – Faz 11c-e: İsteğe bağlı bağımlılık olarak pywebview ve masaüstü pencere modu (--window) (2026-11-21, Faz 11c-e)
**Bağlam:** Faz 11c-e yerel web arayüzü için masaüstü penceresi seçeneği (`--window`) ekler. Bazı kullanıcılar tarayıcı sekmesi yerine bağımsız bir yerel pencere tercih edebilir. Ancak `pywebview` işletim sistemine özgü GUI/WebView kütüphaneleri (Windows WebView2, macOS WebKit, Linux WebKitGTK) gerektirebilir; sunucu veya CLI ortamlarında kurulum yükü getirmemesi gerekir.
**Karar:** `pywebview>=5.0` temel zorunlu bağımlılıklar yerine `[project.optional-dependencies]` altında `window = ["pywebview>=5.0"]` olarak eklendi.
**Davranış ve Hata Yönetimi:**
- `orkestra ui --window` çalıştırıldığında `pywebview` kuruluysa arka planda sunucuyu başlatıp 1280x800 ebadında yerel pencere açar (`webview.create_window`, `webview.start`).
- `pywebview` kurulu değilse CLI çökmez; stderr'e `ui.web.window_fallback` uyarısını yazar ve otomatik olarak varsayılan tarayıcı moduna (`webbrowser.open`) düşer.
- İsteğe bağlı kurulum: `uv tool install git+https://... --with pywebview` veya `pip install orkestra-cli[window]`.
**Alternatifler:** `pywebview`'ı zorunlu bağımlılık yapmak (sunucu ortamlarında ve C-bağımlılıklarında kurulum sorunlarına yol açar) ya da Electron/Tauri gibi ayrı ağır araçlar kullanmak (paket boyutunu ve karmaşıklığı aşırı artırır).
**Sonuç:** Kullanıcı arayüzü masaüstü penceresinde (`orkestra ui --window`), tarayıcıda (`orkestra ui`) veya terminalde (`orkestra ui --tui`) kesintisiz deneyimle çalışır.
**Kod denetimi (Claude, 2026-11-21, 11c sonu):** yalnız `ImportError` yakalanıyordu; pywebview kurulu ama açılamıyorsa (ör. Linux'ta GUI arka ucu yok) komut iz basıp çöküyordu, sunucu iş parçacığı da açık kalıyordu. Artık pencere açılamazsa sunucu iş parçacığı durdurulur, `ui.web.window_failed` (5 dil, nedeniyle) yazılır ve tarayıcıya düşülür; pencere kapanınca sunucu kapatılır (`server_close`).

## D-124 – `routing.prefer_fast`: Kademe içinde hızlı model tercihi (2026-11-22, Faz 13q-b)
**Bağlam:** Öğrenen yönlendirme (`routing.adaptive`) yalnız başarı oranına (Laplace skoru) bakıyordu; ancak modeller arasında süre farkı büyüktü (ör. hızlı Ollama ile yavaş Evren/Ajan). Şefin işçiyi beklemesi pahalıya mal olabiliyordu.
**Karar:** `routing.prefer_fast: bool = false` ayarı eklendi.
- Kapalıyken (varsayılan): yönlendirme sırası eskisiyle bit bit aynı kalır.
- Açıkken: kademe içinde başarı skorları arasındaki fark < 0,05 olan adaylar arasında ortanca süresi (`duration_s`) kısa olan öne geçer; süresi bilinmeyen adaylar bilinenlerin arkasına alınır.
- Belirgin başarı farkında (fark >= 0,05) başarılı olan öne geçer (hız başarıyı ezmez).
- Kademe (`tier`), kota azalan durumu (`quota_low`) ve iş türü tercihi (`by_kind`) önceliğini korur; hız yalnız kademe içinde etkilidir.
**Sonuç:** `prefer_fast` açıkken başarıdan ödün vermeden en hızlı model seçilir; `docs/PROJE_DOKUMANTASYONU.md` §7 güncellendi.
