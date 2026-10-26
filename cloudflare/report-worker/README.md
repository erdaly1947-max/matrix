# Fırsat-Kontrol Raporları — Cloudflare Worker

Bu servis üç rapor türünü ve sorun giderme ZIP dosyasını ayrı KV anahtarlarında saklar. Mevcut Binance/BtcTurk piyasa verisi geçidinden ayrıdır; ona dokunmaz.

## Uç noktalar

- Worker: `firsat-kontrol-analysis-report`
- Sağlık kontrolü: `GET /health`
- Analiz raporu yükle/oku: `POST /api/report` → `GET /latest`
- Günlük rapor yükle/oku: `POST /api/report/daily` → `GET /daily`
- Okunabilir sorun giderme raporu yükle/oku: `POST /api/report/troubleshooting` → `GET /troubleshooting`
- Devir ZIP dosyasını yükle/indir: `POST /api/report/troubleshooting-zip` → `GET /troubleshooting.zip`
- KV namespace: `FirsatKontrolAnalysisReports`

Temel URL: `https://firsat-kontrol-analysis-report.erdaly1947.workers.dev`

## Veri akışı

1. Masaüstü paneli raporları yerelde üretir ve `reports` klasöründe korur.
2. Bağlantı yapılandırması varsa her rapor ayrı bir arka plan HTTPS isteğiyle gönderilir.
3. Analiz ve günlük raporlar, ayrıca okunabilir sorun giderme raporu gzip JSON olarak aktarılır.
4. Sorun giderme ZIP'i ayrıca `application/zip` olarak gönderilir. ZIP ve okunabilir JSON birbirinden ayrı kaydedilir.
5. Her rapor türünün sabit okuma adresi vardır. Yeni yükleme yalnızca aynı türe ait önceki raporun üzerine yazar; diğer türler etkilenmez.
6. Yerel dosyalar gönderim başarılı olsa da korunur. Aktarım hatası radarın çalışmasını durdurmaz.

## Masaüstü yapılandırması

Masaüstü uygulaması Worker adresini kaynak kodundaki sabit değerlerden alır. Yükleme anahtarı Windows Kimlik Bilgileri Yöneticisi'nde genel kimlik bilgisi olarak saklanır; kaynak koda, loglara veya GitHub'a yazılmaz. Yükseltme sırasında eski chatgpt_baglanti.local.json dosyası bulunursa program açılışta yalnızca bilinen Worker adresini kabul eder; anahtar Windows kasasına kaydedilip geri okunarak doğrulanmadan dosya silinmez. İlk güncellemede ZIP mevcut program klasörüne ayıklanmalı ve eski dosya önceden silinmemelidir.

## İçerik ve bağlantılar

- Analiz: `/latest` — adaylar, puanlar ve teknik analiz.
- Günlük: `/daily` — durumun tam anlık görüntüsü, BTC bağlamı, tanı bilgisi ve okunabilir Markdown özeti.
- Sorun giderme: `/troubleshooting` — durum özeti, manifest, sınırlı log kuyruğu ve günlük rapor verisi.
- ZIP paketi: `/troubleshooting.zip` — dosya bütünlüğü doğrulanmış ZIP arşivi.

## Güvenlik ve sınırlar

- Tüm yükleme uç noktaları `Authorization: Bearer` token'ı gerektirir.
- Okuma uç noktaları bağlantıyı bilen herkesin erişimine açıktır. Raporlara parola, token veya başka gizli veri eklenmemelidir.
- Analiz, günlük ve sorun giderme JSON yüklemeleri ile ZIP yüklemesi 8 MiB sınırına tabidir.
- Cloudflare KV'nin yayılımı kısa gecikme yaratabilir.
- Sohbete otomatik mesaj gönderilmez; ChatGPT'de ilgili okuma bağlantısı açılarak rapor okunur.
- Sunucuya ulaşılamazsa yerel rapor dosyaları korunur ve radar çalışmaya devam eder.
