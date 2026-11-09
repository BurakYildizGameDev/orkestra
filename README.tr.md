# Orkestra

[![CI](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml/badge.svg)](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![Lisans](https://img.shields.io/badge/lisans-MIT-green)

[English](README.md) · **Türkçe**

**Güçlü bir "şef" modelin (ör. Claude) işi birçok ucuz veya yerel "işçi" modele dağıtmasını, sonuçları doğrulamasını ve bir sağlayıcı çökünce diğerine geçmesini sağlayan, bütçe farkındalıklı komut satırı aracı.**

> **Durum: geliştirme aşamasında.** 14 fazın 0–4'ü ve 5. fazın ilk kısmı bitti: proje iskeleti, yapılandırma, Ollama ve OpenAI uyumlu adapter'lar, `ask`, `doctor`, günlük bütçe, sağlayıcı onayı, devre kesici, gizli bilgi taraması, yeniden deneme + yedeğe geçişli router ve doğrulama, geri bildirimle tekrar deneme ve üst kademeye geçişli görev dosyaları. Yalıtılmış kod düzenleme ve diğerleri [yol haritasında](#yol-haritası). Bu README sadece bugün çalışan özellikleri anlatır.

```
Sen ──► Claude (şef: planlar, böler, denetler)
            │
            ▼
        orkestra ──► router (kademe + bütçe + sağlık)      ← Faz 3–4
            │
   ┌────────┼──────────────┬───────────────┐
   ▼        ▼              ▼               ▼
 Ollama  OpenRouter    Codex CLI     Antigravity CLI
 (yerel) (API)         (kod ajanı)   (kod ajanı)            ← Faz 6
            │
            ▼
   doğrulama ──► kısa sonuç zarfı (JSON) ──► şef sadece bunu okur
```

## Neden?

Güçlü modellerin kotası azdır, bol kotalı modeller ise daha az güvenilirdir. Orkestra hacimli ama
kontrolü kolay işleri (özet, docstring, test, veri çıkarma, mekanik refactor) ucuz veya yerel
modellere gönderir, çıktıyı otomatik kontrol eder ve şefe tüm çıktı yerine kısa bir JSON zarfı
verir. Bir sağlayıcı çöktüğünde, bütçesi bittiğinde veya internet olmadığında sıradaki devreye girer.

## Bugün çalışanlar

| Özellik | Komut |
|---|---|
| Örnek config (genel veya projeye özel) | `orkestra init [--project] [--force]` |
| Birleştirilmiş config ve kaynakları, okunur hatalarla doğrulama | `orkestra config show [--json]`, `orkestra config validate` |
| İşçi modele tek soru; bağlam dosyaları ve isteğe bağlı JSON Schema | `orkestra ask "…" [--context f] [--schema s.json] [--json]` |
| Profil, gizlilik ve yedeğe geçişli yönlendirme; her sağlayıcının neden seçildiğini/elendiğini görme | `ask [--profile p] [--tier n] [--local-only] [--dry-run]` |
| Görev dosyaları (YAML/JSON): cevabı doğrula, geri bildirimle tekrar dene, üst kademeye geç | `orkestra run gorev.yaml [--dry-run] [--json]` |
| Ortam kontrolü: config, sağlayıcı erişimi, API anahtarı değişkenleri, Ollama modelleri, onaylar, beklemedeki sağlayıcılar, git, codex/agy | `orkestra doctor [--json] [--warm]` |
| Sağlayıcı başına açık onay (vermeden önce ne yapabileceği gösterilir) | `orkestra providers enable <ad>`, `providers disable <ad>` |
| Sağlayıcılar: onay, sağlık ve kalan bütçe | `orkestra providers list [--json]` |
| Günlük bütçe (token, USD, istek, koşu), yerel gece yarısı sıfırlanır | `orkestra budget [--json]` |
| Türkçe veya İngilizce arayüz | `--lang en\|tr`, `ORKESTRA_LANG` veya config'te `language:` |

Şu an desteklenen sağlayıcılar:

- **Ollama**, kendi `/api/chat` API'si üzerinden. `num_ctx` her istekte gönderilir; uzun istemler asla sessizce kesilmez (Ollama'nın OpenAI uyumlu uç noktası bunu yok sayar).
- **OpenAI uyumlu her API**: OpenRouter, LM Studio, vLLM, kendi sunucun. OpenRouter'ın bildirdiği maliyet (`usage.cost`) okunur; diğerlerinde maliyet `price_per_mtok`'tan hesaplanır.

## Kurulum

Gereksinimler: Python 3.11+, git, [uv](https://docs.astral.sh/uv/). İsteğe bağlı: Ollama, OpenRouter anahtarı.

```bash
git clone https://github.com/BurakYildizGameDev/orkestra
cd orkestra
uv sync
uv run orkestra --help
```

Paket PyPI'da `orkestra-cli` adıyla yayınlanacak; komutun adı `orkestra`.

## Hızlı başlangıç

```bash
# 1. Örnekten config oluştur (~/.orkestra/config.yaml)
uv run orkestra init                 # veya: init --project → ./orkestra.yaml

# 2. Config'i düzenle: kullandığın sağlayıcıları bırak, model adlarını yaz.
#    API anahtarları ortam değişkenine gider. Config'te sadece değişkenin ADI durur.
export OPENROUTER_API_KEY="..."      # PowerShell: $env:OPENROUTER_API_KEY="..."

# 3. Her şeyi kontrol et ve kullanmak istediğin sağlayıcılara izin ver
uv run orkestra config validate
uv run orkestra doctor               # --warm her Ollama modelini belleğe de yükler
uv run orkestra providers enable ollama
uv run orkestra providers enable openrouter   # URL'yi ve anahtar değişkenini gösterir, sonra sorar

# 4. Sor
uv run orkestra ask "Bu fonksiyon ne yapıyor?" --context src/util.py
uv run orkestra ask "Tek satırda özetle" --provider openrouter --tier 2
uv run orkestra ask "Tek satırda özetle" --dry-run      # kim cevap verirdi, neden
uv run orkestra ask "İsimleri çıkar" --context kisiler.txt --schema isimler.schema.json --json

# 5. Ya da görevi kontrolleriyle birlikte dosyaya yaz ve çalıştır
uv run orkestra run examples/tasks/summarize-readme.yaml --json
```

`ask` **router** üzerinden çalışır. Görevi yapabilecek her (sağlayıcı, model) çiftini şu sırayla
listeler: kademe artan → `priority` azalan → config'e yazdığın sıra (sağlayıcılar baştan sona, sonra
her sağlayıcının modelleri listelendiği sırayla). Bu sırayı ezmek için `priority` kullan. Bütçe
sadece eler: limiti aşacak sağlayıcı atlanır, ama kalan bütçe sırayı değiştirmez. Kademeler profilden gelir
(`--profile cheap|balanced|quality`, varsayılan config'ten); `--tier` en alt kademeyi belirler, üst
kademeler yedek olarak kalır.

Bir sağlayıcı veya model şu durumlarda elenir:

- kapalıysa, kod ajanıysa veya API anahtarı değişkeni tanımlı değilse
- henüz onayı yoksa (`orkestra providers enable <ad>`) ya da onaydan sonra ayarları değiştiyse
- **devre kesici tarafından beklemeye alındıysa**: arka arkaya 3 ağ/sunucu hatası 5 dakika, kimlik doğrulama hatası 1 saat bekletir
- profilin kademe aralığı dışındaysa veya bağlam penceresi istem için küçükse
- günlük bütçesi aşılacaksa
- uzak bir sağlayıcıysa ve bağlamda gizli bilgi varsa (API anahtarı, özel anahtar…) ya da görev `--local-only` ise

`orkestra ask "…" --dry-run` hiçbir şey göndermeden sırayı ve elenen her adayın nedenini gösterir.

**Aynı komut içinde yedeğe geçiş.** Adaylar biri cevap verene kadar sırayla denenir:

| Hata | Ne olur |
|---|---|
| Bağlantı hiç kurulamıyor (internet yok, DNS, reddedildi) | 0.5 sn sonra bir kez daha (anlık dalgalanma için), sonra sıradaki sağlayıcı |
| Zaman aşımı, 5xx, istek sınırı (429) | aynı model 1 sn, 2 sn, 4 sn (+ rastgele pay) sonra veya sunucunun `retry-after` süresi kadar beklenip yeniden denenir; üçüncü hata sağlayıcıyı beklemeye alır ve sıradakine geçilir |
| Kimlik doğrulama başarısız | sağlayıcı atlanır (ve 1 saat beklemeye alınır; `providers enable` beklemeyi kaldırır) |
| Model bulunamadı (404) | sıradaki model; sağlayıcının diğer modelleri yine denenir |
| İstem modele göre uzun | daha büyük bağlam pencereli sıradaki model |
| Boş veya bozuk cevap | sıradaki aday |
| Model `CANNOT_DO: <neden>` cevabı verir | daha üst kademedeki sıradaki aday; kalmadıysa durum `escalate`, çıkış kodu 1 |

Zaman aşımına uğrayan istek, günlük bütçeye tahminiyle sayılır (sağlayıcı ücretlendirmiş
olabilir); yeniden denemeler ve yedeğe geçişler `daily_runs` için sağlayıcı başına tek koşu sayılır.

Yani internet yokken `ask` aynı komut içinde yerel Ollama'dan cevap verir; uzak API envelope'ta
`failovers` altında listelenir. Bütün adaylar başarısız olursa hepsi listelenir ve çıkış kodu 3 olur.

## Görev dosyaları ve doğrulama

Görev dosyası tek bir işi ve sonucun nasıl kontrol edileceğini tarif eder. `orkestra ask` de
seçeneklerinden aynı türde bir görev oluşturur. Örnekler: [`examples/tasks/`](examples/tasks/).

```yaml
id: summarize-readme
kind: ask                    # edit görevleri (git worktree'de kod değiştirme) sonra gelecek
tier: 1                      # başlanacak en düşük kademe
prompt: |
  Bu projenin ne yaptığını tek cümleyle özetle ve ana özelliklerini listele.
context:
  files: [README.md]
  globs: []                  # örn. ["src/**/*.py"]; .gitignore ve .orkestraignore uygulanır
output:
  format: json               # text | json
  schema: summary.schema.json
verify:
  - type: regex
    must_not_match: ["(?i)lorem ipsum"]
  - type: command            # kendi kontrolün; çıkış kodu 0 = geçti
    run: "python check_summary.py"
    timeout_s: 60
limits:
  max_retries: 1             # model başına geri bildirimle tekrar (varsayılan: defaults.max_retries)
  timeout_s: 120             # istek başına (varsayılan: sağlayıcının zaman aşımı)
privacy: normal              # local_only görevi yerel modellerde tutar
tags: [docs]
```

Göreli yollar `orkestra`'yı çalıştırdığın dizine göre, görevde `workspace` varsa ona göre çözülür.

**Doğrulayıcılar:** `command` (çıkış kodu 0; `shell: true` yazmadıkça kabuk yok, boru ve `&&`
için gerekir), `json_schema` (`format: json` ise kendiliğinden eklenir), `regex` (`must_match`,
`must_not_match`), `files_exist`, ve kod değişiklikleri için `max_changed_files`,
`max_diff_lines`, `protect_paths`, `forbid_paths` (hiçbir şey değiştirmeyen `ask` görevlerinde
kendiliğinden geçer).

**Bir kontrol başarısız olunca:**

1. Aynı model önceki cevabını ve başarısız kontrolleri (İngilizce) geri alır ve `max_retries`
   kez daha dener.
2. Hâlâ geçemezse ya da `CANNOT_DO: <neden>` derse bir üst kademeye geçilir, aynı kademedeki
   diğer adaylar atlanır. Geçiş `escalations` altında listelenir.
3. Hiçbir cevap geçmezse: `status: failed`, kademe 3 de geçemediyse `escalate` (şef devralmalı).
   Çıkış kodu 1. Son cevap yine `output.md`'de durur.

Her denemenin isteği, cevabı ve kontrol kaydı (`verify.log`)
`~/.orkestra/runs/<run_id>/attempts/<n>/` altında tutulur.

## Yapılandırma

Orkestra bir temel dosya ve bir proje dosyası okur; proje dosyası kazanır:

1. Temel: `--config <dosya>` › `$ORKESTRA_CONFIG` › `~/.orkestra/config.yaml`
2. Proje: bulunduğun dizinden git köküne kadar en yakın `orkestra.yaml`

Eşlemeler derin birleştirilir, listeler değiştirilir, `providers.<ad>: null` bir sağlayıcıyı kaldırır.
Yazım hataları sessizce geçmesin diye bilinmeyen anahtarlar reddedilir. `daily_usd` sınırı her
istekten önce `price_per_mtok` ile kontrol edilir; o yoksa sağlayıcının yayınladığı fiyat listesi
(OpenRouter, bir gün önbelleklenir), o da yoksa geçmiş isteklerde görülen maliyet kullanılır. Yorumlu tam örnek:
[`examples/orkestra.example.yaml`](examples/orkestra.example.yaml).

```yaml
version: 1
language: auto                 # auto | en | tr

providers:
  ollama:
    type: ollama
    models:
      - id: qwen2.5-coder:14b
        tier: 1
        context_window: 32768  # Ollama'ya num_ctx olarak gider
  openrouter:
    type: openai_compat
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY   # değişkenin ADI, anahtarın kendisi asla
    models:
      - id: provider/model-adi
        tier: 2
    budget:
      daily_usd: 2.00
```

Hatalar alanın tam yerini, seçili dilde gösterir:

```
Hata: Geçersiz yapılandırma (~/.orkestra/config.yaml):
  - providers.openrouter.models[0].tier: 1, 2 veya 3 olmalı
  - providers.codex.sandbox: 'danger-full-access' desteklenmiyor; 'read-only' veya 'workspace-write' kullan
```

## Sonuç zarfı ve çıkış kodları

`--json` ile stdout'ta tam olarak bir JSON belgesi olur, geri kalan her şey stderr'e gider. `ask`
için bu belge sonuç zarfıdır. Cevabın tamamı istek, yanıt ve görevle birlikte diskte,
`~/.orkestra/runs/<run_id>/` altında durur.

```json
{
  "envelope_version": 2,
  "run_id": "20261109-193405-3679",
  "task_id": "ask",
  "status": "ok",
  "provider": "ollama",
  "model": "qwen2.5-coder:1.5b",
  "tier": 1,
  "attempts": 2,
  "failovers": [
    {"provider": "openrouter", "model": "some/model", "tier": 1,
     "error": "ProviderUnavailable", "reason": "openrouter: … adresine bağlanılamıyor", "attempts": 1}
  ],
  "summary": "4",
  "verification": [],
  "output_path": "~/.orkestra/runs/20261109-193405-3679/output.md",
  "usage": {"prompt_tokens": 142, "completion_tokens": 2, "cost_usd": 0.0},
  "duration_s": 0.375,
  "error": null
}
```

| Çıkış kodu | Anlamı |
|---|---|
| 0 | Başarılı |
| 1 | Doğrulama geçmedi (`failed`) ya da şefin devralması gerekiyor (`escalate`); `doctor` için: bir kontrol başarısız |
| 2 | Yapılandırma veya kullanım hatası |
| 3 | Uygun sağlayıcı yok ya da bütün adaylar başarısız (erişilemiyor, beklemede, bütçe doldu, bağlamda gizli bilgi, anahtar yok, profil dışında) |
| 4 | Kullanıcı onayı gerekli (`orkestra providers enable <ad>`) |
| 5 | Worktree / uygulama çakışması (Faz 5) |
| 10 | Beklenmeyen iç hata |

## Güvenlik

- API anahtarları config dosyalarında tutulmaz. Orada sadece ortam değişkeninin adı durur; `doctor` değişkenin tanımlı olup olmadığını söyler, değerini asla göstermez.
- Sağlayıcı hata mesajları temizlenir; bir API'nin geri yansıttığı anahtar (ör. 401 gövdesinde) çıktıya ulaşmaz.
- Kod ajanları için `danger-full-access` config tarafından reddedilir.
- Açık onay olmadan hiçbir sağlayıcı kullanılmaz. Onay, verinin nereye gittiğini ve neyin çalıştırılacağını belirleyen ayarlara bağlıdır (URL, anahtar değişkeni, başlıklar, komut, sandbox, model kimlikleri); bunlardan biri değişirse yeniden sorulur. Sağlayıcıyı kapatıp açmak, bütçesini veya zaman aşımını değiştirmek yeniden sormaz.
- Bağlam dosyaları gizli bilgi için taranır (OpenAI/OpenRouter/AWS/GitHub/Slack/Google anahtarları, özel anahtarlar ve config'teki anahtar değişkenlerinin değerleri). Böyle bir bağlam `--allow-secrets` verilmedikçe uzak sağlayıcıya asla gitmez.
- Orkestra'nın `~/.orkestra/runs/` altına yazdığı her şey (istek, yanıt, çıktı, envelope, log) maskelenir. İstem metni de taranır; `.orkestraignore`'a uyan dosyalar hiç gönderilmez.
- `command` doğrulayıcısı senin yazdığın komutu çalışma dizininde çalıştırır. Bu, komutu kendin çalıştırmakla aynı risktir; Orkestra kabuğu sadece `shell: true` ile kullanır.
- Telemetri yok. Her şey senin bilgisayarında ve senin seçtiğin sağlayıcılarda kalır.

## Yol haritası

| Faz | Konu | Durum |
|---|---|---|
| 0 | İskelet, araçlar, çok dilli altyapı | ✅ |
| 1 | Yapılandırma: şema, birleştirme, `init`, `config` | ✅ |
| 2 | Ollama + OpenAI uyumlu adapter'lar, `ask`, `doctor` | ✅ |
| 3 | Durum veritabanı, günlük bütçe, sağlayıcı onayı, devre kesici, gizli bilgi taraması | ✅ |
| 4 | Router, yeniden deneme ve **yedeğe geçiş**: internet yok → yerel Ollama, çöken API → sıradaki sağlayıcı | ✅ |
| 5a | Görev dosyaları, doğrulayıcılar, geri bildirimle tekrar deneme, üst kademeye geçiş (`orkestra run`) | ✅ |
| 5b–5c | Git worktree, `edit`, `show`, `apply`, `discard` | ⏳ |
| 6 | Kod ajanları: Codex CLI, Antigravity CLI | ⏳ |
| 7 | Toplu çalıştırma, paralellik, maliyet tahmini | ⏳ |
| 8 | Şef araçları: `status`, `review`, `map`, şablonlar, `plan expand`, önbellek, tasarruf sayacı | ⏳ |
| 9 | Claude skill | ⏳ |
| 10 | Şef devri (Claude ↔ Codex ↔ Antigravity) | ⏳ |
| 11 | Terminal arayüzü, kurulum sihirbazı, 5 dil | ⏳ |
| 12 | Gece vardiyası kuyruğu, bildirimler, öğrenen yönlendirme | ⏳ |
| 13 | Benchmark (kötü sonuçlarla birlikte) | ⏳ |
| 14 | Paketleme, dokümantasyon, PyPI yayını | ⏳ |

İlerleme notları [`docs/PROGRESS.md`](docs/PROGRESS.md) dosyasında. Plandan her sapma, gerekçesiyle
[`docs/DECISIONS.md`](docs/DECISIONS.md) dosyasında.

## Geliştirme

```bash
uv sync
uv run pytest                 # ağsız; gerçek servislerle: uv run pytest -m live
uv run ruff check . && uv run ruff format --check .
uv run pyright
```

CI; Linux, macOS ve Windows'ta Python 3.11, 3.12 ve 3.13 ile çalışır. Bu repoda çalışan kodlama
ajanları için kurallar [`AGENTS.md`](AGENTS.md) dosyasında.

## Lisans

[MIT](LICENSE)
