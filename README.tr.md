# Orkestra

[![CI](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml/badge.svg)](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![Lisans](https://img.shields.io/badge/lisans-MIT-green)

[English](README.md) · **Türkçe**

**Güçlü bir "şef" modelin (ör. Claude) işi birçok ucuz veya yerel "işçi" modele dağıtmasını, sonuçları doğrulamasını ve bir sağlayıcı çöktüğünde ya da kotası bittiğinde işin başka bir sağlayıcıda sürmesini sağlayan, bütçe farkındalıklı komut satırı aracı.**

> **Durum: erken sürüm, geliştirme aşamasında.** Aşağıdaki tablodaki her şey çalışıyor ve
> Linux, macOS ve Windows'ta ağsız çalışan yaklaşık 1.900 testle denetleniyor; ama gerçek
> kullanımda henüz az denendi. PyPI'de henüz yok. Ölçüldü: işi işçilere devretmek şefin
> tokenını **azaltmıyor**; bağlam süzgeci büyük bir işin maliyetini ~%20 düşürüyor. Güvenmeden
> önce [Bilinen sınırlar](#bilinen-sınırlar) bölümünü oku. Ne bitti, sırada ne var:
> [Yol haritası](#yol-haritası).

```text
Sen ──► Claude (şef: planlar, böler, denetler)
            │
            ▼
        Orkestra ──► router (kademe + bütçe + sağlık + kota)
            │
   ┌────────┼──────────────┬───────────────┐
   ▼        ▼              ▼               ▼
 Ollama  OpenRouter    Codex CLI     Antigravity CLI
 (yerel) (API)         (kod ajanı)   (kod ajanı)
            │
            ▼
   doğrulama ──► kısa sonuç zarfı (JSON) ──► şef sadece bunu okur
```

## Neden?

Güçlü modellerin kotası az; kotası bol modeller daha az güvenilir. Orkestra bunun için iki şey yapar:

- **İşi sürdürür.** Bir sağlayıcı çökmüş, çevrimdışı, bütçesi ya da kotası bitmişse aynı
  komutta sıradaki devralır; kotası biten sağlayıcı yenilenene kadar duraklatılır. Bütün bir
  oturum bir şeften diğerine devredilebilir (Claude → Codex → Antigravity).
- **Şefin bağlamını küçük tutar.** Hacimli ve kolay denetlenen işler (özet, docstring, test,
  veri çıkarma, mekanik refactor, uzun komut çıktısı) ucuz ya da yerel modellere gider. Çıktı
  otomatik denetlenir, şef onun yerine kısa bir JSON zarfı alır.

## Bugün çalışanlar

| Özellik | Komut |
|---|---|
| Kurulum sihirbazı (Ollama, Codex/agy/Claude ve API anahtarı değişkenlerini bulur) ya da örnek config | `orkestra init [--plain \| --defaults] [--project]` |
| Terminal arayüzü: durum, sağlayıcılar, bütçeler, profiller, onaylar, gece kuyruğu, devir özeti, ayarlar | `orkestra ui` |
| Herhangi bir OpenAI uyumlu servisi ekleme ya da OpenCode'dan alma | `orkestra providers add NAME --base-url URL --model ID`, `providers import opencode` |
| Sağlayıcı başına açık onay; sağlık ve kalan bütçeyle sağlayıcı listesi | `orkestra providers enable NAME`, `providers list` |
| İşçiye tek soru; bağlam dosyaları ve isteğe bağlı JSON Schema | `orkestra ask "…" [--context f] [--schema s.json] [--json]` |
| Kademe, bütçe, sağlık, kota, iş türü ve geçmiş başarıya göre yönlendirme; her aday neden seçildi ya da atlandı | `ask … --dry-run`, `routing.by_kind`, `routing.adaptive` |
| Aynı komutta yedeğe geçiş; kotası biten sağlayıcı yenilenene kadar duraklatılır | bkz. [Bir AI'nın kotası bitince](docs/guide.tr.md#bir-ainın-kotası-bitince) |
| Görev dosyaları: cevabı doğrula, geri bildirimle tekrar dene, üst kademeye geç | `orkestra run task.yaml [--json]` |
| Düzenleme görevleri: işçi kodu yalıtılmış bir git worktree'de değiştirir, karar senin testlerinin | `orkestra run edit.yaml`, `show RUN_ID --diff`, `apply RUN_ID`, `discard RUN_ID` |
| Kod ajanları (Codex CLI, Antigravity) işçi olarak, worktree içinde | `cli_agent` sağlayıcıları |
| Bağımlılıklı, paralel batch; önce maliyet tahmini; geçen koşuları uygulama | `orkestra batch tasks.yaml [--estimate]`, `apply --batch ID --only-ok` |
| Görev şablonları (docstring, tip ipucu, test, özet, yeniden adlandırma, çeviri, kendi şablonun) | `orkestra run --template docstring --files "src/*.py"`, `templates list` |
| İşçinin değişikliğini ikinci bir AI denetler; yalnız düşük riskliyi uygula | `orkestra review RUN_ID`, `apply RUN_ID --max-risk low` |
| Şef için uzun komut çıktısı: test/lint bulguları `dosya:satır` ile, gerisi özet | `orkestra exec -- pytest` |
| İşçi dosyaları ya da arama sonuçlarını okur, denetlenmiş `dosya:satır` işaretçileriyle cevaplar | `orkestra read FILE "soru"`, `orkestra find PATTERN` |
| Claude Code'un tokenı nereye gidiyor (dökümlerini okur, kota harcamaz) | `orkestra tokens [--since 7d]` |
| Şefin tek bakışta görünümü (en çok 15 satır) | `orkestra status` |
| Sonraki şef için devir dosyası ve özeti; başka bir şefe devretme | `orkestra handoff init`, `handoff show --brief`, `handoff to codex` |
| Gece kuyruğu: şimdi ekle, sonra yerel modellerle çalıştır; belirli saatte ya da maliyette dur | `orkestra queue add FILE`, `queue run --until 07:00 --notify`, `queue remove --finished` |
| Batch ya da kuyruk bitince bildirim: masaüstü ve telefon (ntfy, kendi sunucun da olur) | `--notify`, `orkestra notify test` |
| İşçiler nasıl gitti: başarı oranı, deneme, token, maliyet, süre | `orkestra stats [--since 7d]` |
| Günlük bütçeler (token, USD, istek, koşu), yerel gece yarısı sıfırlanır | `orkestra budget` |
| Ortam denetimi: config, sağlayıcılar, anahtarlar, modeller, onay, kota, git, kurulum | `orkestra doctor [--warm]` |
| Eski worktree'leri, koşu kayıtlarını, veritabanı satırlarını ve askıda rezervasyonları temizleme | `orkestra gc [--dry-run]` |
| Claude skill: Claude ne zaman ve nasıl Orkestra'ya devreder | [`skill/orkestra/SKILL.md`](skill/orkestra/SKILL.md) |
| Arayüz Türkçe, İngilizce, Almanca, İspanyolca ya da Fransızca | `--lang en\|tr\|de\|es\|fr`, `ORKESTRA_LANG` |

**Sağlayıcılar:**

- **Ollama**, kendi API'siyle (`num_ctx` her istekte gönderilir; uzun istem sessizce kesilmez).
- **Herhangi bir OpenAI uyumlu API**: OpenRouter, LM Studio, vLLM, kendi sunucun (`providers add`). OpenRouter'ın bildirdiği maliyet okunur; diğerlerinde maliyet `price_per_mtok`'tan gelir.
- **Kod ajanları**, `cli_agent` sağlayıcısı olarak: Codex CLI, Antigravity (`agy`, deneysel: komut satırı hâlâ değişiyor) ya da başka bir komut satırı ajanı (`generic`).

## Kurulum

Gereksinimler: Python 3.11+, git, [uv](https://docs.astral.sh/uv/). İsteğe bağlı: Ollama, bir API
anahtarı (OpenRouter ya da başka bir OpenAI uyumlu servis), Codex CLI ya da Antigravity.

```bash
uv tool install git+https://github.com/BurakYildizGameDev/orkestra
# masaüstü bildirimiyle:
uv tool install git+https://github.com/BurakYildizGameDev/orkestra --with "desktop-notifier>=6.0,<7"
orkestra --help
```

Henüz PyPI'de yok (`orkestra-cli` adıyla planlanıyor). Bir klondan `uv sync` ve
`uv run orkestra --help` de çalışır. Bir klonu `uv tool install --editable .` ile kurarsan
`orkestra` komutu o klonda hangi dal açıksa onu çalıştırır: klonu `main`'de tut (değilse
`orkestra doctor` uyarır).

## Hızlı başlangıç

```bash
# 1. API anahtarları ortam değişkenine gider; config'te sadece değişkenin ADI durur.
export OPENROUTER_API_KEY="..."      # PowerShell: $env:OPENROUTER_API_KEY="..."

# 2. ~/.orkestra/config.yaml'ı kur: sihirbaz Ollama'yı ve modellerini, codex/agy/claude'u ve
#    hangi anahtar değişkenlerinin tanımlı olduğunu (değerlerini asla) bulur; sonra sağlayıcıları,
#    kademeleri, bütçeleri ve onayları sorar. Var olan dosyadaki yorumların korunur.
orkestra init                        # --plain: aynı sorular; --project: ./orkestra.yaml

# 3. Her şeyi denetle ve kullanmak istediğin sağlayıcılara izin ver
orkestra doctor
orkestra providers enable ollama
orkestra providers enable openrouter    # adresi ve anahtar değişkenini gösterir, sonra sorar

# 4. Sor; kimin cevap vereceğini ve nedenini gör
orkestra ask "Bu fonksiyon ne yapıyor?" --context src/util.py
orkestra ask "Tek satırda özetle" --dry-run

# 5. Ya da görevi denetimleriyle birlikte yaz ve çalıştır
orkestra run examples/tasks/summarize-readme.yaml --json
```

Her sağlayıcının bir **kademesi** var (1 küçük/ücretsiz … 3 en güçlü). Router önce profilin izin
verdiği en düşük kademeyi dener, üst kademeler yedek kalır. Kapalı, onaysız, duraklatılmış,
günlük bütçesini aşacak ya da bağlamda gizli bilgi varken uzak olan sağlayıcı atlanır.
İnternet yoksa `ask` aynı komutta yerel Ollama'dan cevap verir. Ayrıntısı:
[Yönlendirme ve yedeğe geçiş](docs/guide.tr.md#yönlendirme-ve-yedeğe-geçiş).

Claude'un Orkestra'yı kullanması için skill'i kur:

```bash
mkdir -p ~/.claude/skills && cp -r skill/orkestra ~/.claude/skills/
```

## Bilinen sınırlar

- **Devretmek Claude tokenını azaltmıyor; bağlam süzgeci biraz azaltıyor.** Benchmark
  (Faz 13, Claude Code 2.1.329 + Opus 5.5, Windows 11, i9-13900HX, 32 GB, RTX 5070 Ti 12 GB;
  ayrıntı [`bench/README.md`](bench/README.md#results)):

  | Koşu | Geçen | Claude token / görev | Claude maliyeti / görev |
  |---|---|---|---|
  | 20 küçük görev, yalnız Claude (2 tur) | 20/20 | 9,1k | $0,117 |
  | aynısı, skill ile (Claude hiç devretmedi) | 20/20 | 11,4k (+%26) | $0,136 (+%16) |
  | aynısı, agy'ye devret denince (1 tur) | 20/20 | 15,7k (+%73) | $0,197 (+%68) |
  | şefsiz Orkestra, yerel qwen2.5-coder:14b | 7,5/20 | – | – |
  | büyük görev (~1.200 satırlık proje, 160 KB log), yalnız Claude (2 tur) | 2/2 | 87,4k | $1,38 |
  | aynısı, bağlam süzgeciyle (`exec`/`read`/`find`) | 2/2 | 76,9k (−%12) | $1,10 (−%20) |
  | aynısı, + devir ve çapraz denetim | 2/2 | 76,7k (−%12) | $1,19 (−%13) |

  Projenin hedeflediği %25 tasarruf tutmadı. Orkestra'nın Claude kullanıcısına verdiği şey
  kesintisizlik (biri bitince başka sağlayıcı ya da şef devralır) ve bağlam süzgeci (büyük
  görevde bağlamı yeniden okuma −%46); devretmek küçük görevde de büyük görevde de şefe
  kazandırdığından fazlasına mal oluyor.
- **Gerçek kullanım az.** Gece kuyruğu, bildirimler, terminal arayüzü ve sihirbaz testlerle
  denetleniyor ama gerçek modellerle, gerçek terminallerde az kullanıldı. Kod AI yardımıyla
  yazıldı ve denetlendi. Pürüz bekle; lütfen
  [bildir](https://github.com/BurakYildizGameDev/orkestra/issues).
- **Öğrenen yönlendirme veri ister.** `routing.adaptive` bir kademeyi ancak aynı etiketten
  `min_samples` (varsayılan 10) koşudan sonra yeniden sıralar; o zamana kadar nötrdür.
- **Antigravity (`agy`) desteği deneysel**: komut satırı ve çıktısı hâlâ değişiyor.
- **Yerel modeller bilgisayarı yorar.** Terminaller arasında aynı anda tek ağır yerel model
  çalışır; `doctor` RAM/GPU'na göre model boyutu önerir.
- **Çeviriler:** Almanca, İspanyolca ve Fransızca AI ile çevrildi; ana dili konuşan biri
  henüz gözden geçirmedi.
- **Henüz PyPI'de yok** ve sürüm numarası yok (bkz. yol haritası).

## Güvenlik

- API anahtarları config dosyalarında asla tutulmaz, sadece ortam değişkeninin adı; `doctor` değişkenin tanımlı olup olmadığını söyler, değerini asla.
- Sağlayıcı hata mesajları temizlenir; API'nin geri yansıttığı bir anahtar çıktıya ulaşmaz.
- Açık onay olmadan hiçbir sağlayıcı kullanılmaz; onay verinin nereye gittiğine ve neyin çalışabileceğine bağlıdır (adres, anahtar değişkeni, başlıklar, komut, sandbox, modeller); biri değişirse yeniden sorulur.
- Bağlam ve istem gizli bilgiye karşı taranır; böyle bir bağlam `--allow-secrets` vermeden uzak sağlayıcıya gitmez. `.orkestraignore` ile eşleşen dosyalar asla gönderilmez.
- `~/.orkestra/runs/` altına yazılan her şey maskelenir. Kod ajanları için `danger-full-access` sandbox'ı reddedilir.
- `command` doğrulayıcısı senin yazdığın komutu çalışma klasöründe çalıştırır; kabuk yalnız `shell: true` ile.
- Telemetri yok. Her şey senin bilgisayarında ve seçtiğin sağlayıcılarda kalır.

## Belgeler

- [Rehber](docs/guide.tr.md): yönlendirme ve yedeğe geçiş, görev dosyaları, düzenlemeler, kod
  ajanları, kota ve kesintisizlik, batch, gece kuyruğu, şef araçları, çapraz denetim,
  `exec`/`read`/`find`, token haritası, yapılandırma, sonuç zarfı ve çıkış kodları.
- [Tarifler](docs/recipes.tr.md): hazır iş akışları.
- [Örnek config](examples/orkestra.example.yaml) ve [örnek görevler](examples/tasks/).
- [`docs/PROGRESS.md`](docs/PROGRESS.md): her fazda ne yapıldı; [`docs/DECISIONS.md`](docs/DECISIONS.md): plandan her sapma ve gerekçesi.

## Yol haritası

| Faz | Konu | Durum |
|---|---|---|
| 0–4 | İskelet, config, Ollama/OpenAI adapter'ları, bütçe, onay, devre kesici, yedeğe geçişli router | ✅ |
| 5–6 | Görev dosyaları ve doğrulayıcılar, worktree'ler, düzenleme görevleri, kod ajanları (Codex, Antigravity) | ✅ |
| 6b | MCP sınırları; Unity açıkken elle testler | ⏳ |
| 7–8 | Batch, maliyet tahmini, `stats`; şef araçları (`status`, şablonlar, önbellek, `review`, `map`) | ✅ |
| 9 | Claude skill; ucuz modeller için SEARCH/REPLACE düzenleme | ✅ |
| 10 | Şef devri (Claude ↔ Codex ↔ Antigravity) | ✅ |
| 11 | Terminal arayüzü, kurulum sihirbazı, 5 dil | ✅ |
| 12 | Gece kuyruğu, bildirimler, öğrenen yönlendirme | ✅ |
| 13a–c | Benchmark aracı, 20 görev, ilk deneme | ✅ |
| 13f–o | Kota kesintisizliği, token haritası, bağlam süzgeci (`exec`/`read`/`find`), kısa oturumlar, kota tahmini, işe göre model, çapraz denetim, Claude dışı şef, `providers add` | ✅ |
| düzeltmeler | `gc` ile veritabanı temizliği, dosya bölme ve bu README bitti; sırada gerçek modellerle elle kullanım turu | ⏳ |
| 13d, 13e, 13g, 13p | Tam benchmark turları, büyük görev deneyi, kısa skill | ✅ |
| 14 | Paketleme, belgeler, PyPI sürümü | ⏳ |

## Geliştirme

```bash
uv sync
uv run pytest                 # ağsız; gerçek servisler yalnız: uv run pytest -m live
uv run ruff check . && uv run ruff format --check .
uv run pyright
```

CI; Linux, macOS ve Windows'ta Python 3.11, 3.12 ve 3.13 ile çalışır. Bu repoda çalışan kodlama
ajanları için kurallar [`AGENTS.md`](AGENTS.md) dosyasında.

## Lisans

[MIT](LICENSE)
