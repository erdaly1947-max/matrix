# Analiz Raporu — Cloudflare Worker kurulumu

Bu servis, piyasa verisi geçidinden ayrıdır. Yalnızca teknik analiz raporunu alır ve güncel raporu saklar. Mevcut Binance/BtcTurk piyasa veri geçidine dokunmaz.

## Veri akışı

1. Masaüstü paneli aday ve teknik analiz verilerini analysis_report.py ile kompakt JSON'a dönüştürür.
2. Ham mum dizileri, yinelenen aday BTC bağlamı ve tanılama bilgileri dışarıda bırakılır.
3. JSON gzip ile sıkıştırılır; masaüstünde reports/analiz_raporu_*.json.gz olarak da saklanır.
4. Uygulama POST /api/report uç noktasına Content-Encoding: gzip ve Authorization: Bearer ... başlıklarıyla gönderir.
5. Worker gzip verisini açıp JSON şemasını doğrular, sıkıştırılmış baytları KV içindeki tek latest kaydına yazar.
6. ChatGPT'nin okuyacağı GET /latest uç noktası gzip'i açıp yalnızca analiz JSON'unu döndürür. Tanılama raporu bu uç noktada yayımlanmaz.

## Cloudflare'da ilk kurulum

1. Yeni bir KV namespace oluşturun; mevcut firsat-kontrol-market-data Worker'ını veya piyasa verisi ayarlarını değiştirmeyin.
2. wrangler.toml içindeki REPLACE_WITH_NEW_KV_NAMESPACE_ID alanına yeni namespace ID'sini yazın.
3. UPLOAD_TOKEN adıyla güçlü ve rastgele bir Worker secret oluşturun. Token'ı kaynak dosyaya, GitHub'a, rapora veya ekran görüntüsüne yazmayın.
4. cloudflare/report-worker klasöründen wrangler deploy çalıştırın.
5. https://<worker-host>/health ile sağlık uç noktasını; ardından yerel config ile bir deneme yüklemesini ve https://<worker-host>/latest okumasını doğrulayın.

## Masaüstü bağlantı ayarı

Örnek chatgpt_baglanti.example.json dosyasını aynı klasörde chatgpt_baglanti.local.json adıyla kopyalayın. upload_url, upload_token ve read_url alanlarını kendi Worker adresiniz ve secret değerinizle doldurun. Gerçek config dosyası .gitignore kapsamındadır; GitHub'a eklemeyin.

## Güvenlik ve sınırlar

- POST /api/report token olmadan veri kabul etmez.
- GET /latest herkese açık, salt okunur bir uç noktadır; yalnızca teknik analiz verisi yayımlar. Bu tasarım, ChatGPT gibi harici okuyucuların ek hesap kimlik doğrulaması olmadan raporu çekebilmesi içindir. Bu URL'yi gizli bir kişisel veri alanı olarak değerlendirmeyin.
- Tek KV anahtarı kullanılır; her başarılı yükleme güncel raporun üzerine yazar. Tarihsel rapor arşivi oluşturulmaz.
- KV yayılımı bölgesel olarak gecikebilir; yüklemeden hemen sonra başka bir konumdan okuma kısa süre eski veriyi döndürebilir.
- ChatGPT sohbetine otomatik mesaj gönderilmez. Sohbette /latest bağlantısından en güncel raporu okumasını istemek gerekir; ChatGPT erişimi gerçek kullanımda ayrıca doğrulanmalıdır.
- Sunucuya ulaşılamazsa yerel .json.gz dosyası korunur ve radarın çalışması durdurulmaz.
