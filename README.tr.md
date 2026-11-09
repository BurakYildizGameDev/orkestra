# Orkestra

[![CI](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml/badge.svg)](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![Lisans](https://img.shields.io/badge/lisans-MIT-green)

[English](README.md) · **Türkçe**

**Güçlü bir "şef" modelin (ör. Claude) işi birçok ucuz veya yerel "işçi" modele dağıtmasını, sonuçları doğrulamasını ve bir sağlayıcı çökünce diğerine geçmesini sağlayan, bütçe farkındalıklı komut satırı aracı.**

> **Durum: geliştirme aşamasında.** 14 fazın 0–2'si bitti: proje iskeleti, yapılandırma, Ollama ve OpenAI uyumlu adapter'lar, `ask` ve `doctor`. Yönlendirme, bütçe, yedeğe geçiş, yalıtılmış kod düzenleme ve diğerleri [yol haritasında](#yol-haritası). Bu README sadece bugün çalışan özellikleri anlatır.

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
| Ortam kontrolü: config, sağlayıcı erişimi, API anahtarı değişkenleri, Ollama modelleri, git, codex/agy | `orkestra doctor [--json] [--warm]` |
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

# 3. Her şeyi kontrol et
uv run orkestra config validate
uv run orkestra doctor               # --warm her Ollama modelini belleğe de yükler

# 4. Sor
uv run orkestra ask "Bu fonksiyon ne yapıyor?" --context src/util.py
uv run orkestra ask "Tek satırda özetle" --provider openrouter --tier 2
uv run orkestra ask "İsimleri çıkar" --context kisiler.txt --schema isimler.schema.json --json
```

`--provider`/`--model` verilmezse `ask`, istenen kademede (varsayılan 1) modeli olan ilk açık
sağlayıcıyı config sırasıyla seçer. Kapalı olanlar, kod ajanları ve API anahtarı ortamda olmayanlar
atlanır; hiçbiri kalmazsa her birinin nedeni listelenir.

## Yapılandırma

Orkestra bir temel dosya ve bir proje dosyası okur; proje dosyası kazanır:

1. Temel: `--config <dosya>` › `$ORKESTRA_CONFIG` › `~/.orkestra/config.yaml`
2. Proje: bulunduğun dizinden git köküne kadar en yakın `orkestra.yaml`

Eşlemeler derin birleştirilir, listeler değiştirilir, `providers.<ad>: null` bir sağlayıcıyı kaldırır.
Yazım hataları sessizce geçmesin diye bilinmeyen anahtarlar reddedilir. Yorumlu tam örnek:
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
  "envelope_version": 1,
  "run_id": "20261109-193405-3679",
  "task_id": "ask",
  "status": "ok",
  "provider": "ollama",
  "model": "qwen2.5-coder:1.5b",
  "tier": 1,
  "attempts": 1,
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
| 1 | Doğrulama geçmedi (ör. cevap `--schema`'ya uymuyor); `doctor` için: bir kontrol başarısız |
| 2 | Yapılandırma veya kullanım hatası |
| 3 | Uygun sağlayıcı yok (erişilemiyor, kimlik doğrulama başarısız, anahtar yok, o kademede model yok) |
| 4 | Kullanıcı onayı gerekli (Faz 3) |
| 5 | Worktree / uygulama çakışması (Faz 5) |
| 10 | Beklenmeyen iç hata |

## Güvenlik

- API anahtarları config dosyalarında tutulmaz. Orada sadece ortam değişkeninin adı durur; `doctor` değişkenin tanımlı olup olmadığını söyler, değerini asla göstermez.
- Sağlayıcı hata mesajları temizlenir; bir API'nin geri yansıttığı anahtar (ör. 401 gövdesinde) çıktıya ulaşmaz.
- Kod ajanları için `danger-full-access` config tarafından reddedilir.
- Telemetri yok. Her şey senin bilgisayarında ve senin seçtiğin sağlayıcılarda kalır.

## Yol haritası

| Faz | Konu | Durum |
|---|---|---|
| 0 | İskelet, araçlar, çok dilli altyapı | ✅ |
| 1 | Yapılandırma: şema, birleştirme, `init`, `config` | ✅ |
| 2 | Ollama + OpenAI uyumlu adapter'lar, `ask`, `doctor` | ✅ |
| 3 | Durum veritabanı, günlük bütçe, sağlayıcı onayı, devre kesici, gizli bilgi taraması | ⏳ |
| 4 | Router, yeniden deneme ve **yedeğe geçiş**: internet yok → yerel Ollama, çöken API → sıradaki sağlayıcı | ⏳ |
| 5 | Görev dosyaları, doğrulayıcılar, git worktree, `edit`, `apply` | ⏳ |
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
