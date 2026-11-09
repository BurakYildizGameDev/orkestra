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

