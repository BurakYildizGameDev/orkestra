---
name: orkestra
description: Delegate high-volume, verifiable work (bulk docstrings/types, test writing, file summaries, data extraction, mechanical refactors) to cheaper or local AI workers through the `orkestra` CLI, then verify and apply the results. Use when a task is large, mechanical and checkable, or when the user asks to save tokens, use Ollama/OpenRouter/Codex, or "orkestra ile dağıt".
---

# Orkestra ile iş dağıtma

Sen **şefsin**: planlar, böler, denetlersin. İşi `orkestra` CLI üzerinden ucuz/yerel işçiler yapar. Amaç kullanıcının token tasarrufu sağlarken kaliteyi korumak. Kalite senin denetimine bağlı; işçi çıktısını asla doğrulamadan kabul etme.

Bu skill yerel kabuk erişimi olan ortamlar içindir (ör. Claude Code). `orkestra` komutu yoksa kullanıcıya kurulum gerektiğini söyle ve işi kendin yap.

## 1. Delege etmeli miyim?

Şu soruyu sor: **"Görevi yazmak + sonucu kontrol etmek, işi kendim yapmaktan ucuz mu?"**

Delege et:
- Çıktısı büyük, kontrolü ucuz işler: 5+ dosyada docstring/tip ekleme, çalıştırılabilir testi olan kod üretimi, çok dosya özetleme, şemaya göre veri çıkarma, mekanik yeniden adlandırma/refactor, çeviri.
- Kullanıcı açıkça "orkestra kullan", "token harcama", "Ollama'ya yaptır" dediyse.

Delege etme (kendin yap):
- Küçük işler (yaklaşık 30 satırdan az değişiklik, tek dosyada hızlı düzeltme).
- Mimari karar, güvenlik açısından hassas kod, belirsiz gereksinim.
- Doğrulama yöntemi olmayan işler (test, şema veya net dosya kuralı yazamıyorsan).
- Kullanıcıyla yoğun etkileşim gerektiren işler.

Emin değilsen bir kez kullanıcıya sor.

## 2. Oturum başı ve ilk kullanım

Her oturumun başında tek komut (en fazla 15 satır: profil, uygulanmamış koşular, bugünkü bütçe, duraklatılmış sağlayıcılar):

```bash
orkestra status --json
```

`unapplied` altında koşu varsa önce onları denetle (§6): uygula ya da `discard` et.

İlk delegeden önce bir kez durumu kontrol et:

```bash
orkestra doctor --json            # config, sağlayıcı erişimi, anahtar değişkenleri, araçlar
orkestra providers list --json    # onay (consent), sağlık, kalan bütçe
```

- Orkestra yalnızca `"enabled": true` ve `"consent": "granted"` olan sağlayıcıları kullanır. `"consent": "missing"` hiç onay verilmemiş demektir. `"consent": "changed"` ise onaydan sonra sağlayıcının ayarları (adres, model vb.) değişmiş demektir ve yeniden onay gerekir. `"enabled": false` olan sağlayıcıyı kullanıcı kapatmıştır, onu açmayı önerme.
- Kullanmak istediğin sağlayıcının onayı eksikse **kullanıcıya sor**. En iyisi, kullanıcının `orkestra providers enable <ad>` komutunu **kendi terminalinde** çalıştırmasıdır. Komut, sağlayıcının neler yapabileceğini ve uyarıları gösterip etkileşimli olarak onay ister.
- Komutu sen `--yes` olmadan çalıştırırsan terminal etkileşimli olmadığı için onay metnini yazdırır, sonra kod 2 ile `consent.not_interactive` hatası verir. Bu hata görev dosyasıyla ilgili değildir. Kullanıcı onayı senin vermeni isterse önce bu metni ona **olduğu gibi göster**. Ancak metni gördükten sonra açıkça kabul ederse `--yes` ile çalıştır. `--yes` bayrağını başka hiçbir durumda **asla** kullanma.
- Hiç sağlayıcı yoksa (`orkestra init` ile config oluşturulmamış) kurulumu kullanıcıya bırak, işi kendin yap.
- Bir görevin nereye gideceğini merak ediyorsan önce `--dry-run` ile bak; hiçbir şey göndermez, adayları ve elenen sağlayıcıları nedenleriyle listeler (`candidates`, `eliminated`).

Çıkış kodları (her komut için aynı):

| Kod | Anlamı | Ne yaparsın |
|---|---|---|
| 0 | Başarılı | Zarfı oku, denetle |
| 1 | Görev doğrulamayı geçemedi (`failed` / `escalate`) | Bkz. §6 |
| 2 | Config veya kullanım hatası (görev dosyası geçersiz, yanlış bayrak/değer, etkileşimsiz onay vb.) | Mesajı oku; görev dosyası veya komut hatalıysa düzelt |
| 3 | Uygun sağlayıcı yok (bütçe bitti, hepsi erişilemez, gizli bilgi, anahtar yok) | Nedenleri kullanıcıya özetle; limitleri kendin değiştirme |
| 4 | Kullanıcı onayı gerekli | Kullanıcıya sor, `providers enable` komutunu kendi terminalinde çalıştırmasını iste |
| 5 | `apply` çakışması: hiçbir şey yazılmadı, worktree duruyor | Bkz. §6 |
| 10 | Beklenmeyen iç hata | Kullanıcıya bildir, işi kendin yap |

`--json` ile hatalar üç biçimde gelir:
- Koşu başlamadan çıkan hata (onay yok, uygun sağlayıcı yok, görev dosyası geçersiz) stdout'ta tek bir JSON belgesidir: `{"error": {"code": 4, "type": "ConsentRequired", "message": "...", "details": ["..."]}}`. `details` satırları hangi sağlayıcının neden elendiğini söyler.
- Koşu başladıktan sonra bütün adaylar başarısız olursa normal sonuç zarfı gelir: `status: error`, `error` alanında kısa metin, nedenler `failovers` içinde (kod 3).
- Komut satırı ayrıştırılamazsa (bilinmeyen bayrak, aralık dışı değer, eksik argüman) stdout boş kalır, mesaj stderr'e yazılır (kod 2). Komutu düzelt.

## 3. Kademe seçimi

| Kademe | Ne için |
|---|---|
| 1 (yerel/ucuz) | Özet, docstring, basit dönüşüm, veri çıkarma |
| 2 (orta API) | Test yazma, orta karmaşıklıkta fonksiyon, refactor |
| 3 (kod ajanı: Codex vb.) | Çok dosyalı değişiklik, büyük dosyalar, komut çalıştırması gereken işler |

Düşük kademeden başla; Orkestra başarısızlıkta önce aynı modelle geri bildirimle tekrar dener, sonra kendisi üst kademeye geçer. Bir sağlayıcı erişilemezse (internet yok, API hatası, bütçe bitti) sıradakine kendisi geçer. Kademe 3 ajanları kullanıcının kendi Codex/agy kotasından harcar; gerekmedikçe kademe 3 isteme. agy (deneysel) dosya düzenleyebilir ama kabuk komutu çalıştıramaz; Orkestra bunu agy'ye kendisi söyler, istemine ekleme (görev Codex'e de gidebilir, o komut çalıştırabilir). Testleri `verify` ile Orkestra çalıştırır.

İşçiler MCP araçlarını kullanamaz. Unity projesinde (`Assets/` ve `ProjectSettings/` var) sahne, prefab ve editör işleri Unity MCP ile şefte kalır; işçilere sadece dosya tabanlı işler (C# betikleri, testler, belgeler) ver. agy bağlanmayan bir MCP sunucusunu beklerse Orkestra onu `mcp_wait_s` (varsayılan 60 sn) sonra durdurup sıradaki sağlayıcıya geçer; hata mesajında sunucunun adı yazar, kullanıcıya ilet (çözüm makinedeki MCP ayarında, Orkestra'da değil).

Gizli bilgi içeren dosyalarda işi yerel modelle sınırla: görev dosyasında `privacy: local_only`, `ask` için `--local-only`. Orkestra gizli bilgi bulduğu bağlamı uzak sağlayıcıya göndermez (çıkış kodu 3); `--allow-secrets` bayrağını kullanıcı açıkça izin vermeden **asla** kullanma, bunun yerine `local_only` öner.

## 4. Görev yazma

Tek soru için (dosya değiştirmez):

```bash
orkestra ask "<net istem>" --context src/a.py --context src/b.py --tier 1 --json
```

Her bağlam dosyası için ayrı `--context` yaz. Cevabın JSON olmasını istiyorsan `--schema sema.json` ekle; cevap şemaya uymazsa Orkestra geri bildirimle tekrar dener.

Düzenleme veya doğrulamalı iş için görev dosyası yaz (`.orkestra/tasks/` altına):

```yaml
id: kisa-ad
kind: edit
tier: 1
prompt: |
  <Ne yapılacak, ne YAPILMAYACAK, beklenen sonuç. Somut ol.>
context:
  files: [src/ilgili.py]
verify:
  - type: command
    run: "python -m pytest -q"
  - type: protect_paths
    paths: ["tests/**"]        # işçi testleri değiştirerek geçemesin
  - type: max_changed_files
    value: 3
allow_new_files: false
```

Alanlar: `id` (harf veya rakamla başlar, sonra harf/rakam, `.`, `_`, `-`), `kind` (`ask` | `edit`), `tier` (1–3), `prompt`, `context.files` / `context.globs`, `verify`, `verify_defaults` (bkz. aşağı), `privacy` (`normal` | `local_only`), `allow_new_files`, `output` (`format: json`, `schema: dosya.json`), `limits` (`timeout_s`, `max_retries`), `workspace`, `provider`, `model`, `edit_format` (`auto` | `replace` | `whole`, bkz. aşağı), `tags` (kayıtta ve `orkestra stats` içinde görünen etiketler), `depends_on` (batch içinde: bu görevler `ok` bitmeden başlamaz). Bilinmeyen alan hata verir (kod 2).

Doğrulayıcılar (`verify`):
- `command`: komut 0 ile bitmeli (`run`, `timeout_s`; boru veya `&&` gerekiyorsa `shell: true`).
- `protect_paths`: bu desenlerdeki dosyalar değişmemeli. `forbid_paths`: bu desenlerde dosya oluşturulmamalı/değişmemeli.
- `max_changed_files`, `max_diff_lines`: değişikliğin boyut sınırı (`value`).
- `files_exist`: dosyalar oluşmalı (`paths`). `regex`: cevapta `must_match` / `must_not_match`. `json_schema`: cevap JSON ve şemaya uygun (`schema`).

Her `edit` görevine Orkestra kendiliğinden `.env`, `*.pem`, `*.key`, `.git/**` yasağı ve `max_diff_lines: 2000` ekler. Meşru bir değişiklik 2000 satırı aşıyorsa görevi bölmeyi tercih et. Bölünemiyorsa `verify_defaults: false` yaz ve dosya yasağını kendi `forbid_paths` doğrulayıcınla geri ekle. Yine de **her `edit` görevinde en az bir anlamlı doğrulayıcı** (genelde testleri çalıştıran `command` + `protect_paths`) olsun.

Düzenleme görevleri hakkında bilmen gerekenler:
- İşçi, kullanıcının deposunda değil ayrı bir git worktree'sinde çalışır; senin onayın (`apply`) olmadan kullanıcının dosyalarına hiçbir şey yazılmaz. Depoda en az bir commit olmalı; commit edilmemiş değişiklikler worktree'ye taşınır.
- Görev dosyasındaki göreli yollar görev dosyasının klasörüne değil, `workspace` alanına (yoksa komutun çalıştığı dizine) göre çözülür. `orkestra run` komutunu proje kökünden çalıştır.
- Git'in ignore ettiği klasörler (`node_modules/`, `.venv/`) worktree'de yoktur; onlara ihtiyaç duyan doğrulama komutları (ör. `npm test`) başarısız olur. Python'da etkin yorumlayıcıyla `python -m pytest` çalışır. Windows'ta `node --test test/` gibi klasör vermek çalışmaz; test dosyalarını tek tek yaz (`node --test test/a.test.js test/b.test.js`).
- API işçilerinin (Ollama, OpenRouter vb.) düzenleme biçimi varsayılan olarak `edit_format: auto`: dosyalar 400 satıra (`security.max_api_edit_lines`) kadarsa işçi dosyanın tamamını yazar (`whole`), daha büyükse sadece değiştirdiği satırları ara/değiştir bloklarıyla gönderir (`replace`), böylece büyük dosyalar da ucuz modele gidebilir. Genelde dokunma. `replace`'i elle seç: işçi küçük bir dosyada tam dosya yazarken satır kaybediyorsa. `whole`'u elle seç: model ara/değiştir bloklarında sürekli hata yapıyorsa (o zaman 400 satırdan büyük dosya ajana gider). Kullanılan biçim zarfta `edit_format` alanında görünür.
- Yorum, docstring ya da biçim gibi "mantığı değiştirme" denen işlerde testler yetmeyebilir: mantığın aynı kaldığını denetleyen bir `command` doğrulayıcısı ekle (ör. yorumlar çıkarıldığında kodun aynı kaldığını karşılaştıran küçük bir betik).
- Bağlamdaki dosyalar işçiye tamamen gönderilir; `.env` ve anahtar dosyalarını bağlama koyma. `.orkestraignore` kapsamındaki dosyaları Orkestra hiç göndermez, gizli bilgi taraması da uzağa gitmeyi engeller.

İyi istem kuralları: tek bir sorumluluk; kapsam dışını açıkça yaz; çıktı biçimini belirt; mevcut stil örneği ver.

Çoğu zaman görev dosyası yazmana gerek yok, hazır şablon kullan:

```bash
orkestra templates list --json
orkestra run --template docstring --files "src/**/*.py" --dry-run   # hangi görevler?
orkestra run --template docstring --files "src/**/*.py" --json
```

Yerleşik şablonlar: `docstring`, `type-hints`, `tests`, `summarize` (JSON cevap, dosya değiştirmez), `rename-refactor` (`--param old=… --param new=…`), `translate` (`--param language=…`). Her eşleşen dosya için bir görev üretilir ve batch olarak çalışır (maliyet eşiği ve `--yes-cost` kuralları aynı). Parametreleri `orkestra templates show <ad>` gösterir. Mantığı korumak için `--param check="python -m pytest -q"` gibi bir doğrulama komutu ver; vermezsen sadece değişen dosya sayısı denetlenir. Proje kendi şablonlarını `.orkestra/templates/<ad>.yaml` olarak koyabilir (aynı adı ezer).

Birden çok görev varsa bir batch dosyası yaz (`.orkestra/tasks/batch.yaml`); her görev, görev dosyasıyla aynı alanları alır:

```yaml
parallel: 4
tasks:
  - id: docs-a
    kind: edit
    prompt: "src/a.py içindeki her fonksiyona docstring ekle; kodu değiştirme."
    context: {files: [src/a.py]}
    verify:
      - {type: command, run: "python -m pytest -q"}
  - id: ozet
    kind: ask
    prompt: "docs-a bittikten sonra src/a.py'nin genel yapısını üç cümleyle özetle."
    context: {files: [src/a.py]}
    depends_on: [docs-a]
```

- Aynı dosyayı değiştiren işleri ayrı görevlere bölme, tek görevde topla. Orkestra dosyaları kesişen düzenleme görevlerini sırayla çalıştırır ve uyarır, ama ikisi de kullanıcının dosyalarından başlar ve ikisini birden uygulamak çakışabilir.
- `depends_on` sadece sıradır: bağımlı görev, önceki görevin **uygulanmamış** değişikliğini görmez. Değişikliğe ihtiyaç varsa önce o batch'i denetleyip `apply` et, sonra ayrı bir batch çalıştır.
- Uzak (ücretli) sağlayıcı kullanacak bir batch'ten önce maliyete bak: `orkestra batch .orkestra/tasks/batch.yaml --estimate --json`. Hiçbir şey gönderilmez. Tahmin, ilk adaydaki ilk denemedir; tekrarlar ve üst kademeye geçiş daha pahalıya çıkabilir.
- Tahmin `estimate.confirm_above_usd`'yi aşarsa `batch --json` çalışmaz, kod 2 ile tahmin belgesini döner (`needs_confirmation: true`). Fiyatı bilinmeyen ücretli bir model varsa da (`totals.unpriced_remote`) aynısı olur. Tahmini kullanıcıya göster; **kullanıcı kabul ederse** `--yes-cost` ekleyip tekrar çalıştır.

## 5. Çalıştırma ve okuma

```bash
orkestra run .orkestra/tasks/kisa-ad.yaml --dry-run --json   # isteğe bağlı: nereye gidecek?
orkestra run .orkestra/tasks/kisa-ad.yaml --json
orkestra batch .orkestra/tasks/batch.yaml --json   # birden çok görev: tek JSON belgesi
```

Batch belgesi: `batch_id`, `results` (her görev için `task_id`, `status`, `run_id` ve görevin zarfı; `skipped`: bağımlılığı `ok` bitmedi), `totals`. Her görevin zarfını aşağıdaki gibi oku.

Aynı `ask` sorusu (aynı model, istem ve bağlam dosyaları) doğrulamayı geçtiyse önbellekten gelir: istek gitmez, maliyet 0, zarfta `cached: true`. Bağlam dosyası değişince yeni soru sayılır. Taze cevap gerekiyorsa `--no-cache`.

Sadece **sonuç zarfını** oku. Token tasarrufunun anahtarı bu; tam çıktıyı ancak gerekirse oku. Önemli alanlar:
- `status`: `ok` · `failed` (doğrulama geçmedi, yükseltme yapılamadı) · `escalate` (iş şefe dönmeli) · `error` (sistem hatası; `error` alanında neden).
- `run_id`, `provider`, `model`, `tier`, `edit_format`, `attempts`, `escalations`, `failovers` (hangi sağlayıcı neden atlandı).
- `summary`: işçinin kısa özeti. `verification`: her doğrulayıcı için `ok` ve `detail`.
- `changes`: `files`, `insertions`, `deletions` (sadece `edit`). `usage.cost_usd`: maliyet.

Ayrıntı gerekirse:

```bash
orkestra show <run_id> --diff     # edit değişikliği (patch)
orkestra show <run_id> --output   # ask cevabının tamamı
orkestra show <run_id> --log      # koşunun kaydı (neden başarısız oldu?)
orkestra show <run_id> --json     # zarfı tekrar al
```

## 6. Denetim (atlanamaz)

`status: ok` olsa bile:
1. `orkestra show <run_id> --diff` ile değişikliği oku. Değişiklik güvenlik, kimlik doğrulama veya veri silme ile ilgiliyse diff'in **tamamını** satır satır oku. Doğrulayıcıların yakalayamayacağı şeylere bak: mantık hatası, gereksiz değişiklik, stil uyumsuzluğu, güvenlik, istenmeyen dosyalar.
2. Uygunsa: `orkestra apply <run_id>`. Değilse: `orkestra discard <run_id>` ve ya istemi iyileştirip tekrar çalıştır ya da kendin yap.
3. `apply` çakışma verirse (kod 5) **hiçbir dosya** yazılmamıştır, çakışmayanlar da yazılmamıştır. Worktree durur. Hata `details` içinde sadece çakışan dosyaları listeler. Değişikliğin tamamı `orkestra show <run_id> --diff` içindedir. Diff'teki **her dosyayı** kendin uygula: çakışmayanları olduğu gibi, çakışanları kullanıcının son haliyle birleştirerek. Bütün dosyaları uyguladıktan sonra `orkestra discard <run_id>` çalıştır. Emin değilsen önce kullanıcıya sor.

`apply` sadece `status: ok` koşuları uygular. `--force` (doğrulamayı geçmemiş değişikliği uygulamak) bayrağını kullanıcı açıkça istemeden **asla** kullanma.

Batch'te her `ok` koşunun diff'ini yukarıdaki gibi denetle. Hepsi uygunsa `orkestra apply --batch <batch_id> --only-ok --json`: geçen koşular çalıştıkları sırayla uygulanır, geçmeyenler ve zaten uygulananlar atlanır (`skipped`). Uygun bulmadığın bir koşu varsa önce onu `orkestra discard <run_id>` ile at. Çakışmada (kod 5) durur: `applied` uygulananlar, `conflict` çakışan koşu (yukarıdaki gibi kendin uygula), `not_tried` denenmeyenler; çakışmayı çözdükten sonra aynı komutu tekrar çalıştır. Başka bir hatada da durur (`error`, kendi çıkış kodu); `applied` yine doğrudur. `--only-ok` olmadan, geçmeyen koşusu olan batch hiç uygulanmaz.

`status: escalate` veya `failed` ise: `verification` ve gerekirse `orkestra show <run_id> --log` ile nedenini anla, işi kendin yap ya da durumu kullanıcıya açıkla. Değişiklik bırakan başarısız koşunun worktree'si durur; işin bitince `orkestra discard <run_id>`. Aynı görevi değişiklik yapmadan tekrar çalıştırma.

Uzun bir çalışmanın sonunda sahipsiz worktree'leri ve eski kayıtları temizlemek için `orkestra gc --dry-run` ile bak, kullanıcı isterse `orkestra gc` çalıştır.

## 7. Raporlama

İş bitince kullanıcıya kısaca bildir: hangi işler delege edildi, hangi sağlayıcı/kademe, kaç deneme, maliyet (zarftaki `usage.cost_usd`; günlük toplam için `orkestra budget --json`), neyi kendin düzelttin. Uzun log yapıştırma. Kullanıcı hangi işçinin ne kadar başarılı olduğunu sorarsa: `orkestra stats --since 7d --json` (sağlayıcı ve etiket başına koşu, başarı oranı, deneme, token, maliyet, süre).

## Asla yapma
- İşçi çıktısını incelemeden `apply` etme; `apply --force` kullanıcı istemeden yok.
- API anahtarlarını istem, görev dosyası veya bağlama koyma.
- `.env`, anahtar dosyaları veya `.orkestraignore` kapsamındaki dosyaları bağlama ekleme.
- Kullanıcının izni olmadan sağlayıcı onaylama (`--yes`), maliyet eşiğini geçme (`--yes-cost`) veya gizli bilgiyi uzağa gönderme (`--allow-secrets`).
- Bütçe bittiğinde kullanıcıya sormadan config'teki limitleri değiştirme.
