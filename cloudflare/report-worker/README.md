# Analiz Raporu — Cloudflare Worker

Bu servis yalnızca teknik analiz raporunu alır ve güncel raporu saklar. Mevcut Binance/BtcTurk piyasa verisi geçidinden ayrıdır; ona dokunmaz.

## Dağıtılan uç noktalar

- Worker: `firsat-kontrol-analysis-report`
- Sağlık kontrolü: `https://firsat-kontrol-analysis-report.erdaly1947.workers.dev/health`
- Rapor yükleme: `POST https://firsat-kontrol-analysis-report.erdaly1947.workers.dev/api/report`
- Güncel raporu okuma: `GET https://firsat-kontrol-analysis-report.erdaly1947.workers.dev/latest`
- KV namespace: `FirsatKontrolAnalysisReports`

Worker ve KV, Cloudflare hesabında oluşturuldu. `ANALYSIS_REPORTS` KV binding'i ve `UPLOAD_TOKEN` gizli değeri yapılandırıldı. Yükleme token'ı hiçbir kaynak dosyaya veya GitHub'a konulmamalıdır.

## Veri akışı

1. Masaüstü paneli `analysis_report.py` ile adayları ve teknik analiz verilerini kompakt JSON'a dönüştürür.
2. Ham mum arşivleri ve genel tanılama/log verileri analiz raporuna dahil edilmez.
3. JSON gzip ile sıkıştırılır ve yerelde `reports/analiz_raporu_*.json.gz` olarak korunur.
4. Uygulama `POST /api/report` adresine `Content-Encoding: gzip` ve `Authorization: Bearer ...` başlıklarıyla gönderir.
5. Worker gzip'i açıp rapor türünü, şema sürümünü ve aday sayısını doğrular; sıkıştırılmış raporu KV'deki tek `latest` kaydına yazar.
6. `GET /latest` gzip'i açıp tam analiz JSON'unu döndürür. SHA-256 ve rapor zamanı yanıt başlıklarında bulunur.

## Masaüstü bağlantı ayarı

Örnek dosya `chatgpt_baglanti.example.json`, dağıtılan Worker adresini içerir. `chatgpt_baglanti.local.json` dosyasını uygulamanın ana klasörüne koyun ve `upload_token` alanına size özel token'ı girin. Gerçek config dosyası `.gitignore` kapsamındadır; GitHub'a veya başkasına göndermeyin.

## Doğrulama

1. `/health` adresi `ok: true` döndürmelidir.
2. İlk rapor yüklenmeden `/latest` adresi `404` döndürür; bu beklenen davranıştır.
3. Panelden **Analiz Raporu Gönder** işlemini çalıştırın. Başarılı yanıt aday sayısını, sıkıştırılmış boyutu ve SHA-256'yı bildirir.
4. Aynı sohbet içinde ChatGPT'den `https://firsat-kontrol-analysis-report.erdaly1947.workers.dev/latest` adresindeki güncel analiz raporunu açıp incelemesini isteyin. Uç noktaya ChatGPT erişimi ayrıca gerçek kullanımda doğrulanmalıdır.

## Güvenlik ve sınırlar

- `POST /api/report` geçerli token olmadan veri kabul etmez.
- `GET /latest` herkese açık ve salt okunurdur; bağlantıyı bilen herkes teknik analiz raporunu okuyabilir. Rapora özel/kişisel bilgi koymayın.
- Her başarılı yükleme önceki raporun üzerine yazar; tarihsel arşiv oluşturulmaz.
- KV'nin bölgeler arası yayılımı kısa gecikme yaratabilir.
- Sohbete otomatik mesaj gönderilmez; ChatGPT'ye güncel okuma bağlantısını açması istenir.
- Sunucuya ulaşılamazsa yerel gzip raporu korunur ve radar çalışmaya devam eder.
