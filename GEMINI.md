# GEMINI.md – Antigravity (agy) için

Bu dosyayı Antigravity okur. Asıl kurallar `AGENTS.md`'dedir; bu dosya onların yerine geçmez,
sadece sana verilen işi ve denetimi anlatır.

## 1. Önce oku (atlama)

1. `AGENTS.md` – baştan sona oku ve **harfiyen** uy. Oradaki her "kesin kural" senin için de geçerli.
2. `docs/PROGRESS.md` – nerede kaldık (en yeni kayıt en üstte).
3. `docs/PROJE_DOKUMANTASYONU.md` – Teknik Mimari bölümü, tek doğruluk kaynağı.
4. `docs/YAPILIS_PLANI.md` – sadece sana verilen fazın bölümü.
5. `docs/DECISIONS.md` – önceki sapma kararları (son karar D-060; yenileri D-061'den devam eder).

## 2. Sana verilen fazlar

Sırayla, her biri **kendi dalında ve kendi PR'ında**:

1. **Faz 8b** – `review`, `map`, `plan expand` (`YAPILIS_PLANI.md` "8b", Mimari §19). Dal:
   `faz-8b`, güncel `main`'den. Plandaki 8b kabul kriterlerinin hepsi; `map`'in gizlilik
   kuralını (yerel sağlayıcı yoksa uzağa hiçbir içerik gitmez) **ilk test** olarak yaz.
2. **Faz 10** – şef devri (`YAPILIS_PLANI.md` "Faz 10", Mimari'deki devir bölümü). Dal:
   `faz-10`, Faz 8b birleştirildikten sonra güncel `main`'den. 8b birleşmeden başlama.

Faz 8a bitti (PR #16); onun kodunu "iyileştirme" diye değiştirme. Başka fazların kodunu
"hazırlık" diye yazma. Plan sana uymuyorsa dur ve kullanıcıya sor.

## 3. Claude denetleyecek – kolaya kaçma

Her fazın PR'ını **Claude Code `/code-review` ile satır satır denetleyecek**, kabul kriterlerini
tek tek çalıştırıp doğrulayacak ve `PROGRESS.md` / `DECISIONS.md`'de yazdıklarını koda karşı
kontrol edecek. Yazdığın ile yaptığın arasındaki her fark bulgu olur. Bu yüzden:

- Testi geçirmek için testi zayıflatma, `skip`/`xfail` ekleme, silme ya da beklenen değeri
  koda göre değiştirme. Var olan testler kırılırsa nedenini bul; davranış bilerek değiştiyse
  bunu `DECISIONS.md`'ye yaz.
- **Önce başarısız test, sonra kod.** Her kabul kriterinin bir testi olsun; testin adı neyi
  doğruladığını söylesin.
- Hata gizleme yok: `# type: ignore`, `# noqa`, çıplak `except:`, `except Exception: pass`,
  sessizce `return None`. Hatalar `errors.py` hiyerarşisinden.
- Yapamadığın ya da yarım kalan bir kriteri "✅" diye yazma. `PROGRESS.md`'de dürüstçe
  "⏳ ertelendi" ya da "bilinen sorun" olarak, nedeniyle yaz. Eksik ama dürüst rapor, eksiksiz
  görünen sahte rapordan iyidir.
- Mimari'den sapma gerekiyorsa uygula, ama gerekçesini `DECISIONS.md`'ye tarih ve faz
  numarasıyla yaz ve Mimari'deki ilgili yeri karar numarasıyla güncelle.
- Kullanıcıya görünen her metin `t("anahtar")` ile, en az `en.yaml` ve `tr.yaml`'da.
- Bağımlılık eklemeden önce Mimari §1'e bak; listede yoksa `DECISIONS.md`'ye gerekçe yaz.
- Var olan migration dosyasını değiştirme; yeni migration ekle.
- Skill'e (`skill/orkestra/SKILL.md`) faz bitince ilgili komutları geri ekle; `tests/unit/test_skill.py`
  skill'deki her komutu gerçek CLI'ye karşı denetler.

## 4. Git

- `main`'e doğrudan commit yok. Force push, `reset --hard`, `clean` yok.
- Commit biçimi: `feat(faz-8b): kısa açıklama` (Faz 10 için `feat(faz-10): …`).
- PR aç, **birleştirme**. PR açıklamasına kabul kriterlerini madde madde (✅ / ⏳ / ❌), test
  sayısını ve "Claude denetimi bekliyor" notunu yaz. Birleştirmeyi denetimden sonra kullanıcı
  onaylar.

## 5. Bitirmeden önce

`AGENTS.md`'deki "Faz bitiş kontrol listesi"nin hepsi, şu komutlar temiz:

```bash
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest
```

`docs/PROGRESS.md` (yapılanlar, kabul kriterleri madde madde, ertelenenler, bilinen sorunlar),
`docs/DECISIONS.md` (yeni kararlar) ve `docs/YAPILANLAR.md` (test sonuçları tablosu)
güncellensin. Kod denetimi adımını Claude yapacak; listede bunu "Claude denetimi bekliyor"
diye bırak.

## 6. Bu makineye özel

- Windows 11, PowerShell. Komutlar `uv run …` ile.
- `rm` ve `sudo` senin için yasak (`permissions.deny`). Dosya silmen gerekiyorsa nedenini
  söyleyip kullanıcıya bırak.
- Testler ağa çıkmaz ve gerçek ajan başlatmaz (`@pytest.mark.live` hariç, onları çalıştırma).
- API anahtarı, token ya da kişisel yol (`C:\Users\…`) hiçbir dosyaya, teste, log'a, commit'e
  girmez.
