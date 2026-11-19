# Orkestra

[![CI](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml/badge.svg)](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![Lisans](https://img.shields.io/badge/lisans-MIT-green)

[English](README.md) · **Türkçe**

**Güçlü bir "şef" modelin (ör. Claude) işi birçok ucuz veya yerel "işçi" modele dağıtmasını, sonuçları doğrulamasını ve bir sağlayıcı çökünce diğerine geçmesini sağlayan, bütçe farkındalıklı komut satırı aracı.**

> **Durum: geliştirme aşamasında.** 14 fazın 0–4'ü ve 5. fazın ilk iki kısmı bitti: proje iskeleti, yapılandırma, Ollama ve OpenAI uyumlu adapter'lar, `ask`, `doctor`, günlük bütçe, sağlayıcı onayı, devre kesici, gizli bilgi taraması, yeniden deneme + yedeğe geçişli router doğrulama, geri bildirimle tekrar deneme ve üst kademeye geçişli görev dosyaları, ve `show`, `apply`, `discard`, `gc` ile yalıtılmış git worktree'leri. İşçilerin (bu worktree'lerde) kod değiştirdiği düzenleme görevleri ve diğerleri [yol haritasında](#yol-haritası). Bu README sadece bugün çalışan özellikleri anlatır.

```
Sen ──► Claude (şef: planlar, böler, denetler)
            │
            ▼
        orkestra ──► router (kademe + bütçe + sağlık)      ← Faz 3–4
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

Güçlü modellerin kotası azdır, bol kotalı modeller ise daha az güvenilirdir. Orkestra hacimli ama
kontrolü kolay işleri (özet, docstring, test, veri çıkarma, mekanik refactor) ucuz veya yerel
modellere gönderir, çıktıyı otomatik kontrol eder ve şefe tüm çıktı yerine kısa bir JSON zarfı
verir. Bir sağlayıcı çöktüğünde, bütçesi bittiğinde veya internet olmadığında sıradaki devreye girer.

## Bugün çalışanlar

| Özellik | Komut |
|---|---|
| Kurulum sihirbazı (Ollama, Codex/agy/Claude ve API anahtarı değişkenlerini bulur) ya da örnek config | `orkestra init [--plain \| --defaults] [--project] [--force]` |
| Terminal arayüzü: durum, sağlayıcılar (aç/kapat, test), bütçeler, profiller, onaylar, gece kuyruğu, devir özeti, dil ve bildirimler; Türkçe, İngilizce, Almanca, İspanyolca ya da Fransızca | `orkestra ui` |
| Birleştirilmiş config ve kaynakları, okunur hatalarla doğrulama | `orkestra config show [--json]`, `orkestra config validate` |
| İşçi modele tek soru; bağlam dosyaları ve isteğe bağlı JSON Schema | `orkestra ask "…" [--context f] [--schema s.json] [--json]` |
| Profil, gizlilik ve yedeğe geçişli yönlendirme; her sağlayıcının neden seçildiğini/elendiğini görme | `ask [--profile p] [--tier n] [--local-only] [--dry-run]` |
| Öğrenen yönlendirme: aynı kademede, aynı etiketli görevlerde en başarılı model öne geçer (`min_samples` koşudan sonra); `--dry-run` skoru gösterir | `routing.adaptive: true` |
| İşe göre model: özet ve arama küçük ya da ücretsiz modelde, kod büyük modelde, her kademe içinde (`routing.by_kind`); bilgisayarda aynı anda tek ağır yerel model, terminaller arasında da; `doctor` RAM/GPU'na göre model boyutu önerir | `routing.by_kind` |
| Bir sağlayıcının kotası bitince (Codex, agy, OpenRouter, OpenAI, Ollama bulut): yenilenene kadar duraklatılır, iş sıradakiyle sürer | `quota_pause_s`, bkz. [Bir AI'nın kotası bitince](#bir-ainın-kotası-bitince) |
| Görev dosyaları (YAML/JSON): cevabı doğrula, geri bildirimle tekrar dene, üst kademeye geç | `orkestra run gorev.yaml [--dry-run] [--json]` |
| Düzenleme görevleri: işçi kodu yalıtılmış worktree'de değiştirir, karar senin testlerinin | `orkestra run duzenle.yaml`, sonra `show --diff`, `apply` |
| Batch: bağımlılıklarıyla birçok görev, paralel, her sağlayıcı kendi concurrency sınırında | `orkestra batch tasks.yaml [--parallel N] [--fail-fast] [--notify] [--json]` |
| Batch'ten önce maliyet tahmini (hiçbir şey gönderilmez); pahalı batch önce sorar | `orkestra batch tasks.yaml --estimate [--json]`, `--yes-cost` |
| Bir batch'in geçen koşularını çalıştıkları sırayla uygula, çakışmada dur | `orkestra apply --batch <batch_id> --only-ok [--json]` |
| İşçiler nasıl gitti: sağlayıcı ve etiket başına başarı oranı, deneme, token, maliyet, süre | `orkestra stats [--since 7d] [--json]` |
| Claude Code'un tokenı nereye gidiyor: pahalı araç çağrıları, türlere göre pay, bağlamın büyümesi, önbellek kaçırma (dökümleri okur, kota harcamaz) | `orkestra tokens [--session id \| --since 7d] [--project p] [--top n] [--json]` |
| Bir komutu çalıştır, yalnız işe yarayanı al: kısa çıktı olduğu gibi, pytest/ruff/pyright/derleyici çıktısı `dosya:satır` bulgularıyla, diğerleri özetlenerek; tam çıktı günlükte | `orkestra exec [--max-lines n] [--no-model] [--timeout s] [--json] -- <komut>` |
| Dosyaları ya da arama sonuçlarını bir işçiye okut, denetlenmiş `dosya:satır` işaretçileriyle cevap al; modelsiz ara; proje fihristini her commit'ten sonra güncel tut | `orkestra read DOSYALAR... "<soru>"`, `orkestra find DESEN [--regex] [--glob g] [--ask soru]`, `orkestra map --install-hook` |
| İşçi olarak kod ajanları (Codex CLI, Antigravity): worktree'de, süreç ağacı temizliğiyle | `cli_agent` sağlayıcıları |
| Şef için tek bakışta durum (en fazla 15 satır): uygulanmamış koşular, gece kuyruğu, bugünkü bütçe, duraklatılmış sağlayıcılar | `orkestra status [--json]` |
| Gece kuyruğu: görev veya batch'leri şimdi ekle, sonra (gece, yerel modellerle) çalıştır; aynı anda tek çalıştırma, belirli saatte veya maliyette durur | `orkestra queue add <dosya> [--profile p]`, `queue list`, `queue remove <id>`, `queue run [--until 07:00] [--max-cost-usd X] [--notify]` |
| Batch veya kuyruk bitince bildirim: masaüstü (isteğe bağlı ek paket) ve telefon (ntfy), yalnız sayılar | `--notify`, `orkestra notify test` |
| Görev şablonları (docstring, type-hints, tests, summarize, rename-refactor, translate ya da kendi şablonun): dosya başına bir görev | `orkestra run --template docstring --files "src/*.py" [--param k=v]`, `orkestra templates list\|show` |
| Aynı `ask` tekrar önbellekten gelir: hiçbir şey gönderilmez, maliyeti yok | `--no-cache`, `orkestra cache clear` |
| Devir dosyası: sıradaki yapay zekâ şefinin devam etmesi için gerekenler; gerçek git durumu, uygulanmamış koşular ve bütçeyle kısa özet | `orkestra handoff init`, `update --section … --add/--set`, `check`, `show [--brief] [--json]`, `to <şef> [--print-only] [--allow-dirty]`, `install-hook` |
| Bir koşunun envelope'u, tam çıktısı, log'u veya değişikliği | `orkestra show <run_id> [--output\|--log\|--diff] [--json]` |
| Koşunun değişikliğini çalışma ağacına al ya da at | `orkestra apply <run_id>`, `orkestra discard <run_id>` |
| Sahipsiz worktree, eski koşu kaydı ve askıda rezervasyonları temizle | `orkestra gc [--older-than 30] [--dry-run]` |
| Ortam kontrolü: config, sağlayıcı erişimi, API anahtarı değişkenleri, Ollama modelleri, onaylar, beklemedeki sağlayıcılar, git, codex/agy | `orkestra doctor [--json] [--warm]` |
| Sağlayıcı başına açık onay (vermeden önce ne yapabileceği gösterilir) | `orkestra providers enable <ad>`, `providers disable <ad>` |
| Sağlayıcılar: onay, sağlık ve kalan bütçe | `orkestra providers list [--json]` |
| Günlük bütçe (token, USD, istek, koşu), yerel gece yarısı sıfırlanır | `orkestra budget [--json]` |
| Claude skill: Claude işi Orkestra'ya ne zaman ve nasıl verir | `skill/orkestra/SKILL.md` |
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
# 1. API anahtarları ortam değişkenine gider; config'te sadece değişkenin ADI durur.
export OPENROUTER_API_KEY="..."      # PowerShell: $env:OPENROUTER_API_KEY="..."

# 2. Kur (~/.orkestra/config.yaml): terminalde sihirbaz Ollama'yı ve modellerini,
#    codex/agy/claude'u ve hangi anahtar değişkenlerinin tanımlı olduğunu bulur (değerlerini
#    asla okumaz), sonra sağlayıcıları, kademeleri, bütçeyi ve onayları sorar. Var olan
#    dosyadaki yorumların korunur.
uv run orkestra init                 # --plain: aynı sorular; --project: ./orkestra.yaml
uv run orkestra init --defaults      # sorusuz: bulduklarını açar, hiçbir onay vermez

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

- kapalıysa veya API anahtarı değişkeni tanımlı değilse (kod ajanı: programı kurulu değilse)
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
kind: ask                    # ask | edit (aşağıda "Düzenleme görevleri")
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

## Düzenleme görevleri: işçiler kod değiştirir

Düzenleme (edit) görevi işçiden dosya değiştirmesini ister. Bir worktree'de çalışır (aşağıya
bak), yani sonucu uygulayana kadar çalışma kopyan olduğu gibi kalır.

```yaml
id: fix-add
kind: edit
prompt: calc.py içindeki add()'i testler geçecek şekilde düzelt. Testleri değiştirme.
context:
  files: [calc.py]           # işçinin değiştirebileceği dosyalar
verify:
  - type: command
    run: "python -m pytest -q"
  - type: protect_paths      # testi değiştirerek geçirmek başarısızlık sayılır
    paths: ["tests/**"]
allow_new_files: true        # varsayılan; false: sadece bağlamdaki dosyalar değişebilir
```

API işçileri iki biçimden biriyle cevap verir. Biçimi `edit_format` seçer (görev dosyasında ya
da config'te model bazında). Varsayılan `auto`, dosya boyutuna göre seçer:

- **`whole`** (auto'da `security.max_api_edit_lines`'a, 400 satıra kadar): dosyanın tamamı JSON
  olarak, `{"files": [{"path", "content"}], "note"}`.
- **`replace`** (auto'da 400 satırdan büyük dosyalarda): sadece değişen yerler,
  ara/değiştir (SEARCH/REPLACE) blokları olarak:

```
calc.py
<<<<<<< SEARCH
    return a - b
=======
    return a + b
>>>>>>> REPLACE
```

`replace` ile dosyanın geri kalanı hiç yeniden yazılmaz, böylece büyük dosyalar da ucuz
modellere gidebilir (o boyutta tam dosya cevapları kesilir). SEARCH, dosyada tam satırlar olarak
tek bir yere uymalıdır (satır sonu ve satır sonundaki boşluklar önemli değil). Boş SEARCH yeni
dosya oluşturur. Neden her zaman `replace` değil de `auto`: elle denemelerimizde 14B yerel bir
model küçük dosyada tam dosya biçimiyle daha iyi sonuç verdi, bloklarına da zaten büyük
parçalar kopyaladı (`docs/DECISIONS.md`, D-051). Modellerin ürettiği unified diff'ler çok sık
bozulduğu için kullanılmaz. Orkestra sonra:

1. blokları (ya da JSON'u) kod çiti veya etrafında metin olsa da alır; bulunamayan SEARCH
   (dosyanın en yakın satırları geri gönderilir), birden çok yere uyan SEARCH, bozuk ya da
   kesik cevap geri bildirim olarak işçiye döner (`edit_format` kontrolü);
2. her yolu denetler: göreli, proje içinde, `..` ve `.git` yok, `forbid_paths`'e uymuyor ve ya
   bağlamdaki bir dosya ya da yeni bir dosya. İşçiye gösterilmemiş bir dosyanın üstüne asla
   yazılmaz;
3. dosyaları orijinal satır sonlarıyla (CRLF/LF) yazar ve kontrollerini worktree'de çalıştırır.
   Kontrollerin geride bıraktığı dosyalar (`__pycache__`, derleme çıktısı) değişikliğe girmez;
4. kontrol başarısızsa: her görevde olduğu gibi geri bildirim, senin dosyalarından yeniden
   deneme, üst kademeye geçiş.

Cevap çıktı sınırında kesilirse dosya o model için çok büyüktür: koşu doğrudan kademe 3'e geçer.
Sadece açıkça `edit_format: whole` seçilirse `security.max_api_edit_lines`'tan (400) uzun
dosyalar API işçilerine hiç verilmez; onları kod ajanları yerinde düzenler. Envelope'ta `edit_format` ve
`changes: {files, insertions, deletions, patch_path}` var, `run --dry-run` her adayın biçimini
gösterir; sonra:

```bash
orkestra show <run_id> --diff      # incele
orkestra apply <run_id>            # al
```

Kontrolleri geçmeyen koşu, değişikliğe bakabilmen için worktree'sini korur ama `apply` o zaman
`--force` ister. Değişikliksiz biten koşu worktree'sini siler. UTF-8 olmayan, git'in ignore
ettiği veya `protect_paths`/`forbid_paths`'e uyan bağlam dosyaları işçiye sadece okunur
gösterilir. Görevi yapamayan işçi `CANNOT_DO: <neden>` (`whole` ile `{"cannot_do": "<neden>"}`)
der ve koşu hemen üst kademeye geçer.

Koşu sırasında Ctrl+C bütçe rezervasyonunu serbest bırakır, `error: interrupted` içeren bir
envelope yazar ve worktree'yi korur.

## Kod ajanları: Codex CLI ve Antigravity

`cli_agent` sağlayıcısı gerçek bir kod ajanını alt süreç olarak çalıştırır, genelde kademe
3'te. Düzenleme görevinde doğrudan koşunun worktree'sinde çalışır; `ask` görevinde projeni
salt okunur sandbox ile okur. Gerisi API işçileriyle aynı: karar senin kontrollerinin,
başarısızlıkta geri bildirim, sonunda `show --diff` ve `apply`.

```yaml
providers:
  codex:
    type: cli_agent
    command: codex               # PATH'te aranır (Windows'ta codex.cmd de olur)
    tier: 3
    sandbox: workspace-write     # salt okunur ajanlar düzenleme görevi yapamaz
    model: null                  # null = ajanın varsayılanı
    timeout_s: 1200              # varsayılan: 30 dakika
    budget: {daily_runs: 20}
  agy:
    type: cli_agent
    command: agy
    experimental: true           # agy deneysel: iki satır da gerekli
    enabled: true
```

- İstem stdin'den (codex) veya koşu kayıtlarının yanındaki bir dosyadan (agy) gider, komut
  satırından asla; uzun istemler Windows'ta da çalışır. Ajanın çıktısı
  `~/.orkestra/runs/<run_id>/attempts/<n>/` altındaki dosyalara yazılır.
- Zaman aşımında veya Ctrl+C'de ajan **ve bütün alt süreçleri** durdurulur.
- Codex `codex exec --sandbox workspace-write|read-only --json --output-last-message …` ile
  çalışır; `danger-full-access` asla kullanılmaz. agy kendi `--sandbox` print modunda çalışır.
  Kendi oturumların (`codex login`) kullanılır; Orkestra onları okumaz.
- Diff her zaman koşunun baseline'ına göre alınır, ajanın kendi commit'leri de sayılır.
- Deponun durumu her ajan koşusundan önce ve sonra denetlenir. Orada bir şey değiştiyse
  `workspace_scope` kontrolü başarısız olur ve uyarı alırsın (Orkestra bunu geri almaz).
- Deponun ajan dosyaları (`AGENTS.md`, `.codex/` …) worktree'de de vardır ve ajanı her zamanki
  gibi yönlendirir.
- Geri bildirim denemesi baştan başlamaz, ajanın önceki değişikliğinden devam eder.
- Başka bir program da olur (`kind: generic`: istem stdin'den, cevap stdout'a) ama **sandbox'ı
  yoktur**: senin yetkilerinle çalışır (`ask`'te proje dizininde).
- `doctor` ajanın sürümünü gösterir; codex oturumu açık değilse ve agy'nin `permissions.deny`
  listesi `rm`/`sudo` engellemiyorsa uyarır (agy print modunda araç çağrılarını kendisi onaylar).
- Kurulu olmayan program, `experimental: true` olmadan agy ve düzenleme görevi için salt okunur
  ajan, `--dry-run`'da nedeniyle listelenir. Ajanların fiyatı yok: `daily_runs` kullan.
- **agy ve MCP sunucuları:** agy, bir şey göndermeden önce `~/.gemini/config/mcp_config.json`
  içindeki bütün MCP sunucularını (`disabled` işaretli olanlar dahil) başlatır ve hepsi
  bağlanana kadar bekler. Bağlanamayan bir sunucu (ör. Unity editörü kapalıyken Unity'nin
  relay'i) her koşuyu zaman aşımına kadar bekletirdi. Orkestra, agy `mcp_wait_s` kadar
  beklediğinde (varsayılan 60 saniye; agy 30 sn'de bir raporlar; `0` hiç durdurmaz) koşuyu
  sunucunun adını veren bir hatayla durdurur ve sıradaki sağlayıcıya geçer; `doctor` ve
  `providers enable` `disabled` kayıtlar için uyarır. Böyle bir sunucuyu etkileşimli kullanım için
  tutmak istersen, uygulaması çalışmıyorsa hemen kapanan küçük bir betikle başlat, ör.
  Windows'ta (`command: "cmd.exe"`, `args: ["/d", "/c", "<betik>.cmd", "--mcp"]`):
  ```bat
  @echo off
  "%SystemRoot%\System32\tasklist.exe" /FI "IMAGENAME eq Unity.exe" /NH | "%SystemRoot%\System32\find.exe" /I "Unity.exe" >nul || exit /b 1
  "%USERPROFILE%\.unity\relay\relay_win.exe" %*
  ```

codex-cli 0.160.0 ve agy 1.5.5 ile denendi (`--log-file` kullanılmadan önce agy 1.5.3).

## Bir AI'nın kotası bitince

Birden fazla sağlayıcının amacı, biri durduğunda işin sürmesi. Sen müdahale etmeden her
durumda olan şu:

| Biten ne | Orkestra ne yapar |
|---|---|
| **Bağlantı** (internet yok, DNS, bağlantı reddi) | 0,5 sn sonra bir kez daha dener, sonra aynı komutta sıradaki sağlayıcıya geçer; yerel model yaklaşık yarım saniyede devralır |
| **API hataları** (zaman aşımı, 5xx, kısa istek sınırları) | bekleyerek yeniden dener; art arda 3 hatada sağlayıcı 5 dakika duraklatılır |
| **Senin bütçen** (`daily_usd`, `daily_tokens`, `daily_runs` …) | sağlayıcı yerel gece yarısına kadar kullanılmaz; iş sıradakine gider |
| **Sağlayıcının kotası** (Codex ya da agy kullanım sınırı, Gemini `RESOURCE_EXHAUSTED`, OpenRouter'ın günlük ücretsiz istekleri, OpenAI `insufficient_quota`, Ollama bulut kullanım sınırları) | yeniden denenmez: sağlayıcı **kotası yenilenene kadar duraklatılır** (mesajdaki süre, yoksa `quota_pause_s`, varsayılan 1 saat) ve görev aynı komutta sıradakine geçer; sonraki görevler, batch'in geri kalanı ve gece kuyruğu onu bir daha denemez |
| **Şefin kotası** (Claude'un kendi sınırı) | `orkestra handoff to <şef>` işi kısa bir özetle sıradaki şefe devreder (bkz. Şef araçları) |

```yaml
providers:
  agy:
    type: cli_agent
    command: agy
    quota_pause_s: 7200          # kota mesajında yenilenme zamanı yoksa (varsayılan 3600)
```

- Kota mesajına yalnız zaten başarısız olan koşuda bakılır (sıfır olmayan çıkış kodu, cevap
  yok, HTTP 429), ajanlarda da yalnız çıktının son satırlarında; kotalardan söz eden bir
  cevap ya da test çıktısı hiçbir şeyi duraklatmaz. Orkestra'nın tanımadığı bir mesajda da
  iş eskisi gibi sıradakine geçer; yalnız duraklatma olmaz.
- Kısa bir istek sınırı ("429 Too Many Requests") kota bitmesi sayılmaz: eskisi gibi yeniden
  denenir ya da sayılır (art arda 3'ü 5 dakika duraklatır).
- Hesabın değil tek modelin kotası (OpenRouter'ın günlük ücretsiz modelleri, Gemini'nin
  model başına kotaları) yalnız o modeli atlatır; sağlayıcının diğer modelleri çalışır.
- Mesajdaki yenilenme zamanı genel bir `retry-after` başlığından önce gelir.
- Zarftaki `failovers` sağlayıcının kendi sözleriyle `ProviderQuotaExhausted` yazar;
  `status`, `providers list`, `doctor` ve `--dry-run` "kota bitti, duraklatıldı (açılış: 14:30)"
  gösterir (haftalık sınırda tarihle). `orkestra providers enable <ad>` duraklatmayı hemen
  kaldırır.
- `batch --notify` ve `queue run --notify`, o batch ya da kuyruk koşusunda kotası biten
  sağlayıcıları ve açılış saatlerini tek satırla ekler, başka bir şey değil.
- Ağsız ölçüm (`tests/integration/test_continuity_cli.py`): 10 görevlik bir batch'te 4.
  görevde kotası biten bir ajan → **10/10 görev biter**, 4–10 Ollama'da; ajan 4 kez başlatılır,
  kota mesajından sonra bir daha hiç; geçişin bedeli bir başarısız ajan koşusu, bekleme yok.

### Bitmeden önce

Orkestra ileriye de bakar. Her sağlayıcının son bir saatteki hızını sınırıyla karşılaştırır
ve sınıra ne zaman varılacağını söyler:

- **Bilinen sınırlar** senin `budget`'ındır (`daily_runs` …). **Öğrenilen sınırlar** kimsenin
  yazmadığı kotalar içindir, örneğin bir ajanın aboneliği: her biten kota, penceresinin
  başından beri ne kadar kullanıldığını kaydeder; son 5'inin ortancası sınır olur.
- Bir saat içinde bitecekse ya da sınırın %10'u veya daha azı kaldıysa sağlayıcının
  **kotası azalıyor** demektir. `status`, `doctor` ve `--notify` mesajları bunu söyler
  ("kotası azalanlar: agy: ~40 dk (runs 18/20)"). Router da onu **kendi kademesinde en sona**
  alır: kota bitmeden iş ötekilere kayar, hiçbir şey engellenmez. `--dry-run --json`
  `quota_low` gösterir.

```yaml
forecast:
  enabled: true        # false: uyarı yok, sıra değişmez
  window_s: 3600       # hız bu süre üzerinden okunur
  warn_within_s: 3600  # sınır bu kadar yakınsa "azalıyor"
  low_share: 0.1       # ... ya da sınırın bu payı kaldıysa
  learn_events: 5      # öğrenilen sınır, son bu kadar biten kotanın ortancası
```

**Şefin kendi kotası.** Claude Code kullanım pencerelerini (5 saat, 7 gün) durum satırı
komutuna verir. Orkestra'nın satırını ve kancasını bir kez bağla:

```bash
orkestra statusline config   # ~/.claude/settings.json'a girecek parçayı yazdırır
```

Satır şöyle görünür: `Claude 5h 72% (~40 dk) · 7d 40% | orkestra: agy ~20 dk (runs 18/20)`. Bir
pencere `handoff.prepare_at_percent`'i (varsayılan 85) geçince ya da bir saat içinde bitecekse
kanca Claude'a, pencere başına bir kez, devir dosyasını güncelleyip commit etmesini söyler.
Sınır sonra biterse yalnız `orkestra handoff to agy` yazarsın. İki komut da yaklaşık 0,3 sn'de
açılır, çünkü CLI'nin geri kalanını yüklemezler.

## Batch: birçok görev birden

```yaml
parallel: 4                  # aynı anda çalışan görev (varsayılan 4; --parallel ezer)
tasks:
  - id: docs-a
    kind: edit
    prompt: src/a.py'ye docstring ekle; kodu değiştirme.
    context: {files: [src/a.py]}
    verify: [{type: command, run: "python -m pytest -q"}]
  - id: docs-b
    kind: edit
    prompt: src/b.py'ye docstring ekle; kodu değiştirme.
    context: {files: [src/b.py]}
    verify: [{type: command, run: "python -m pytest -q"}]
  - id: ozet
    kind: ask
    prompt: src/a.py ve src/b.py'nin ne yaptığını özetle.
    context: {files: [src/a.py, src/b.py]}
    depends_on: [docs-a, docs-b]
```

```bash
orkestra batch tasks.yaml --json              # tek JSON belgesi: batch_id, results, totals
orkestra batch tasks.yaml --parallel 2 --fail-fast
```

- Hiçbir şey başlamadan önce her görev, tek görev dosyası gibi denetlenir. Tekrarlanan
  kimlikler ve bilinmeyen ya da döngüsel `depends_on` kod 2 verir.
- `--parallel` ne derse desin, her sağlayıcıya bütün batch boyunca aynı anda en fazla kendi
  `concurrency` değeri kadar istek gider (Ollama: varsayılan 1).
- Bağlam dosyaları kesişen düzenleme görevleri uyarıyla sırayla çalışır. İkisi de kendi
  worktree'sinde senin dosyalarından başlar, bu yüzden ikisini birden uygulamak çakışabilir.
- Bağımlılığı `ok` bitmeyen görev `skipped` olur. `--fail-fast` ilk başarısızlıktan sonra yeni
  görev başlatmaz. Çöken bir görev `error` olur, diğerleri devam eder.
- Bağımlılık sadece sırayı belirler, uygulanmamış değişikliği sonraki göreve aktarmaz.
  Başka bir görevin değişikliğine ihtiyaç duyan görev, `apply`'dan sonra ayrı bir batch'e
  konur.
- Çıkış kodu: her görev `ok` ise 0, değilse 1. Her sonuçta görevin zarfı vardır.

**Maliyet.** `orkestra batch tasks.yaml --estimate`, her görevin ilk isteğini router'ın
seçeceği sağlayıcıda fiyatlar (istem + `max_output_tokens`, bütçe rezervasyonuyla aynı tahmin)
ve hiçbir şey göndermez; `--dry-run` gibi önbellekteki fiyat listelerini kullanır. Tekrarlar,
geri bildirim ve üst kademeye geçiş daha pahalıya çıkabilir. Kod ajanları ve fiyatı bilinmeyen
modeller "fiyatsız" listelenir ve toplama girmez; fiyatsız yerel model 0 sayılır.
Fiyatı bilinmeyen ücretli (uzak) modelin maliyeti denetlenemez; böyle bir model kullanan
batch de önce sorar.

Gerçek koşudan önce batch aynı şekilde tahmin edilir. `estimate.confirm_above_usd` aşılırsa
(varsayılan `0.50`; `null` denetimi kapatır) terminalde sorulur; `--json` ya da terminalsiz
koşuda tahmin yazılır (`needs_confirmation: true`), hiçbir şey çalışmaz ve `--yes-cost`
eklenene kadar kod 2 döner. Sadece fiyatsız yerel modeller (ve kod ajanları) olan kurulum
para harcamaz ve bu denetimi atlar.

**Uygulama.** Her koşuya bak (`show <run_id> --diff`), istemediklerini `discard` et, sonra
`orkestra apply --batch <batch_id> --only-ok`: batch'in geçen düzenleme koşuları çalıştıkları
sırayla uygulanır; geçmeyenler ve zaten uygulananlar atlanır. İlk çakışmada kod 5 ile durur ve
uygulananları, çakışan koşuyu ve denenmeyenleri bildirir; başka bir hata da aynı şekilde
kendi çıkış koduyla durdurur ve rapor uygulananları korur. `--only-ok` olmadan, değişikliği
duran başarısız bir koşusu olan batch reddedilir ve hiçbir şey uygulanmaz (`discard` ettiğin
başarısız koşu sayılmaz).

**İstatistik.** `orkestra stats --since 7d` (ya da `24h`, `30m`) sağlayıcı ve görev etiketi
başına biten koşuları, başarı oranını, ortalama deneme ve süreyi, token ve maliyeti gösterir.
Koşu cevabı veren sağlayıcıya sayılır; üst kademeye geçen koşu son kullandığı sağlayıcıya.
Hâlâ `running` görünen koşular ayrıca sayılır.

## Gece kuyruğu ve bildirimler

İşleri gün içinde kuyruğa ekle; bilgisayar boşken (örneğin gece, ücretsiz yerel modellerle)
çalışsın:

```bash
orkestra queue add tasks/docstrings.yaml                 # şimdi denetlenir; klasör saklanır
orkestra queue add tasks/tests-batch.yaml --profile cheap
orkestra queue run --until 07:00 --notify                # terminali açık bırak
```

- Kuyruk `state.db`'de durur. İşler sırayla, her biri eklendiği klasörde (o projenin
  `orkestra.yaml`'ı ile) çalışır. `queue add`'den sonra değişen dosya için uyarı yazılır ve
  güncel hali çalışır. `--profile` verilmezse iş `queue.default_profile` ile çalışır.
- Aynı anda tek `queue run` çalışır (ikincisi 5 koduyla çıkar); çöken bir çalıştırmanın
  bıraktığı kilit temizlenir, `running` bıraktığı işler yeniden kuyruğa girer.
- `--until SS:DD` o saatten sonra yeni iş başlatmaz; `--max-cost-usd` o kadar harcanınca yeni iş
  başlatmaz (`0` = yalnız ücretsiz iş). Gece maliyeti onaylayacak kimse yok: onay isteyecek batch
  atlanır ve kuyrukta kalır (`--max-cost-usd` verilmişse sınır karar verir).
- Servis değildir: uyuyan bilgisayar hiçbir şey çalıştırmaz. Her gece başlatmak için cron veya
  Windows Görev Zamanlayıcı: [`docs/recipes.tr.md`](docs/recipes.tr.md).
- Bildirimler (`queue run --notify`, `batch --notify`) yalnız sayıları içerir ("5 bitti,
  1 başarısız"), görev metni veya kod asla. Masaüstü bildirimi ek paket ister
  (`uv tool install "orkestra-cli[notify]"`); yoksa sessizce atlanır. Telefon bildirimi
  [ntfy](https://ntfy.sh) ile: `notify.ntfy_topic_env`'e konu adını tutan ortam değişkeninin
  adını yaz. `orkestra notify test` her kanalı dener.
- Sabah: `orkestra status` → `orkestra review` → `orkestra apply`.

## Şef araçları

**`orkestra status`** oturuma başlarken tek komut: şef ve profil, doğrulamayı geçip `apply` ya
da `discard` bekleyen düzenleme koşuları, bugünkü bütçe (sağlayıcı başına) ve duraklatılmış
sağlayıcılar; en fazla 15 satır (`--json` her şeyi verir). Devir dosyası varsa hedefi de
gösterir; kuyrukta bekleyen, çalışan veya başarısız iş varsa onları da.

**Devir dosyası (`orkestra handoff`).** Şefin kotası dolduğunda iş, sıradaki yapay zekânın
hafızası yerine `.orkestra/HANDOFF.md` ile devam eder: hedef, durum, bitenler, kararlar, açık
sorular ve tuzaklar; kimin ne zaman hangi commit'te güncellediği. `orkestra handoff init`
dosyayı oluşturur, `update --section done --add "…"` tarihli ve şefli madde ekler, `--set`
metin bölümünü değiştirir. `orkestra handoff check`, dosya `handoff.stale_after_commits`
commit'ten daha eskiyse uyarır (`--strict` kod 1, `--warn-only` asla durdurmaz ve yalnızca uyarıları basar).
`orkestra handoff show --brief` sıradaki şef için kısa özeti yazar: dosyanın kilit
bölümleri (sıradaki adımın durduğu `In progress` dahil), gerçek dal, `git status`, son commit'ler, uygulanmamış koşular ve kalan bütçe; asla
`handoff.brief_max_lines` satırı geçmez (kesmek gerekirse eskime uyarısı ve Orkestra
kılavuzu kalır, önce proje satırları kesilir). `update` ile yazılan metin maskelenir; `Done`/
`Decisions` `handoff.max_lines`'ı aşınca en eski maddeler `.orkestra/HANDOFF.archive.md`'ye
eklenir (silinmez).

`orkestra handoff to <şef>` devri gerçekleştirir: özeti hazırlar, tek bir `handoffs` kaydı
yazar (kim, kime, ne zaman, hangi commit'te, özet nereye yazıldı) ve hedef ajanı senin
terminalinde, repo kökünde ve `ORKESTRA_CHIEF` kendi adıyla başlatır (komutu kendin
çalıştır, bir şefin komut aracından değil: ajanın gerçek bir terminale ihtiyacı var; Ctrl+C
artık ajanındır); Orkestra hedef ajanın çıkış koduyla çıkar. Özetin nasıl ulaşacağını
`chiefs.<ad>.prompt_mode` belirler: `arg` (son argüman), `stdin` ya da `file`
(`.orkestra/BRIEF.md` ve kısa bir talimat). `.cmd`/`.bat` başlatıcı ya da 8000 karakteri aşan
bir özet uyarıyla `file` moduna düşer. `--print-only` hiçbir şey başlatmadan ve kayıt
yazmadan ne gönderileceğini gösterir. Commit edilmemiş değişiklik varsa `to` kod 5 ile durur ve dosyaları sayar;
`--allow-dirty` ile devam edilir (devir dosyası, arşivi ve üretilen `BRIEF.md` kirli sayılmaz).
`orkestra handoff install-hook`, deponun `pre-commit` kancasına shebang satırının hemen
altına işaretli ve tekrar çalıştırılabilir bir blok ekler; hatırlatma her commit'te görünür
(var olan kancayı ezmez, commit'i asla engellemez; kabuk betiği olmayan kancaya dokunmaz ve
nedenini söyler; worktree'de git'in bildirdiği hooks yolunu kullanır).

**Şablonlar** görev dosyası yazmaktan kurtarır:

```bash
orkestra templates list
orkestra run --template docstring --files "src/*.py" --param style=numpy --dry-run   # görevler
orkestra run --template docstring --files "src/*.py" --param check="python -m pytest -q"
```

Eşleşen her dosya bir görev olur (şablonun adıyla etiketlenir) ve aynı maliyet denetimiyle
batch olarak çalışır. Yerleşikler: `docstring`, `type-hints`, `tests`, `summarize` (JSON cevap,
hiçbir şeyi değiştirmez), `rename-refactor` (`old`, `new`), `translate` (`language`).
Parametreleri `templates show <ad>` listeler. İsteğe bağlı `check` parametresi geçmesi gereken
bir komuttur (testlerin); verilmezse sadece değişen dosya sayısı denetlenir. Proje kendi
şablonlarını `.orkestra/templates/<ad>.yaml` olarak ekleyebilir ya da yerleşiği ezebilir:
`description`, `params` (`ad: {default, description}`; varsayılanı olmayan zorunludur) ve
`task` (`id` olmadan görev alanları; `$file` ve `$<parametre>` doldurulur, dosya adındaki `$`
olduğu gibi kalır). Yerleşik şablonun yerine geçen proje şablonu her kullanımda duyurulur:
klonlanan bir depo kendi komutlarını getirebilir, önce `templates show` ile bak. `--files`
sadece çalışma dizinindeki, `.gitignore` ve ignore dosyasının dışarıda bırakmadığı gerçek
dosyaları alır.

**Cevap önbelleği.** Doğrulamayı geçen bir `ask` cevabı `cache.ttl_days` (14) gün boyunca
`~/.orkestra/cache/responses/` altında tutulur (gizli bilgiler maskeli, istem yok). Aynı
modele aynı bağlam dosyaları ve doğrulayıcılarla sorulan aynı soru oradan gelir: hiçbir şey
gönderilmez, bütçe harcanmaz, zarfta `cached: true` yazar. Bağlam dosyası değişirse yeni soru
sayılır; artık doğrulamayı geçmeyen önbellek cevabı silinir ve işçiye sorulur. `edit`
görevleri ve kod ajanlarının cevapları asla önbelleğe alınmaz. `--no-cache` (`ask`, `run`, `batch`) tek komutta atlar,
`cache.enabled: false` kapatır, `orkestra cache clear` boşaltır.

**Tasarruf (tahmini).** `orkestra stats` işçilerin kaç token yazdığını ve şefe zarflarla kaç
token döndüğünü de gösterir (doğrulamayı geçen koşular için). Şefin kendi kullanımı
ölçülemediği için satır her zaman tahmini olarak işaretlenir.

## İkinci bir AI denetler: şef için daha ucuz yazma

Yazmayı devretmenin şef için sabit bir bedeli var: görevi yazmak ve geleni okumak. Orkestra
okumayı kısa tutar. İşçinin değişikliğini başka bir sağlayıcı denetler, şef diff yerine birkaç
satırlık rapor okur:

```bash
orkestra review RUN_ID --json        # yazardan başka bir sağlayıcı denetler
orkestra show RUN_ID --report        # yapılan / denetlenen / değişiklik / denetim / bak / sıradaki
orkestra apply RUN_ID --max-risk low # yalnız bağımsız denetim "low" dediyse
```

```yaml
review:
  auto: true            # denetimi geçen her edit koşusu denetlenir
  independent: true     # başka biri denetleyebiliyorsa asla yazar değil (varsayılan)
  by:
    ollama: [agy, openrouter]   # Ollama'nın değişikliklerini agy, yoksa OpenRouter denetler
    "*": [openrouter]           # ötekilerin
```

- Başka biri denetleyebildiği sürece denetçi, değişikliği yazan sağlayıcı olmaz. Kimse
  denetleyemezse yazar denetler ve rapor `independent: false` der. Kod ajanları da denetleyebilir
  (salt okunur).
- `apply --max-risk low` yalnız denetimler koşup geçtiyse, bağımsız denetim değişikliği en çok o
  riskte bulup hiçbir yeri işaretlemediyse (`unknown` hiç geçmez) ve değişiklik hâlâ denetlenenle
  aynıysa uygular; yoksa kod 2 ile reddeder ve şef diff'i okur. `review.by`'da adı geçen
  denetçiler ve eksik onaylar asla sessizce atlanmaz; `doctor` sağlayıcı olmayan `review.by`
  adını uyarır.
  `apply --batch ID --only-ok --max-risk low` geçenleri uygular, ötekileri atlandı diye listeler.
- `show --report` sıradaki tek komutla biter: `apply --max-risk low`, işaretli satırlar, diff'in
  tamamı ya da henüz denetim yoksa `review`.
- Skill şefe tek küçük işi devretmemesini, mekanik işi tek batch'le (ya da `run --template`)
  vermesini ve doğrulayıcı olarak projenin kendi testlerini kullanmasını söyler.

## Uzun komut çıktısı: `orkestra exec`

Test koşuları, linter'lar ve derlemeler Claude'un bağlamına giren en büyük şey (aşağıdaki
token haritasına bak) ve sonraki her istek onları yeniden okur. `orkestra exec` komutu
çalıştırır ve yalnız işe yarayanı geri verir:

```bash
orkestra exec -- uv run pytest
orkestra exec --max-lines 20 -- uv run ruff check .
orkestra exec --json -- npm test
```

```
çıkış 1 · 412 satır · pytest · tam çıktı: ~/.orkestra/runs/20261117-205059-46bf/output.log
3 failed, 120 passed in 4.10s
tests/test_calc.py:6: FAILED tests/test_calc.py::test_add - assert -1 == 5
…
```

- `exec.max_lines` satıra kadar (varsayılan 40) çıktı olduğu gibi döner.
- Orkestra'nın tanıdığı bir aracın uzun çıktısı kurallarla, modelsiz ve hatasız özetlenir:
  **pytest** (başarısız ya da hatalı her test, hiçbiri düşmez, başarısız olduğu
  `dosya:satır` ile), **ruff** (check ve format), **pyright**, ve `dosya:satır` yazan
  derleyiciler ya da tip denetleyiciler (mypy, gcc/clang, tsc, rustc). Yollar projeye göre.
- Diğer uzun çıktıyı `exec.tier`'deki (varsayılan 1) bir sohbet modeli özetler (router
  üzerinden: anahtar içeren çıktı yerelde kalır; bunun için kod ajanı hiç başlatılmaz).
  Model yoksa ya da `--no-model` verildiyse ilk ve son satırlar gösterilir, nedeni yazılır.
- Çıkış kodu komutun kendi kodudur (127: program yok, 124: `--timeout` doldu, komut alt
  süreçleriyle durdurulur). Tam çıktı, anahtarlar maskelenmiş olarak,
  `runs/<id>/output.log`'dadır (diğer koşu kayıtları gibi `gc` temizler).
- Kabuk yoktur: boru, `&&` ve yönlendirme çalışmaz; tek komut ver.

Claude skill'i Claude'a testleri, linter'ları ve derlemeleri böyle çalıştırmasını söyler.

## Bağlamı doldurmadan okumak ve aramak: `orkestra read`, `orkestra find`

Tek bir soruyu cevaplamak için büyük bir dosyayı okumak, o dosyanın bedelini sonraki her
istekte ödetir. Bunun yerine:

```bash
orkestra read src/config/loader.py "Config'ler hangi sırayla birleştiriliyor?"
orkestra find "load_config(" --glob "src/**"
orkestra find "TODO" --ask "Hangileri güvenlikle ilgili?"
```

- **`read DOSYALAR... SORU`**: bir sohbet işçisi (`read.tier`, varsayılan 1; asla kod ajanı)
  dosyaları numaralı satırlarla okur ve birkaç satırda `dosya:satır` işaretçileriyle
  cevaplar. Her işaretçi dosyalara karşı denetlenir: geçerli olanın yanında gösterdiği satır
  yazar, geçersiz olan güvenilmesin diye işaretlenir. Dosyalar görev bağlamı gibi okunur
  (`.orkestraignore` ve ikili dosyalar dışarıda kalır ve listelenir, boyut sınırı geçerli).
  Değişmemiş dosyalar için aynı soru cevap önbelleğinden gelir (`--no-cache` yeniden sorar).
- **`find DESEN`**: model yok. Metin (büyük/küçük harfe duyarlı) ya da `--regex` ile
  düzenli ifade, projenin dosyalarında (`.gitignore`, `.orkestraignore`, ikili dosyalar ve
  Orkestra'nın klasörleri dışında; `--glob` daraltır). `find.max_hits`'e kadar sonuç
  (varsayılan 40) `dosya:satır: metin` olarak gelir; fazlası dosya başına, proje
  fihristindeki özeti ve ilk sonuçlarıyla gruplanır. Sonuç yoksa grep gibi kod 1.
  `--ask "<soru>"` ile bir işçi sonuçlar hakkında (her birinin çevresindeki birkaç satırla)
  denetlenmiş işaretçilerle cevap verir.
- **Proje fihristi**, `orkestra map`'in dosya başına özetleridir. `orkestra map
  --install-hook`, arka planda `orkestra map --after-commit` çalıştıran bir post-commit hook
  ekler: her commit'in değiştirdiği dosyalar, aynı anda tek koşuyla haritalanır (rebase'de
  sıraya girer); fihrist commit'leri yavaşlatmadan güncel kalır.

## Claude'un tokenı nereye gidiyor?

`orkestra tokens` Claude Code'un kendi oturum dökümlerini okur
(`~/.claude/projects/<proje>/*.jsonl` ya da `$CLAUDE_CONFIG_DIR` altında) ve bir oturumun ne
harcadığını ve neden harcadığını gösterir. Hiçbir şey göndermez, kota harcamaz.

```bash
orkestra tokens                      # bu projenin en son oturumu
orkestra tokens --since 7d --top 10  # son haftanın bütün oturumları
orkestra tokens --session 1f49 --json
orkestra tokens --project ../baska-repo
```

Bir araç çağrısının bedeli boyutundan fazladır: sonucu önbelleğe bir kez yazılır, sonra
oturum bitene ya da sıkıştırılana kadar **sonraki her istekte yeniden okunur**. 300 istekli bir
oturumun başında okunan 300 satırlık dosyanın bedeli 300 kez ödenir. Rapor şunları gösterir:

- ölçülen toplamlar (girdi, önbelleğe yazma, önbellekten okuma, çıktı) ve girdi tokenına
  göre API fiyatlarıyla ağırlıklı toplam (çıktı ×5, önbelleğe yazma ×1,25, önbellekten okuma
  ×0,1; abonelik farklı tartabileceği için `tokens.weights` ile değiştirilebilir);
- ağırlıklı tokenların nereye gittiği: okuma, komut çıktısı, yazma, ajanlar, Claude'un kendi
  cevaplarının yeniden okunması, sonraki mesajların ve hatırlatmalar, Claude'un çıktısı, her
  istekte yeniden okunan sabit başlangıç (sistem istemi, araçlar, CLAUDE.md), önbellek kaçırma
  (ara ya da model değişikliği sonrası bağlamın yeniden yazılması) ve geri kalan;
- en pahalı araç çağrıları ve "10 satır olsaydı …";
- istek başına bağlamın büyümesi, alt ajanlar (ayrı sayılır) ve sıkıştırmalar.

Araç çağrısı boyutları tahmin edilir (4 karakter ≈ 1 token), sonra her oturumda Claude
Code'un ölçtüğü yeni bağlama eşit olacak şekilde ölçeklenir; katsayı yazılır. Etiketlerde
dosyalar projeye göre, komutlarda proje `.`, ev klasörü `~` olarak görünür.

Örnek, bu deponun Orkestra'yı yazarken geçen kendi 12 oturumu (Claude Code 2.1.312–2.1.325,
2.793 istek):

```
ağırlıklı tokenlar nereye gidiyor:
  komut çıktısı (Bash, PowerShell): %23
  sonraki mesajların ve hatırlatmalar: %21
  yazma (Edit, Write): %16
  Claude'un çıktısı (metin, düşünme, araç çağrıları): %14
  Claude'un cevapları ve araç çağrıları, sonradan yeniden okunması: %12
  sabit başlangıç (sistem istemi, araçlar, CLAUDE.md, hafıza), her istekte yeniden okunur: %11
  okuma (Read, Grep, Glob, web): %8
  önbellek kaçırma (ara ya da model değişikliği sonrası bağlamın yeniden yazılması): %1

en pahalı araç çağrıları (boyut × bağlamda kaldığı istek sayısı):
  Read YAPILIS_PLANI.md: ~23,027 token, 650 satır, 269 kez yeniden okundu, ağırlıklı 648,210
    10 satır olsaydı: 9,972 (638,238 tasarruf)
istek başına bağlam (en son oturum): 47,252 → 174,632 → 247,227 → 332,261 → 405,278
```

Yani maliyetin yaklaşık %85'i Claude'un yazması değil, bağlamın yeniden okunması: uzun bir
oturumun başındaki büyük komut çıktıları ve dosya okumaları asıl kaldıraç. Sonraki fazlar
(bağlam süzgeci ve kısa oturumlar) buna yöneliyor.

## Kısa oturumlar: işe yaradığında yeni bağlam

Uzun bir oturumda her istek bağlamın tamamını yeniden okur (token haritasına bak), yani bir
isteğin bedeli oturumla birlikte büyür. `handoff.suggest_at_tokens` (varsayılan 120.000)
geçilince `orkestra status` ve `orkestra tokens`, oturumun kendi sayılarından, yeni bir
oturumun ne kazandıracağını söyler:

```
bağlam ~180,000 token: yeni oturum her 100 istekte ~1,300,000 ağırlıklı token kazandırır
(orkestra handoff update …, sonra /clear ve orkestra handoff show --brief, ya da orkestra handoff to claude)
```

Yeni oturum ilk isteğin bağlamından (sistem istemi, araçlar, CLAUDE.md) ve devir özetinden
(~3.000 token) başlar; sonraki her istek o kadar az okur. Devir dosyasını güncelleyip commit
ettikten sonra iki yol var: Claude Code'da `/clear` ve `orkestra handoff show --brief`'i
okumak, ya da oturumu kapatıp `orkestra handoff to claude` (aynı şefe devir). Claude skill'i
bunu bir fazın ya da alt görevin sonunda önerir, ortasında asla.

## İşe göre model

Hafif işler (`exec` çıktısının özeti, `read`, `find --ask`, `map` için dosya özetleri) kodunu
yazan modele gerek duymaz; kendi bilgisayarında tek satırlık özet için büyük model her şeyi
yavaşlatır. `routing.by_kind` her iş türünün önce hangi modelleri deneyeceğini söyler:

```yaml
routing:
  by_kind:
    summary: {prefer: ["ollama/qwen2.5:1.5b", "openrouter/*:free"]}  # orkestra exec
    read:    {prefer: ["ollama/qwen2.5:3b"]}                         # read, find --ask
    map:     {prefer: ["ollama/qwen2.5:1.5b"]}
    edit:    {prefer: ["ollama/qwen2.5-coder:14b", "codex"]}
```

- Türler: `summary` (`exec`), `read` (`read`, `find --ask`), `map`, `review`, `plan` ve görev
  türleri `ask` ile `edit`. Desen bir sağlayıcı (`codex`), `sağlayıcı/model` ya da bunların
  glob'u (`openrouter/*:free`); eşleşen ilk desen sırayı verir.
- Yalnız **her kademenin içinde** sıralar: kademe kuralı, bütçe, gizlilik ve kotası azalan
  sağlayıcı önce gelir; adı geçmeyen modeller her zamanki sırayla arkadan. `by_kind` yoksa
  hiçbir şey değişmez. `--dry-run --json` `prefer_rank` gösterir.
- **Aynı anda tek ağır yerel model.** Yerel sağlayıcının `concurrency`'si (varsayılan 1) artık
  süreçler arasında da geçerli: bir terminaldeki batch, şefin `orkestra exec`'i ve gece
  kuyruğu ikinci bir modeli birincinin yanına yüklemek yerine birbirini bekler. Çöken bir
  sürecin bıraktığı yer geri alınır. Ağır işler yine gece kuyruğuna gidebilir
  (`orkestra queue add`).
- `orkestra doctor`, yerel sağlayıcı tanımlıysa bu bilgisayar için boyut önerir ("RAM 32 GB,
  GPU 12 GB: özet için 1.5b-3b, kod için yaklaşık 14b'ye kadar") ve daha büyük görünen
  tanımlı yerel modeli uyarır. Yalnız öneri.

## Worktree'ler: yalıtılmış değişiklikler

İşçiler senin çalışma kopyanı asla değiştirmez. Kod değiştiren bir koşu `~/.orkestra/worktrees/`
altında kendi git worktree'sini alır ve diskte **şu an** ne varsa oradan başlar: son commit,
commit edilmemiş değişikliklerin ve izlenmeyen dosyaların (ignore edilen dosyalar taşınmaz).
Sonuca bakıp karar verirsin:

```bash
orkestra show <run_id> --diff      # değişiklik
orkestra apply <run_id>            # çalışma ağacına al, worktree'yi sil
orkestra discard <run_id>          # ya da at
orkestra gc                        # sahipsiz worktree'ler, 30 günden eski koşular, askıda rezervasyonlar
```

`apply` hiçbir şeyi stage'lemez ve commit edilmemiş diğer işine dokunmaz. Koşu başladıktan
sonra aynı dosyaları değiştirdiysen üç yönlü birleştirir; değişiklik seninkiyle çakışırsa
**hiçbir şey yazmaz**, çakışan dosyaları listeler, kod 5 ile çıkar ve worktree incelemen için
kalır. Worktree'lerde git hook'ları çalışmaz. Alt modüller ve Git LFS dosyaları henüz
işlenmez (uyarı verilir). Worktree yolları derin olduğu için `doctor` Windows'ta
`core.longpaths` önerir. Ignore edilen dosyalar (`node_modules/`, `.venv/`) worktree'ye
kopyalanmaz; bunlara ihtiyaç duyan bir kontrol kendi getirmeli (etkin yorumlayıcınla çalışan
bir Python kontrolü çalışır).

## Claude skill

`skill/orkestra/SKILL.md`, Claude'a (Claude Code'da ya da yerel kabuğu olan her yerde) işi ne
zaman ve nasıl Orkestra'ya vereceğini öğretir: sadece büyük ve denetlenebilir işleri delege et,
gerçek doğrulayıcılarla görev dosyası yaz, sadece sonuç zarfını oku, `apply` etmeden önce diff'i
oku; onay vermeyi (`--yes`), gizli bilgiyi uzağa göndermeyi (`--allow-secrets`) ve doğrulanmamış
değişikliği zorla uygulamayı (`--force`) asla kendi başına yapma. Bir test, skill'in andığı her
komutun ve bayrağın CLI'de var olduğunu denetler.

```bash
# kişisel skill olarak
mkdir -p ~/.claude/skills && cp -r skill/orkestra ~/.claude/skills/
# veya sadece bir proje için
mkdir -p .claude/skills && cp -r skill/orkestra .claude/skills/
```

Sonra Claude'a örneğin şunu söyle: *"Bu 20 dosyaya docstring ekleme işini orkestra ile dağıt,
sonucu sen denetle."* Skill şimdilik Türkçe (yayında İngilizceye çevrilecek) ve bugün var olan
bütün komutları kapsıyor: `batch`, `map`, `review`, `plan expand` ve devir dosyası da
(`handoff update`, `show --brief`, `to --print-only`).

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

### Sağlayıcı ekleme

OpenAI uyumlu herhangi bir servis YAML yazmadan eklenebilir; belirli bir servise özel kod
yoktur. Anahtarın kendisi asla yazılmaz, yalnız onu tutan ortam değişkeninin adı (varsayılan
`<AD>_API_KEY`). Eklemek onay vermek değildir; ardından yine `providers enable` gerekir.

```bash
orkestra providers add myapi --base-url https://api.example.com/v1 \
  --model some-model --model other-model --check     # --check sunucudan model listesini ister
orkestra providers add lab --base-url http://localhost:1234/v1 --model m --no-key
orkestra providers import opencode                   # OpenCode'un opencode.json dosyasından
orkestra providers import opencode --name myapi      # dosyada birden fazla varsa
orkestra providers import opencode --name My.Lab --as lab   # başka bir adla
orkestra providers remove myapi                      # onayıyla birlikte
orkestra providers enable myapi
```

`import opencode`, `@ai-sdk/openai-compatible` girdilerini (`baseURL`, `models`) okur.
`{env:DEĞİŞKEN}` biçimindeki `apiKey` değişken adını verir; dosyaya düz yazılmış anahtar
kopyalanmaz, Orkestra onu hangi değişkene koyman gerektiğini söyler. Anahtar değişkeni olarak
verilen değer bir değişken adı olmalı; yapıştırılan anahtar reddedilir ve hiç gösterilmez. Bir
modelin `limit.context` değeri bağlam uzunluğu olur. `init --plain` aynısını
"başka bir OpenAI uyumlu servis" olarak sunar. `--tier` (varsayılan 2), `--context-window` ve
`--project`, `add` ve `import` için geçerlidir.

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
| 5 | `apply` çakışması: hiçbir şey yazılmadı, worktree duruyor |
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
| 5b | Git worktree, `show`, `apply`, `discard`, `gc` | ✅ |
| 5c | API işçileriyle düzenleme görevleri | ✅ |
| 6 | Kod ajanları: Codex CLI, Antigravity CLI | ✅ |
| 7a | Batch: bağımlılıklar, paralellik, sağlayıcı başına sınır | ✅ |
| 7b | Maliyet tahmini, toplu apply, `stats` | ✅ |
| 8a | Şef araçları: `status`, şablonlar, cevap önbelleği, tasarruf sayacı | ✅ |
| 8b | Şef araçları: `review`, `map`, `plan expand` | ✅ |
| 9a | Claude skill: `SKILL.md`, CLI ile denetlenmiş | ✅ |
| 9b | Claude skill: denetim ve elle senaryolar | ✅ |
| 9c | Ucuz modeller için ara/değiştir (SEARCH/REPLACE) düzenlemesi | ✅ |
| 10 | Şef devri (Claude ↔ Codex ↔ Antigravity) | ✅ |
| 11 | Terminal arayüzü, kurulum sihirbazı, 5 dil | ✅ |
| 12a | Gece kuyruğu ve bildirimler | ✅ |
| 12b | Öğrenen yönlendirme, terminal arayüzünde kuyruk | ✅ |
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
