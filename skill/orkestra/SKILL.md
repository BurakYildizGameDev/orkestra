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

İlk delegeden önce bir kez durumu kontrol et:

```bash
orkestra doctor --json            # config, sağlayıcı erişimi, anahtar değişkenleri, araçlar
orkestra providers list --json    # onay (consent), sağlık, kalan bütçe
```

- `providers list` içinde `"consent": "missing"` olan sağlayıcıyı Orkestra kullanmaz. Kullanmak istediğin sağlayıcı onaysızsa **kullanıcıya sor** ve komutu onun çalıştırmasını iste: `orkestra providers enable <ad>`. Komut, sağlayıcının neler yapabileceğini gösterip kullanıcıdan onay ister. `--yes` bayrağını kullanıcı açıkça izin vermeden **asla** kullanma.
- Hiç sağlayıcı yoksa (`orkestra init` ile config oluşturulmamış) kurulumu kullanıcıya bırak, işi kendin yap.
- Bir görevin nereye gideceğini merak ediyorsan önce `--dry-run` ile bak; hiçbir şey göndermez, adayları ve elenen sağlayıcıları nedenleriyle listeler (`candidates`, `eliminated`).

Çıkış kodları (her komut için aynı):

| Kod | Anlamı | Ne yaparsın |
|---|---|---|
| 0 | Başarılı | Zarfı oku, denetle |
| 1 | Görev doğrulamayı geçemedi (`failed` / `escalate`) | Bkz. §6 |
| 2 | Config veya kullanım hatası (görev dosyası geçersiz vb.) | Mesajı oku, görev dosyasını düzelt |
| 3 | Uygun sağlayıcı yok (bütçe bitti, hepsi erişilemez, gizli bilgi, anahtar yok) | Nedenleri kullanıcıya özetle; limitleri kendin değiştirme |
| 4 | Kullanıcı onayı gerekli | Kullanıcıya sor, `providers enable` komutunu onun çalıştırmasını iste |
| 5 | `apply` çakışması: hiçbir şey yazılmadı, worktree duruyor | Bkz. §6 |
| 10 | Beklenmeyen iç hata | Kullanıcıya bildir, işi kendin yap |

`--json` ile hata da tek bir JSON belgesi olarak gelir: `{"error": {"code": 4, "type": "ConsentRequired", "message": "...", "details": ["..."]}}`. `details` satırları hangi sağlayıcının neden elendiğini söyler.

## 3. Kademe seçimi

| Kademe | Ne için |
|---|---|
| 1 (yerel/ucuz) | Özet, docstring, basit dönüşüm, veri çıkarma |
| 2 (orta API) | Test yazma, orta karmaşıklıkta fonksiyon, refactor |
| 3 (kod ajanı: Codex vb.) | Çok dosyalı değişiklik, büyük dosyalar, komut çalıştırması gereken işler |

Düşük kademeden başla; Orkestra başarısızlıkta önce aynı modelle geri bildirimle tekrar dener, sonra kendisi üst kademeye geçer. Bir sağlayıcı erişilemezse (internet yok, API hatası, bütçe bitti) sıradakine kendisi geçer. Kademe 3 ajanları kullanıcının kendi Codex/agy kotasından harcar; gerekmedikçe kademe 3 isteme.

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

Alanlar: `id` (harf/rakam, `.`, `_`, `-`), `kind` (`ask` | `edit`), `tier` (1–3), `prompt`, `context.files` / `context.globs`, `verify`, `privacy` (`normal` | `local_only`), `allow_new_files`, `output` (`format: json`, `schema: dosya.json`), `limits` (`timeout_s`, `max_retries`), `workspace`, `provider`, `model`. Bilinmeyen alan hata verir (kod 2).

Doğrulayıcılar (`verify`):
- `command`: komut 0 ile bitmeli (`run`, `timeout_s`; boru veya `&&` gerekiyorsa `shell: true`).
- `protect_paths`: bu desenlerdeki dosyalar değişmemeli. `forbid_paths`: bu desenlerde dosya oluşturulmamalı/değişmemeli.
- `max_changed_files`, `max_diff_lines`: değişikliğin boyut sınırı (`value`).
- `files_exist`: dosyalar oluşmalı (`paths`). `regex`: cevapta `must_match` / `must_not_match`. `json_schema`: cevap JSON ve şemaya uygun (`schema`).

Her `edit` görevine Orkestra kendiliğinden `.env`, `*.pem`, `*.key`, `.git/**` yasağı ve `max_diff_lines: 2000` ekler; yine de **her `edit` görevinde en az bir anlamlı doğrulayıcı** (genelde testleri çalıştıran `command` + `protect_paths`) olsun.

Düzenleme görevleri hakkında bilmen gerekenler:
- İşçi, kullanıcının deposunda değil ayrı bir git worktree'sinde çalışır; senin onayın (`apply`) olmadan kullanıcının dosyalarına hiçbir şey yazılmaz. Depoda en az bir commit olmalı; commit edilmemiş değişiklikler worktree'ye taşınır.
- Görev dosyasındaki göreli yollar görev dosyasının klasörüne değil, `workspace` alanına (yoksa komutun çalıştığı dizine) göre çözülür. `orkestra run` komutunu proje kökünden çalıştır.
- Git'in ignore ettiği klasörler (`node_modules/`, `.venv/`) worktree'de yoktur; onlara ihtiyaç duyan doğrulama komutları (ör. `npm test`) başarısız olur. Python'da etkin yorumlayıcıyla `python -m pytest` çalışır.
- Bağlamdaki dosyalar işçiye tamamen gönderilir; `.env` ve anahtar dosyalarını bağlama koyma. `.orkestraignore` kapsamındaki dosyaları Orkestra hiç göndermez, gizli bilgi taraması da uzağa gitmeyi engeller.

İyi istem kuralları: tek bir sorumluluk; kapsam dışını açıkça yaz; çıktı biçimini belirt; mevcut stil örneği ver.

Birden çok görev varsa her biri için ayrı görev dosyası yaz ve sırayla çalıştır (`orkestra run` her seferinde bir görev). Aynı dosyayı değiştiren işleri ayrı görevlere bölme, tek görevde topla; bir görevin değişikliği sonraki göreve lazımsa önce onu denetleyip `apply` et.

## 5. Çalıştırma ve okuma

```bash
orkestra run .orkestra/tasks/kisa-ad.yaml --dry-run --json   # isteğe bağlı: nereye gidecek?
orkestra run .orkestra/tasks/kisa-ad.yaml --json
```

Sadece **sonuç zarfını** oku. Token tasarrufunun anahtarı bu; tam çıktıyı ancak gerekirse oku. Önemli alanlar:
- `status`: `ok` · `failed` (doğrulama geçmedi, yükseltme yapılamadı) · `escalate` (iş şefe dönmeli) · `error` (sistem hatası; `error` alanında neden).
- `run_id`, `provider`, `model`, `tier`, `attempts`, `escalations`, `failovers` (hangi sağlayıcı neden atlandı).
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
3. `apply` çakışma verirse (kod 5) hiçbir şey yazılmamıştır ve worktree durur: çakışan dosyaları kullanıcının son haline göre kendin düzenle (diff'i rehber al), sonra `orkestra discard <run_id>`.

`apply` sadece `status: ok` koşuları uygular. `--force` (doğrulamayı geçmemiş değişikliği uygulamak) bayrağını kullanıcı açıkça istemeden **asla** kullanma.

`status: escalate` veya `failed` ise: `verification` ve gerekirse `orkestra show <run_id> --log` ile nedenini anla, işi kendin yap ya da durumu kullanıcıya açıkla. Değişiklik bırakan başarısız koşunun worktree'si durur; işin bitince `orkestra discard <run_id>`. Aynı görevi değişiklik yapmadan tekrar çalıştırma.

Uzun bir çalışmanın sonunda sahipsiz worktree'leri ve eski kayıtları temizlemek için `orkestra gc --dry-run` ile bak, kullanıcı isterse `orkestra gc` çalıştır.

## 7. Raporlama

İş bitince kullanıcıya kısaca bildir: hangi işler delege edildi, hangi sağlayıcı/kademe, kaç deneme, maliyet (zarftaki `usage.cost_usd`; günlük toplam için `orkestra budget --json`), neyi kendin düzelttin. Uzun log yapıştırma.

## Asla yapma
- İşçi çıktısını incelemeden `apply` etme; `apply --force` kullanıcı istemeden yok.
- API anahtarlarını istem, görev dosyası veya bağlama koyma.
- `.env`, anahtar dosyaları veya `.orkestraignore` kapsamındaki dosyaları bağlama ekleme.
- Kullanıcının izni olmadan sağlayıcı onaylama (`--yes`) veya gizli bilgiyi uzağa gönderme (`--allow-secrets`).
- Bütçe bittiğinde kullanıcıya sormadan config'teki limitleri değiştirme.
