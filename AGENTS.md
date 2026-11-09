# AGENTS.md – Kodlama ajanları için kurallar

Bu dosya Claude Code, Codex, Antigravity ve benzeri ajanlar içindir. (Claude Code `CLAUDE.md` üzerinden bu dosyayı içe aktarır. Kullandığın araç başka bir dosya adı okuyorsa, örneğin `GEMINI.md`, aynı içeriği oraya da koy veya bağla.)

## Proje
Orkestra: birden fazla yapay zekâyı (Ollama, OpenAI uyumlu API'ler, Codex/Antigravity CLI) bütçe ve doğrulama ile yöneten Python CLI.

## Her oturumun başında oku
1. `docs/PROGRESS.md` – nerede kaldık
2. `docs/PROJE_DOKUMANTASYONU.md` (Teknik Mimari bölümü) – teknik şartname (tek doğruluk kaynağı)
3. `docs/YAPILIS_PLANI.md` – sadece sana verilen faz
4. `docs/DECISIONS.md` – önceki sapma kararları

## Kesin kurallar
- **Sadece istenen fazı yap.** Gelecek fazların kodunu "hazırlık" diye yazma.
- **Önce test.** Yeni davranış için önce başarısız test, sonra kod.
- **Teknik Mimari bölümünden sapma** gerekiyorsa uygula ama gerekçesini `docs/DECISIONS.md`'ye tarih ve faz numarasıyla yaz ve Mimari bölümündeki ilgili yeri de karar numarasıyla güncelle (iki belge çelişmesin).
- `cli.py` iş mantığı içermez; servis fonksiyonlarını çağırır.
- `shell=True` kullanma (tek istisna: kullanıcının `command` doğrulayıcısında açıkça `shell: true` yazması).
- API anahtarı, token veya kişisel yol **hiçbir dosyaya, teste, log'a, commit'e** girmez. Testlerde sahte değer kullan.
- Gerçek ağa çıkan testler `@pytest.mark.live` ile işaretlenir; normal test koşusu ağsız çalışır.
- Her `open()` çağrısında `encoding="utf-8"`.
- Git komutları worktree işlemlerinde her zaman `cwd=` ile; ana depoda yıkıcı komut (`reset --hard`, `clean`) çalıştırma.
- Bağımlılık eklemeden önce Mimari §1'e bak; listede yoksa DECISIONS.md'ye gerekçe yaz.
- Var olan bir veritabanı migration dosyasını asla değiştirme; yeni migration ekle.
- YAML yazarken her zaman ruamel round-trip (kullanıcı yorumları korunur).

## Komutlar
```bash
uv sync                      # bağımlılıklar
uv run pytest                # testler (live hariç)
uv run pytest -m live        # gerçek servislerle (elle)
uv run ruff check . && uv run ruff format .
uv run pyright
uv run orkestra --help
```

## Faz bitiş kontrol listesi
- [ ] ruff, pyright, pytest temiz
- [ ] Fazın kabul kriterleri tek tek doğrulandı (raporda madde madde yaz)
- [ ] `docs/PROGRESS.md` güncellendi: yapılanlar, ertelenenler, bilinen sorunlar
- [ ] Sapmalar `docs/DECISIONS.md`'de
- [ ] `git diff` içinde sır/kişisel veri yok
- [ ] Commit: `feat(faz-N): kısa açıklama`

## Kod stili
- Python 3.11+, tam tip ipuçları, `from __future__ import annotations`.
- Kullanıcıya görünen her metin `t("anahtar")` ile (i18n); koda düz metin gömülmez. Yeni anahtar en az `en.yaml` ve `tr.yaml`'a eklenir (Faz 11'den sonra 5 dile).
- Kod, değişken adları, log mesajları, config anahtarları, JSON alanları ve işçi istemleri İngilizce.
- Hatalar `errors.py` hiyerarşisinden; çıplak `except:` yok.
- Fonksiyonlar küçük; dış etkiler (saat, uyku, alt süreç) testte enjekte edilebilir olsun.
