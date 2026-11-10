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
