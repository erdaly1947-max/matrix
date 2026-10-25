# Fırsat-Kontrol Paneli — başlangıç kaynak kodu

Bu depo, İki Radarlı Spot Trade / Fırsat-Kontrol Paneli projesinin başlangıç kaynak kodudur. Var olan motor ve analiz modülleri korunmuş; eksik iki dosya eldeki motor sözleşmeleri, ayarlar ve kullanım kılavuzu temel alınarak yeniden oluşturulmuştur.

## Başlangıç sürümündeki dosyalar

- `binance_erken_firsat_radari.py`: Binance Spot piyasa verisi analiz motoru.
- `radar_core.py`: teknik analiz, aday değerlendirme ve koşullu risk planı.
- `ortak_piyasa.py`, `tek_motor_evreni.py`: halka açık piyasa uç noktaları ve yerel USDT parite listesi.
- `binance_mum_arsivi.py`, `sinyal_kaydi.py`: kapanmış mum arşivi ve sinyal izleme kayıtları.
- `tek_motor_paneli.pyw`: mevcut motorun durum JSON'u ve komut satırı arayüzüyle uyumlu olacak şekilde yeniden oluşturulmuş Tkinter paneli.
- `veri_yasam_dongusu.py`: eski aday geçmişi CSV'lerini aylık ZIP arşivine doğrulayarak taşıyan ve yalnızca eski, PID etiketli geçici dosyaları temizleyen bakım modülü.
- `btcturk_usdt_spot.json`: yüklenen yerel başlangıç parite listesi. Motor, `data/` altında henüz liste yoksa bu kök dizindeki kopyayı da arar.
- `BASLAT.bat`, `ayarlar.json`, `requirements.txt`, `KULLANIM_KILAVUZU.txt` ve `firsat_kontrol.ico`: başlatma, yapılandırma, bağımlılıklar, kullanım ve görsel kaynakları.

## Çalışma sınırları

Program halka açık piyasa verilerini okur; borsa hesabına bağlanmaz, bakiye/pozisyon bilgisi istemez, emir göndermez ve otomatik alım-satım yapmaz. A/B/C aşamaları araştırma durumlarıdır, kârlılık garantisi veya emir değildir.

## Başlatma

Windows'ta depoyu indirip tüm dosyaları aynı klasörde tutun ve `BASLAT.bat` dosyasını çalıştırın. Başlatıcı Python, Tkinter ve `requirements.txt` paketlerini kontrol eder.

## Doğrulama notu

Başlangıç sürümünde Python sözdizimi ve depolama bakımının arşivleme/SHA-256 akışı daha önce kontrol edilmiştir. Bu komisyon/kayma hesabını kaldıran son değişiklik GitHub kaynakları üzerinden statik olarak gözden geçirildi; bu son değişiklikten sonra yerel Python derleyicisiyle yeniden derleme ve Windows üzerinde canlı Binance/BtcTurk uçtan uca çalışma testi yapılmadı. **Bu commit bitmiş/dağıtıma hazır ZIP olarak değerlendirilmemelidir.**

`ayarlar.json` komisyon/kayma ayarlarını içermez. Program bu oranları hesaplamaz ve karar/alarmlarda kullanmaz. Güçlü fırsat kapısı, en yakın teknik hedef için brüt teknik risk/getiri oranının en az 1,5 olmasını ister; spread ayrı likidite filtresinde değerlendirilir.
