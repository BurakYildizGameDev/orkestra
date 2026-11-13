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
