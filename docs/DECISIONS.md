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
