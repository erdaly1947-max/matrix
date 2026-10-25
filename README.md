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

## Kalıcı çalışma kuralları

Bu bölüm, proje boyunca uygulanacak çalışma düzenini tanımlar. Kullanıcının sonradan bildirdiği yeni kurallar bu bölüme eklenir; tekrar eden hükümler birleştirilir, hiçbir kuralın anlamı değiştirilmez. Buradaki kurallar, çelişen eski çalışma notlarına göre önceliklidir ve kullanıcı aksini belirtmedikçe geçerlidir.

### 1. Çalışma alanı ve kayıtların yeri

- Program yazımı, kod düzenleme ve bunlarla ilgili bütün çalışmalar yalnızca GitHub üzerinde yürütülür.
- Bu projeyle ilgili ChatGPT Kitaplığı'nda hiçbir kayıt, dosya veya klasör oluşturulmaz.
- Projenin kaynakları, gerekli dosyaları ve çalışma kuralları GitHub deposunda tutulur. Çalışma kuralları bu `README.md` dosyasında kayıt altına alınır.

### 2. Aşamalar, gereksinimler ve tasarım onayı

- İlk aşamada netleştirilen gereksinimler temel alınır. Her yeni aşama önceki aşamaların üzerine eklenir; önceki kararlar kaybedilmez veya birbirinden kopuk değerlendirilmez.
- İstenen davranış, programda nasıl uygulanacağı ve hangi mantıkla çalışacağı netleştirilir. Arayüz tasarımında sonucun kullanıcıya nasıl gösterileceği, hangi bilgilerin öne çıkarılacağı ve fırsat kararının nasıl anlaşılacağı somutlaştırılır.
- Henüz kesinleşmemiş konular kesin karar gibi sunulmaz. Kullanıcının onayladığı her öneri kesinleşmiş karar kabul edilir ve bütün tasarım içinde korunur.
- Önce gereksinimler kesinleştirilir, sonra programın davranışı ve arayüzü tasarlanır; tasarım bütünüyle tamamlanıp kullanıcı nihai onayını vermeden mevcut program kodlarında değişiklik yapılmaz.
- Tasarım ve onay süreci tamamlanmadan sonraki aşamaya geçilmez.

### 3. Her çalışmanın başında mevcut durumu belirleme

Her yeni çalışma başlangıcında şu bilgiler netleştirilir: mevcut sürüm, aktif aşama, README'de belirtilen gerçek tamamlanma durumu ve sıradaki iş. README, mevcut kod ve mevcut test sonuçları karşılaştırılarak gerçekten tamamlanmış işler ile doğrulanmış eksikler belirlenir. Tamamlanmış işler tekrarlanmaz; yalnızca gerçekten kalan eksikler üzerinde ilerlenir.

### 4. Kodlama, test ve değişiklik kaydı

- Birbiriyle ilişkili kodlama işleri anlamlı ve işlevsel gruplar hâlinde tamamlanır; işler gereksiz yere küçük parçalara ayrılmaz.
- Bir sürüm için belirlenen kodlama kapsamı tamamen bitmeden test çalıştırılmaz. Kodlama tamamlandığında ilgili testler topluca, ardından gerekli genel regresyon testleri çalıştırılır.
- Testlerde başarısız sonuç varsa gerekli düzeltmeler yapılır ve testler yeniden çalıştırılır. Başarısız testleri bulunan bir grup veya sürüm tamamlanmış sayılmaz.
- Kodlama ve testler tamamlandıktan sonra README ve sürüm kayıtları tek seferde güncellenir. Mümkün olduğunca ilgili kod değişiklikleri, testleri ve kayıtları tek commit altında toplanır.
- Tamamlanmış işler tekrar uygulanmaz. Her yeni değişiklik, doğrulanmış eksik veya onaylanmış yeni gereksinim üzerine yapılır.

### 5. Aşamalar arası bağlam aktarımı ve son ZIP paketi

- Her aşamanın sonunda, yeni sohbet odasında kesintisiz devam edilebilmesi için kesinleşmiş kararlar, tamamlanan işler, doğrulanmış eksikler ve sıradaki aşamanın amacı birlikte aktarılır.
- Bağlam aktarımı tamamlanmış sayılmadan önce güncel README kontrol edilir; aktarım README'deki gerçek durumla tutarlı olmalıdır.
- ZIP paketi hazırlanırken aktarılan dosyalar arasında BtcTurk evreni var onu yerleştirilir.
- Nihai ZIP paketi oluşturulmadan önce ilgili son aşamanın yapılacağı kullanıcıya bildirilir ve açık onayı alınır. Bu bildirim ve onay olmadan son ZIP paketi oluşturulmaz.
