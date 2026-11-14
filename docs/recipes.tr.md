# Tarifler: gece kuyruğunu zamanlayıcıyla çalıştırmak

Orkestra servis kurmaz. `orkestra queue run` sıradan bir komuttur: kuyruğu bitirir ve çıkar.
Her gece başlaması için sistemin zamanlayıcısına çalıştırt.

> **Uyku kuyruğu durdurur.** Uyuyan veya hazırda bekleyen bilgisayar hiçbir şey çalıştırmaz.
> Gece uyanık tut ya da zamanlayıcı uyandırsın (Windows: "Bu görevi çalıştırmak için
> bilgisayarı uyandır"). Yarıda kalan çalıştırma kaybolmaz: `running` kalan işler bir sonraki
> `queue run` başlarken yeniden `pending` olur.

## Gün içinde

```bash
cd ~/projeler/uygulamam
orkestra queue add tasks/docstrings.yaml                 # şimdi denetlenir, sonra çalışır
orkestra queue add tasks/tests-batch.yaml --profile cheap
orkestra queue list
```

Her iş eklendiği klasörü hatırlar. Çalışırken göreli yollar ve projenin `orkestra.yaml`'ı
oradan okunur; yani zamanlayıcı `queue run`'ı herhangi bir klasörde başlatabilir. `--profile`
verilmezse iş `queue.default_profile` ile (varsayılan `cheap`) çalışır.

## Zamanlanacak komut

```bash
orkestra queue run --until 07:00 --notify
```

- `--until 07:00`: 07:00'dan sonra yeni iş başlamaz; çalışan iş biter.
- `--max-cost-usd 0.50`: 0.50 USD harcanınca yeni iş başlamaz; tahmini kalan tutarı aşan iş
  atlanır. `--max-cost-usd 0` yalnız ücretsiz işleri çalıştırır. Bayrak yoksa maliyet onayı
  isteyecek batch atlanır (cevap verecek kimse yok) ve kuyrukta kalır; tek görev
  `orkestra run`'daki gibi hiç sormaz.
- `--notify`: sonunda yalnız sayıları içeren tek bildirim ("5 bitti, 1 başarısız").
- Aynı anda yalnız bir `queue run` çalışır; ikincisi 5 koduyla çıkar. Çöken bir çalıştırmanın
  bıraktığı kilit kendiliğinden temizlenir.

Sabah: `orkestra status`, sonra `orkestra review` ve `orkestra apply`.

## Bildirimler

```yaml
notify:
  desktop: true                      # ek paket gerekir: uv tool install "orkestra-cli[notify]"
  ntfy_topic_env: ORKESTRA_NTFY_TOPIC
```

Telefon bildirimi [ntfy](https://ntfy.sh) üzerinden: uygulamayı kur, uzun ve tahmini zor bir
konu adına abone ol, bu adı `ntfy_topic_env`'in gösterdiği ortam değişkenine yaz (config
dosyasına değil). Konuyu bilen herkes okuyabilir; bu yüzden bildirimde görev metni, kod veya
dosya adı asla olmaz. `orkestra notify test` ile dene.

## Linux ve macOS: cron

Önce tam yolu bul; cron kısa bir `PATH` ile başlar:

```bash
command -v orkestra          # örneğin /home/sen/.local/bin/orkestra
crontab -e
```

```cron
# her gece 23:00'te; 07:00'dan sonra yeni iş başlatma
0 23 * * * ORKESTRA_NTFY_TOPIC=uzun-konu-adin /home/sen/.local/bin/orkestra queue run --until 07:00 --notify >> /home/sen/.orkestra/queue.log 2>&1
```

cron'dan masaüstü bildirimi genelde görünmez (cron'un masaüstü oturumu yoktur); orada ntfy
kullan. macOS'ta launchd da aynı işi görür; çoğu kurulum için cron yeter.

## Windows: Görev Zamanlayıcı

PowerShell'de tam yolu bul:

```powershell
(Get-Command orkestra).Source    # örneğin C:\Users\sen\.local\bin\orkestra.exe
setx ORKESTRA_NTFY_TOPIC "uzun-konu-adin"   # isteğe bağlı, telefon bildirimi için
```

Görevi oluştur (her gün 23:00):

```powershell
schtasks /Create /SC DAILY /ST 23:00 /TN "Orkestra queue" /TR "\"C:\Users\sen\.local\bin\orkestra.exe\" queue run --until 07:00 --notify"
```

Ya da PowerShell ile, "uyandırarak çalıştır" seçeneğiyle:

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\Users\sen\.local\bin\orkestra.exe" -Argument "queue run --until 07:00 --notify"
$trigger = New-ScheduledTaskTrigger -Daily -At 23:00
$options = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable
Register-ScheduledTask -TaskName "Orkestra queue" -Action $action -Trigger $trigger -Settings $options
```

Masaüstü bildirimi yalnız görev senin hesabınla ve sen oturum açıkken çalışınca görünür
("Yalnızca kullanıcı oturum açtığında çalıştır"). Sonucu `orkestra queue list` ile veya Görev
Zamanlayıcı'nın geçmişinde gör.
