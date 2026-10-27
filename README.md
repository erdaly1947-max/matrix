# Fırsat-Kontrol Paneli — başlangıç kaynak kodu 00.SÜRÜMÜNÜN SON HALİ

## 26 Ekim 2026 — Sürüm 00 masaüstü panel düzenlemesi

Bu düzenleme masaüstü arayüzünü ve kullanıcıya sunulan durum bilgisini iyileştirir; Binance analiz motorunun puanlama, aday değerlendirme ve güçlü fırsat koşullarını değiştirmez.

- Aday tablosu kısa ve tek bakışta okunabilir tutulur: öncelik, coin, Binance USDT fiyatı, BtcTurk USDT fiyatı, fırsat puanı, zaman dilimi, A/B/C aşaması, veri durumu ve son karar.
- Binance ile BtcTurk fiyat farkı sütunu eklenmez. Keşif yolu, BTC göreli güç/korelasyon ayrıntıları ve teknik plan seçilen coin bölümünde kalır.
- Güncel olmayan veya eksik veriye sahip bir aday güçlü fırsatın yeşil vurgusunu alamaz; veri uyarısı ayrı tutulur.
- Seçilen coin bölümünde koşullu giriş bölgesi, kırılım, zarar durdurma ve en fazla üç teknik hedef öne çıkarılır. Canlı veri lacivert, eski/eksik veri turkuaz; senaryo yeşil, giriş nötr, kırılım sarı, stop kırmızı, hedefler lila ile ayrılır. Karar/puan satırı karar durumuna göre renklendirilir.
- Güçlü fırsat alarmı üç çift tonlu zil, zarar durdurma geçişi dört daha yüksek perdeli kısa ton kullanır. Düğmenin adı **Ses Testi** olup yalnızca mevcut alarm sesini sınar; “Fırsat Testi” adlı bir motor işlevi yoktur.
- Eylem/rapor düğmeleri kırmızı, seviye takibi ve alarm/ses test düğmeleri turkuaz, ince oval kapsül biçimindedir. Seviye takibi, sesli bildirim ve ses testi üst satırda; sorun giderme ZIP'i, ses seviyesi ve panel ışığı alt satırda bulunur. Kaydırma çubukları inceltilmiştir; adaylar ile seçilen coin arasında dikey ayırıcı yoktur. Panel ışığı yüzde 0–100 aralığındadır.
- Panelin nötr arka planı koyu gri, standart metinleri beyazdır. Üst sağdaki canlı durum yazısı canlı akış güncelse parlak yeşil, motor çalışırken güncel değilse kırmızıdır. Seçilen coin ve kanıtlar bölümü Segoe UI yazı tipinde bir punto büyütülmüştür; teknik karar vurguları canlı renklerini korur.
- Motor kapanınca seviye takibi otomatik olarak kapatılır; arayüz açık takip yapılıyormuş izlenimi bırakmaz.
- Yıldız, coin adının önünde gösterilir; aday tablosu ve seçilen coin alanında ince yatay/dikey kaydırma çubukları bulunur. Düğme adları sade Türkçedir.
- Kısa ve tüm düğmeleri açıklayan kullanım kılavuzu `KULLANIM_KILAVUZU.txt` dosyasındadır ve dağıtım ZIP'ine eklenir.
- Arayüz değişiklikleri için başsız CI kontrol testleri eklendi. Bu kontroller motor birim testlerinin ve Windows üzerinde gerçek uygulama açılışının yerine geçmez.

### Dağıtım paketi kuralı

Her `main` gönderiminde derleme, birim testleri, bulut Worker testleri ve canlı piyasa geçidi doğrulamaları çalışır. Olağan kod gönderimleri ZIP üretmez ve indirme dosyalarını değiştirmez. Programın dağıtım ZIP'i yalnızca kullanıcı son paketlemeyi istediğinde `workflow_dispatch` (iş akışını elle başlatma) ile veya kullanıcı onayıyla kullanılan commit mesajındaki `[package]` işareti bulunduğunda hazırlanır. Paketleme sırasında ZIP, SHA-256 doğrulama dosyası, Release dosyaları ve Actions artefaktı oluşturulur. Programı kullanmak için yalnızca program ZIP'ini indirmen yeterlidir; diğer teknik dosyaları indirmen gerekmez. Testler başarısızsa paketleme adımları çalışmaz.


Bu depo, Var olan motor ve analiz modülleri korunmuş, ayarlar ve kullanım kılavuzu temel alınarak yeniden oluşturulmuştur.

## 27 Ekim 2026 — Güncel çalışma durumu

- **Render üzerinden piyasa verisi:** Programın piyasa verisini Render geçidi üzerinden alabildiği güncel çalışma durumudur.
- **Bulut rapor aktarımı ve okuma:** Program raporları buluta gönderebiliyor; buluttaki okuma uçları üzerinden ChatGPT'nin bu raporları okuyabilmesi için gereken geliştirmeler yapıldı ve işleyiş doğrulandı.
- Eski Python/JavaScript otomatik testleri ve Actions sonuçları güncel çalışma durumunun yerine geçmez; yalnızca yardımcı regresyon kontrolleridir. Güncel işlevsellik, gerçek programın Render üzerinden veri alması ve raporların bulutta okunabilmesiyle değerlendirilir.
- Bir sonraki incelemede bu veri/rapor akışında gerçek bir eksik tespit edilirse programın kodunda düzeltilir. Tarihsel backtest ve Windows masaüstü arayüzünün görsel/etkileşim kontrolü ayrı, açık işlerdir.

## 26 Ekim 2026 — Bulut rapor aktarımı ve bağlantı testinin devir notu

### Sonuç: Raporları buluta gönderme ve ChatGPT'nin okuyabilmesi doğrulandı

Bu işin temel amacı, Fırsat-Kontrol Paneli'nin raporlarını buluta göndermek ve ChatGPT'nin bu raporları kullanıcı her seferinde yerel dosya eklemek zorunda kalmadan okuyabilmesini sağlamaktı. **26 Ekim 2026 tarihinde bu amaç bulut aktarımı açısından başarıyla test edildi.** Kullanıcı programı çalıştırarak raporları yeniden gönderdi; Cloudflare KV kayıt zamanları ve içerik özetleri yenilendi. Üç JSON raporunun içeriği doğrudan buluttaki okuma uç noktalarından okunabildi ve sorun giderme ZIP'inin yükleme kaydı da doğrulandı.

Kullanılan okuma adresleri:
- Analiz raporu JSON: `/latest`
- Günlük rapor JSON: `/daily`
- Sorun giderme raporu JSON: `/troubleshooting`
- Sorun giderme ZIP: `/troubleshooting.zip`

Temel Worker adresi: `https://firsat-kontrol-analysis-report.erdaly1947.workers.dev`. Rapor gönderme uç noktaları token doğrulaması ister; okuma uç noktaları şu an URL'yi bilenler tarafından erişilebilir. Bu nedenle raporlara gizli anahtar veya hassas erişim bilgisi konulmamalıdır.

### Kod durumu: Bu işlevler Sürüm 00 program koduna eklendi

Bu yalnızca tasarım veya plan notu değildir; gerekli uygulama kodu GitHub deposundaki Sürüm 00 kaynaklarına işlendi ve Worker'a dağıtıldı:
- `analysis_report.py`: analiz, günlük ve okunabilir sorun giderme JSON raporlarını gönderen ortak yükleme işlevleri ile sorun giderme ZIP yükleme işlevi.
- `tek_motor_paneli.pyw`: panelde analiz raporu gönderme, günlük rapor oluşturup gönderme ve sorun giderme paketi gönderme işlemleri. Sorun giderme düğmesi, okunabilir sorun giderme JSON'u ile ZIP paketini birlikte gönderir; bu nedenle bunun için ayrı dördüncü düğme gerekmez.
- `cloudflare/report-worker/src/index.js`: dört tür yüklemeyi Cloudflare KV'ye kaydeden ve raporları okunabilir adreslerden sunan Worker rotaları.
- `cloudflare/report-worker/test/index.test.js` ve README belgeleri: yükleme/okuma yolları için testler ve teknik kayıt.

26 Ekim tarihli doğrulama/paketleme çalıştırmasında Sürüm 00 ZIP'i ve SHA-256 doğrulama dosyası Release'e yayımlanmıştı. 27 Ekim 2026 tarihli kurala göre paketleme yalnızca kullanıcı açıkça istediğinde yapılır. Paketlemeyle ilişkili diğer teknik çıktılar korunur; programı indirmek için yalnızca ZIP dosyasına ihtiyacın vardır. Mevcut motor veya arayüz işlevi hata verirse o hata ayrıca incelenmelidir.

### Ev interneti üzerinden bağlantı:kesin olarak doğrulandı program ev internetinden render sayesinde veri alıyor.

Bulut aktarımının ve ChatGPT tarafından okunabilmesinin çalıştığı doğrulandı.
### Sonraki çalışma odağı

Buluta rapor gönderme ve raporları ChatGPT'nin okuyabilmesi için temel işlev tamamlandı ve doğrulandı. Sonraki çalışma bu akışı baştan tekrarlamak değil, **Sürüm 00 motor işlevlerindeki gerçek aksaklıkları gidermek, programı kullanım amacı için geliştirmek ve arayüzü tek bakışta anlaşılır hâle getirmek** olmalıdır. Motor ve arayüz kapsamı değiştirilmeden önce mevcut README, son GitHub commit'i ve programın gerçek kullanımda doğrulanan güncel durumu esas alınır; Python/JavaScript otomatik testleri yalnızca yardımcı regresyon kontrolüdür.

## Yerel rapor dosyaları — sabit adlar

Raporlar `reports/` klasöründe her üretimde aynı dosyaların üzerine yazılır; tarih-saat ekli yeni rapor dosyaları oluşturulmaz.

- Günlük/durum JSON raporu: `firsat_kontrol_raporu.json.gz`
- Günlük Markdown özeti: `firsat_kontrol_raporu.md.gz`
- Günlük tanı özeti: `firsat_kontrol_raporu_tani.json.gz`
- Teknik analiz raporu: `analiz_raporu.json.gz`
- Sorun giderme/devir paketi: `firsat_kontrol_devir.zip`

Başarılı yeni üretimden sonra program yalnızca kendi eski tarihli rapor adlandırma kalıplarıyla eşleşen dosyaları temizler. Diğer dosyalara dokunulmaz. Raporların JSON içerikleri yerelde gzip ile sıkıştırılır; devir paketi ZIP olarak oluşturulur. Buluta JSON raporları gzip sıkıştırmasıyla, devir paketi ise ZIP ikili dosyası olarak gönderilir. Bulut okuma uç noktaları JSON içeriğini açarak okunabilir biçimde sunar.

## Başlangıç sürümündeki dosyalar şunlardı

- `binance_erken_firsat_radari.py`: Binance Spot piyasa verisi analiz motoru.
- `radar_core.py`: teknik analiz, aday değerlendirme ve koşullu risk planı.
- `ortak_piyasa.py`, `tek_motor_evreni.py`: halka açık piyasa uç noktaları ve yerel USDT parite listesi.
- `binance_mum_arsivi.py`, `sinyal_kaydi.py`: kapanmış mum arşivi ve sinyal izleme kayıtları.
- `tek_motor_paneli.pyw`: mevcut motorun durum JSON'u ve komut satırı arayüzüyle uyumlu olacak şekilde yeniden oluşturulmuş Tkinter paneli.
- `veri_yasam_dongusu.py`: eski aday geçmişi CSV'lerini aylık ZIP arşivine doğrulayarak taşıyan ve yalnızca eski, PID etiketli geçici dosyaları temizleyen bakım modülü.
- `btcturk_usdt_spot.json`: yüklenen yerel başlangıç parite listesi. Motor, `data/` altında henüz liste yoksa bu kök dizindeki kopyayı da arar.
- `BASLAT.bat`, `ayarlar.json`, `requirements.txt`, `KULLANIM_KILAVUZU.txt` ve `firsat_kontrol.ico`: başlatma, yapılandırma, bağımlılıklar, kullanım ve görsel kaynakları.

## Çalışma sınırları

Program halka açık piyasa verilerini okur; borsa hesabına bağlanmaz, bakiye/pozisyon bilgisi istemez, emir göndermez ve otomatik alım-satım yapmaz. A/B/C aşamaları araştırma durumlarıdır, kârlılık garantisi veya emir değildir.Öngörü oluşturmak içindir.

## Başlatma

Windows'ta kaynak arşivini ayrı bir klasöre ayıklayın, gerekli kaynak dosyaları aynı klasörde tutun ve `BASLAT.bat` dosyasını çalıştırın. Başlatıcı Python, Tkinter ve `requirements.txt` paketlerini kontrol eder.

GitHub'ın `main` dalı ZIP'i kaynak arşividir; bağımsız dağıtım paketiyle aynı şey değildir. Dağıtım paketi ancak derleme, otomatik testler ve ZIP bütünlük kontrolü başarılı olup program ZIP'i Release'e yayımlandığında doğrulanmış sayılır.

## Doğrulama notu

Kaynak koddaki program sürüm etiketi `radar_core.py` içinde `APP_VERSION = "00"` olarak tutulur.

**26 Ekim 2026 — panel ayarları ile motor ayarlarını ayırma düzeltmesi:** [Commit `86ebc63d`](https://github.com/erdaly1947-max/matrix/commit/86ebc63d1ab80de924df6a4f060966ae4e5a12db) içinde `ayarlar.json` dosyasının iki özeti tutulur: tam dosya SHA-256 özeti tanılama için korunur; `panel_ui` alanı hariç tutularak hesaplanan `settings_runtime_sha256` motorun yeniden başlatma gerektiren ayar değişikliklerini izler. Böylece alarm sesi, ses düzeyi veya panel görünümü tercihi değişikliği tek başına canlı akışı geçersiz kılmaz. Motor ayarları değişirse ya da ayar dosyası okunamaz/geçersiz olursa yeniden başlatma uyarısı korunur. Durum çıktısı tam dosya özetini ve motor ayarı özetini ayrı raporlar.

[Doğrulama çalıştırması #40238052373](https://github.com/erdaly1947-max/matrix/actions/runs/40238052373) başarıyla tamamlandı: **51 Python birim testi** geçti; derleme, JSON doğrulaması, JavaScript ve Render geçidi testleri, canlı Binance Spot mum/WebSocket ve BtcTurk USDT doğrulaması ile ZIP/SHA-256/Release güncellemesi başarılı oldu. Bu çalışma yalnızca kod ve bulut doğrulamasıdır; kullanıcının Windows masaüstünde panel etkileşimi hâlâ ayrıca test edilmelidir.

**25 Ekim 2026 — motor durum ayrımı ve regresyon doğrulaması:** [Motor düzeltmesi commit'i](https://github.com/erdaly1947-max/matrix/commit/ab1c7d7d8a21ca8bf2b37d652a49d6d294737048) üzerinde canlı WebSocket sağlığı, geçmiş mum hazırlığı ve genel motor durumu ayrıştırıldı. WebSocket zaman damgaları ile saat aynı kilitli görüntüden alınır; doldurulamayan tarihsel mum boşlukları için yalnızca bu tür hatalarda yeniden deneme aralığı en az 24 saate çıkarılır. Geçici bağlantı hatalarının normal yeniden deneme davranışı korunur. Panel güçlü fırsat alarmı ve seviye takibinde genel geçmiş mum uyarısı yerine canlı akış durumunu ve adayın kendi veri/yeterlilik kapılarını kullanır. Raporlarda canlı akış ve geçmiş mum durumları ayrı gösterilir.

[GitHub Actions doğrulama çalıştırması #40233230870](https://github.com/erdaly1947-max/matrix/actions/runs/40233230870) başarıyla tamamlandı. Python 3.14.8 üzerinde kaynak derlemesi, ayar JSON doğrulaması ve otomatik Python birim testleri geçti. Bulut geçidi JavaScript testleri, Render sağlık kontrolü, Binance borsa sembol listesi (3.736 sembol), BTCUSDT 5 dakikalık mum verisi, BtcTurk USDT ticker verisi ve Render üzerinden canlı Binance WebSocket mum akışı doğrulandı. Bu tarihli çalışmada ZIP bütünlük kontrolü, SHA-256 üretimi ve GitHub Release dosyalarının güncellenmesi de başarılı oldu. O dönem için geçerli olan her gönderimde paketleme davranışı, 27 Ekim 2026 tarihli politika düzeltmesiyle kaldırılmıştır. Kalıcı indirme bağlantıları [Sürüm 00 Release sayfasındadır](https://github.com/erdaly1947-max/matrix/releases/tag/surum-00).

**Ayrı açık işler**

Tarihsel backtest ve Windows masaüstü panelinin görünüm/etkileşim kontrolü ayrı işler olarak kalır. Programın Render üzerinden piyasa verisi alması ve raporların buluta gönderilip buluttan okunabilmesi, güncel çalışma durumu olarak doğrulanmıştır.

`ayarlar.json` komisyon/kayma ayarlarını içermez. Program bu oranları hesaplamaz ve karar/alarmlarda kullanmaz. Güçlü fırsat kapısı, en yakın teknik hedef için brüt teknik risk/getiri oranının en az 1,5 olmasını ister; spread ayrı likidite filtresinde değerlendirilir.

## Sürüm 00 — başlangıç noktası ve geçerli durum

- **Sürüm 00, geliştirmelerin başlangıç tabanıdır.** Bu aşamada amaç, mevcut tek motorlu programı ve işlevlerini inceleyip başlangıç noktasını tutarlı ve doğrulanabilir hâle getirmektir; programı baştan yazmak değildir.
- Kaynak koddaki program sürüm etiketi, radar_core.py içinde APP_VERSION = "00" olarak tutulur.
- Sürüm 00 başlangıç hazırlığında README çalışma kuralları ile kaynak koddaki sürüm etiketi tutarlılaştırılmıştır. Bu kayıt, aşağıda tasarlanan yeni özelliklerin uygulanmış olduğu veya programın son ZIP paketinin dağıtıma hazır olduğu anlamına gelmez.
- main, sürüm 00'ın temel kodunu korur. Bu başlangıç hazırlığı tamamlandıktan sonra yeni özelliklerin kod değişiklikleri ayrı, sürüm/iş kapsamı açık yan dallarda yürütülür.
- **Dal açma yetkisi kullanıcı onayına bağlıdır:** Kullanıcı önceden açıkça onay vermeden hiçbir nedenle yeni dal açılmaz. Sürüm 00 düzeltmeleri `main` üzerinde yapılır. Sürüm 1 için kullanıcı onay verirse kullanılacak dal adı `1.surum-readme-gereksinimler` olacaktır.

## Kalıcı çalışma kuralları

Bu bölüm, proje boyunca uygulanacak çalışma düzenini tanımlar. Kullanıcının sonradan bildirdiği yeni kurallar bu bölüme eklenir; tekrar eden hükümler birleştirilir, hiçbir kuralın anlamı yorumlanmaz, değiştirilmez. Buradaki kurallar, çelişen eski çalışma notlarına göre önceliklidir ve kullanıcı aksini belirtmedikçe geçerlidir.

### 1. Çalışma alanı ve kayıtların yeri

- Program yazımı, kod düzenleme ve bunlarla ilgili bütün çalışmalar yalnızca GitHub üzerinde yürütülür.
- **Kesin dal kuralı:** Kullanıcıya önceden haber vermeden ve açık onayını almadan yeni Git dalı açılmaz. Bu kural tüm aşamalarda geçerlidir.
- Bu projeyle ilgili ChatGPT Kitaplığı'nda hiçbir kayıt, dosya veya klasör oluşturulmaz.
- Projenin kaynakları, gerekli dosyaları ve çalışma kuralları GitHub deposunda tutulur. Çalışma kuralları bu `README.md` dosyasında kayıt altına alınır.

### 2. Aşamalar, gereksinimler ve tasarım onayı

- İlk aşamada netleştirilen gereksinimler temel alınır. Her yeni aşama ve kod önceki aşamaların üzerine eklenir; önceki kararlar kaybedilmez veya birbirinden kopuk değerlendirilmez.
- İstenen davranış, programda nasıl uygulanacağı ve hangi mantıkla çalışacağı netleştirilir önce. Arayüz tasarımında sonucun kullanıcıya nasıl gösterileceği, hangi bilgilerin öne çıkarılacağı ve fırsat kararının nasıl anlaşılacağı somutlaştırılır.
- Henüz kesinleşmemiş konular kesin karar gibi uygulanmaz kullanıcıya sorulur. Kullanıcının onayladığı her öneri kesinleşmiş karar kabul edilir ve bütün tasarım içinde korunur.
- Önce gereksinimler kesinleştirilir, sonra programın davranışı moyor fonksiyonları ve arayüzü tasarlanır; tasarım bütünüyle tamamlanıp kullanıcı nihai onayını vermeden mevcut program kodlarında değişiklik yapılmaz önce kısaca açıklayıp sorulur.
- Tasarım ve onay süreci tamamlanmadan sonraki aşamaya geçilmez.

### 3. Her çalışmanın başında mevcut durumu belirleme

Her yeni çalışma başlangıcında şu bilgiler netleştirilir: mevcut sürüm, aktif aşama, README'de belirtilen gerçek tamamlanma durumu ve sıradaki iş. README, mevcut kod ve mevcut test sonuçları karşılaştırılarak gerçekten tamamlanmış işler ile doğrulanmış eksikler belirlenir daha önce başarılı olan testler tekrarlanmaz. Tamamlanmış işler tekrarlanmaz; yalnızca gerçekten kalan eksikler üzerinde ilerlenir.

### 4. Gereksinim kaydı, kodlama, test ve durum güncellemesi

- Gereksinimler, kabul edilmiş tasarım kararları ve uygulama yöntemi kodlamadan önce README'ye kaydedilir. Tasarım onayı alınmadan ilgili kodda değişiklik yapılmaz önce sorulur.
- Birbiriyle ilişkili kodlama işleri anlamlı ve işlevsel gruplar hâlinde tamamlanır; işler gereksiz yere küçük parçalara testlere ayrılmaz.
- Bir kodlama grubu için belirlenen kapsam bitmeden o gruba ait test turu başlatılmaz. Kodlama tamamlanınca ilgili testler topluca, ardından gerekli genel regresyon testleri çalıştırılır.
- Testlerde başarısız sonuç varsa gerekli düzeltmeler yapılır ve etkilenen testler yeniden çalıştırılır. Başarısız testleri bulunan bir grup veya sürüm bir daha kontrol edilir.
- **Gereksinim ve tasarım kaydı ile uygulama durumu kaydı birbirinden ayrıdır:** Gereksinimler ve planlanan davranış önceden yazılır; uygulamanın tamamlandığı, test edildiği veya başarılı olduğu bilgileri yalnızca gerçek kod ve test kanıtları görüldükten sonra güncellenir kullanıcıya bildirilir.
- İlgili uygulama ve test grubu tamamlandığında sonuçlar, kalan eksikler ve sürüm kayıtları README'de gerçeğe uygun biçimde güncellenir. Uygun olduğunda ilgili kod, test ve durum kayıtları tek commit altında toplanır.
- Tamamlanmış işler tekrar uygulanmaz. Her yeni değişiklik doğrulanmış bir eksiğe veya kullanıcı tarafından onaylanmış yeni bir gereksinime dayanır.

### 5. Dal, sürüm, aşamalar arası aktarım ve son ZIP paketi

- Sürüm 00  tabanıdır. Bu başlangıç hazırlığında README ve kaynak koddaki APP_VERSION etiketi "00" olarak tutarlılaştırılır. Bu hazırlık, planlanan yeni özelliklerin uygulanmış olduğu anlamına gelmez.
- **Dal açılmadan önce açık kullanıcı onayı zorunludur.** Onay olmadan dal oluşturulmaz sorulur, yeniden adlandırılmaz veya başka bir dal geliştirme alanı olarak seçilmez. Sürüm 00'a ait başlangıç/düzeltme işleri `main` üzerinde yürütülür. Kullanıcı Sürüm 1 dalı açılmasını onaylarsa dal adı tam olarak `1.surum-readme-gereksinimler` olur ve 00 sürümün son halinin tüm kodu yeni dala kopyalanır ve artık onun uzerinde geliştirme yapılır ilk main dalına artık müdahale edilmez. Bu yeni dalda geliştirme yapılması da yalnızca onaylanan kapsamla sınırlıdır.
- Yan dalda yapılan değişiklikler gerekli hesaplama, regresyon, geçmiş veri, panel, raporlama ve paket kontrolleri tamamlanmadan main dalına aktarılmaz. Sürüm 1 ancak bu kontroller ve ilgili kullanıcı onayı sonrasında hazırlanır.
- Her aşamanın sonunda, yeni sohbet odasında kesintisiz devam edilebilmesi için kesinleşmiş kararlar, tamamlanan işler, doğrulanmış eksikler ve sıradaki aşamanın amacı birlikte özet olarak aktarılır.
- Bağlam aktarımı tamamlanmış sayılmadan önce güncel README kontrol edilir; aktarım README'deki gerçek durumla tutarlı olmalıdır.
- ZIP paketi hazırlanırken aktarılan dosyalar arasında BtcTurk evreni bulunur, fan tokenler hariç olmalı.
- Nihai ZIP paketi oluşturulmadan önce son paket aşaması kullanıcıya bildirilir,sorulur ve açık onayı alınır. Bu bildirim ve onay olmadan ZIP paketi oluşturulmaz.

## Geliştirme hedefi ve ortak karar sistemi

### 6. Ana karar: mevcut bilgisayar programını koru, üzerine geliştir

Programın amacı,kulanıcının para kazanmasına yönelik, mevcut sistemi koruyarak hızlı yükseliş potansiyeli taşıyan coinleri daha erken ve daha isabetli değerlendirmektir. İlk hedef, mevcut motorun yaptığı hesaplamaları yeniden yazmak değil; eksik kalan yönlerini mevcut işlevler üzerinden geliştirmek ve sonuçlarını ortak bir karar yapısında birleştirerek arayüzde bir bakışta anlaşılacak şekilde yansımasını sağlamaktır.

- Mevcut program baştan yazılmaz; kullanıcı istemedikçe, çalışan ve gerekli işlevler korunur asla bozulmaması sağlanır.
- Aynı gösterge, piyasa verisi veya teknik seviye hesabı farklı yerlerde gereksiz yere tekrarlanmaz. Mevcut hesaplamaların çıktıları yeniden kullanılabilir ve ihtiyaç duyulan geliştirmeler uygun mevcut modüle bağlanır.
- Yeni bir fonksiyon veya modül kulllanıcı isterse veya  mevcut işlevin geliştirilmesiyle ihtiyacın karşılanamayacağı kod incelemesiyle gösterildiğinde değerlendirilir.
- Yeni özelliklerin aday sıralamasını, A/B/C aşama sınıflandırmasını, alarmları veya mevcut panel davranışını değiştirmesi tasarımda açıkça belirtilir; sessiz ve doğrulanmamış davranış değişikliği yapılmaz.
- Amaç, ilk bakışta piyasanın durumunu, hangi coinlerin neden öne çıktığını ve seçilen coindeki olası getirinin riskine değip değmediğini anlamayı sağlamaktır. Ayrıntılı analizler ve mevcut işlevler erişilebilir kalır.
- Program halka açık piyasa verilerini okuyan bir analiz ve karar destek aracıdır. Bu gereksinimler kendi başına borsa hesabına bağlanma, emir gönderme veya otomatik alım-satım yetkisi oluşturmaz.

### 7. İlk somut iş: mevcut–eksik–geliştirme–test matrisi

Yeni kod yazmadan önce mevcut sistemin gerçek durumu güvence altına alınır. Kod, mevcut fonksiyonlar, veri akışı ve testler incelenir; hâlihazırda çalışan, kısmen çalışan ve eksik olan işlevler birbirinden kesin biçimde ayrılır. Bir davranış yalnızca tasarım belgesinde yer aldığı için uygulanmış kabul edilmez kontrolü yapılır.

Her mevcut fonksiyon için şu üç soru yanıtlanır:

1. **Şimdi ne yapıyor?** Kodda gerçekten bulunan işlev ve ürettiği sonuç nedir arayüze yansıyormu, yansımalımı kullanıcıyada sorulur?
2. **Nerede yetersiz kalıyor?** İstenen davranışın hangi parçası eksik, kısmi veya testlerle doğrulanmamış?
3. **Mevcut fonksiyon nasıl geliştirilirse ihtiyaç karşılanır?** Hangi mevcut modülde, hangi hesaplama ve sonuçlar yeniden kullanılarak geliştirme yapılabilir?

Matris en az şu sütunları içerir:

| Fonksiyon/modül | Şu anki davranış ve kod kanıtı | Eksik veya yetersiz kalan yön | Mevcut yapı üzerinden geliştirme | Yeniden kullanılacak hesaplama/veri | Doğrulama testi | Durum |
|---|---|---|---|---|---|---|
| Ortak USDT parite evreni fan token hariç — ortak_piyasa.py:fetch_common_usdt_symbols, tek_motor_evreni.py:build_single_engine_universe | Binance ve BtcTurk Spot USDT çiftlerini eşleştirir; veri kaynağı/cache modu, parite sayıları ve uyarılar döndürülür. | Programın piyasa verisini Render geçidi üzerinden alabildiği güncel durumda doğrulanmıştır. Yerel cache geri dönüşü ve doğrudan borsa uç noktalarının alternatif davranışı bu çalışma sırasında ayrıca doğrulanmadı. | Mevcut ortak evren ve cache akışı korunur; yeni bir paralel evren hesabı yazılmaz. | pairs, evren modu, kaynak zaman damgası ve mevcut eşleştirme sonuçları. | Canlı ve cache modu, boş/uyumsuz evren, aktif olmayan pariteler ve USDT eşleşmesi için test. | Uygulanmış; çalıştırılmadı |
| Mum akışı, veri güncelliği ve 8 zaman dilimi — binance_erken_firsat_radari.py:TIMEFRAMES, BinanceRadar; radar_core.py:valid_bars | Motor 5m, 15m, 30m, 1h, 4h, 1d, 1w ve 1M zaman dilimlerini tanımlar; kapanmış ve zaman hizalı mumları, akış tazeliğini ve eksik/kesintili geçmişi kontrol eden yapılar içerir. | Render üzerinden piyasa verisinin programa ulaşması güncel durumda doğrulanmıştır; ancak sekiz zaman diliminin her birinde boşluk onarımı, zaman hizası ve eski veri davranışı ayrıca sınanmış değildir. | Mevcut WebSocket/REST, arşiv ve geçerlilik kontrolleri üzerinde ilerlenir; ikinci bir mum/veri katmanı açılmaz. | Mevcut mum arşivi, valid_bars, zaman dilimi sabitleri ve akış yaşları. | Her zaman dilimi için kapanmış/açık mum, zaman boşluğu, eski akış, onarım ve veri yok senaryoları. | Uygulanmış; çalıştırılmadı |
| Göstergeler ve A/B/C aşama değerlendirmesi — radar_core.py:_indicator_snapshot, assess_timeframe, evaluate_binance_candidate | EMA, MACD, RSI, ADX, DMI, ATR ve hacim katılımı hesaplanır; zaman dilimi metrikleri ve A/B/C kanıtları aday değerlendirmesine aktarılır. | Hesaplamaların tarihsel veri üzerinde doğruluğu ve farklı piyasa koşullarındaki yanlış sinyalleri bu incelemede ölçülmedi. | Var olan metrikler ile kanıt grupları ortak karar yapısında yeniden kullanılır; aynı göstergeler yeniden hesaplanmaz. | timeframes[*].metrics, mevcut gösterge serileri, evidence_groups, findings, missing_checks. | Bilinen örnek mum serileriyle gösterge referans testleri; eksik/kesintili ve yetersiz geçmiş kontrolleri; aşama regresyonu. | Uygulanmış; çalıştırılmadı |
| Pivot, destek/direnç, kanal ve Fibonacci — _confirmed_pivot_points, _support_resistance_zones, _confirmed_channel, _fibonacci_swing | Kapanmış mumlardan teyitli pivotlar, kümelenmiş destek/direnç bölgeleri ve teyitli kanal üretir; Fibonacci düzeltme ve uzatma seviyelerini hesaplar. Bu çıktılar risk planında ve fırsat puanlamasında kullanılır. | Sahte/erken pivot, kanal yokluğu, seviye kümelenmesi ve haftalık/aylık Fibonacci sonuçlarının gerçek tarihsel örneklerde doğruluğu ölçülmedi. | Hedef/puanlama iyileştirmesi aynı fonksiyonların çıktılarıyla yapılır; ikinci bir destek/direnç veya Fibonacci motoru yazılmaz. | support_resistance_zones, confirmed_channel, fibonacci, ATR ve teyitli pivotlar. | Elle doğrulanmış fiyat yapılarına sahip örnekler; seviye kaybı, kanal dışı kapanış, eksik pivot ve haftalık/aylık swing senaryoları. | Uygulanmış; çalıştırılmadı |
| BTC piyasa bağlamı ve güçlü fırsat kapısı — score_btc_market_context, _apply_btc_context_freshness, assess_btc_strong_opportunity_gate | BTC 1h/4h yönünü, güçlü destek/direnç ve kanal durumunu, göreli oynaklığı hesaplar. Eski/eksik veri, kritik destek/kanal kaybı veya aşırı oynaklık güçlü fırsat/alarm kapısını engelleyebilir. | BTC bağlamının canlı akıştaki davranışı ve tüm kapı kombinasyonları çalıştırılarak test edilmedi. Mevcut bağlam esas olarak 1h/4h ile sınırlıdır. | Mevcut BTC puanı, uyarıları ve kapısı ortak aday kararında korunur; eksik veri olumlu BTC puanı sayılmaz. | btc_market_context, data_completeness, risk_warnings, relative_volatility_ratio ve akış tazeliği. | Taze/eski BTC akışı, eksik 1h/4h mumları, kritik seviye kaybı ve oynaklık oranı eşikleri için kapı testleri. | Uygulanmış; çalıştırılmadı |
| BTC'ye göre göreceli güç ve korelasyon — _relative_strength_and_correlation, btc_correlation_risk_adjustment, score_opportunity | Eş zamanlı kapanmış mumlardan coin getirisi ile BTC getirisi arasındaki fark ve Pearson korelasyonu hesaplanır. Göreceli güç puana katkı verir; korelasyon 1h/4h ölçümleri yeterli örnek içeriyorsa ve BTC bağlamı zayıf/riskliyse ek puan düzeltmesi olarak kullanılır. | Eşiklerin tarihsel başarı üzerindeki etkisi ve korelasyon cezasının farklı rejimlerdeki davranışı geçmiş verilerde ölçülmedi. | Mevcut kural: tam BTC bağlamında risk varken ortalama korelasyon ≥0,80 ise -6, ≥0,60 ise -3 puan uygulanır. Sağlıklı BTC bağlamında, eski/eksik veride veya eşik altındaki korelasyonda ceza yoktur; negatif korelasyon otomatik güvenli/olumlu sayılmaz. | relative_strength_vs_btc_pct_points, btc_return_correlation, btc_correlation_assessment, BTC tazelik ve piyasa bağlamı. | ≥0,60 ve ≥0,80 eşik sınırları; veri sayısı eksikliği; eski BTC verisi; zayıf/sağlıklı BTC bağlamı; puan toplamı ve aday sırası için otomatik testler ve daha sonra geçmiş veri testi. | Kodda uygulandı; test bekliyor |
| Aday puanı ve sıralama — score_opportunity, candidate_priority_key, _candidate_rows | 0–100 fırsat puanı; fiyat yapısı, hacim, momentum, trend, çoklu zaman dilimi yapısı, göreceli güç, BTC bağlamı, likidite ve koşullu korelasyon risk düzeltmesi birleştirilir. Adaylar puan/karar ve diğer öncelik ölçütleriyle sıralanır. | Puan ağırlıklarının tarihsel başarıya etkisi, erken yakalama oranı ve yanlış pozitifler bu turda ölçülmedi. | Mevcut puan bileşenleri ve sıralama korunur; davranış değişikliği gerekçeli kural ve geçmiş veri doğrulamasıyla ayarlanır. | score_components, opportunity_score, final_decision, btc_correlation_assessment, evidence_groups, mevcut sıralama anahtarı. | Kararlı sıralama; puan bileşenleri ve eşik sınır testleri; geçmiş veriyle yanlış pozitif/kaçırılan yükseliş analizi. | Kodda uygulandı; test bekliyor |
| Koşullu giriş, stop, teknik hedef ve R projeksiyonları — build_trade_plan | Giriş bölgesi kırılım/ATR ile, stop destek ve ATR ile oluşturulur. Teknik hedef adayları teyitli direnç, kanal üstü ve Fibonacci uzatmalarından seçilir; 1R/2R/3R matematiksel projeksiyonları ayrıca verilir. Geçersizleşme ve fiyatı kovalamama durumu kaydedilir. | Hesaplanan seviyelerin piyasa verisi üzerinde doğruluğu, hedef sırası ve sınır koşulları çalıştırılarak doğrulanmadı. | Aynı plan fonksiyonunun mevcut fiyat yapısı ve seviye girdileri geliştirilir; teknik hedef ile R projeksiyonu ayrı tutulur. | risk_plan, seçilen zaman dilimi metrikleri, ATR, destek/direnç, kanal, Fibonacci. | Giriş bandı/stop/target geometrisi; hedef yokluğu; fiyat giriş bölgesinin altında/içinde/üstünde; stop invalidasyonu; teknik hedefin R projeksiyonlarından ayrılması. | Uygulanmış; çalıştırılmadı |
| Güçlü fırsat ve risk/getiri kapısı — score_opportunity | Güçlü fırsat için en az 80/100 puan, B/C aşaması, güncel veri, uygunluk, likidite, kovalamama, geçerli teknik plan, BTC kapısı ve en yakın teknik hedefte brüt risk/getiri ≥1,5 koşulları aranır. | Kapıların birleşik canlı davranışı çalıştırılmadı. Geçerli kod akışı komisyon/kayma sonrası net getiri hesabı yapmaz. | Mevcut brüt kural korunur. Masraf sonrası net ölçüm ancak varsayımlar (işlem ücreti, spread/kayma kapsamı ve yönü) kararlaştırılıp onaylandıktan sonra ele alınır. | risk_plan.targets[0].risk_multiple, strong_opportunity_qualified, likidite sonucu, veri güncelliği ve BTC kapısı. | 1,5 eşiğinin hemen altı/eşiti/üstü; kapıların tek tek ve birlikte başarısız/başarılı durumları; masrafsız brüt hesap ayrımı. | Brüt kapı uygulanmış; net maliyet hesabı eksik; çalıştırılmadı |
| Sinyal takibi ve tarihsel sonuç — sinyal_kaydi.py:SignalTracker | B/C adayında canlı veri ve teknik hedef varsa plan seviyeleri dondurulur; sonraki fiyat gözlemlerinde giriş, hedef, stop ve 24 saatlik gözlem penceresi takip edilir. Sonuçlar brüt fiyat hareketine dayanır. | Bu, tam bir geçmiş piyasa taraması/backtest değildir; geçmişte yükselmiş ama listeye girmemiş coinleri veya kaçırılmış erken yükselişleri sistematik ölçtüğü doğrulanmadı. Mum içi hedef/stop sırası ve ücretler de ölçülmez. | Var olan sinyal geçmişi ve özet fonksiyonları üzerinden kapsam belirlenir; ayrı bir arka arkaya hesaplama motoru eklenmez. | Dondurulmuş risk_plan, örneklenen fiyatlar, karar anı kayıtları ve historical_summary. | Giriş/stop/hedef/24 saat sonuç senaryoları; örnekleme sınırlarının açıklanması; geçmiş tarama/backtest tasarımı onaylanırsa kaçırılan fırsat ve yanlış sinyal ölçümleri. | Kısmi; çalıştırılmadı |
| Panel aday listesi ve seçilen coin özeti — tek_motor_paneli.pyw:_build_ui, _selection_changed, _render_state | Aday listesinde coin, keşif yolu, A/B/C, fiyat, BTC'ye göre 1h getiri farkı, BTC 1h korelasyonu, zaman dilimi, veri güncelliği ve karar sınıfı bulunur. Üstte BTC bağlam özeti; seçilen coin bölümünde karar gerekçesi, göreceli güç/korelasyon etkisi, destek/direnç, giriş-stop-hedef ve eksik teyitlerin özeti gösterilir; ayrıntılar korunur. | Panelin gerçek Windows görünümünde okunabilirliği, alanların sığması ve canlı verilerle tutarlılığı henüz doğrulanmadı. | Mevcut motor JSON alanları ve risk planı yeniden kullanılır; paralel hesaplama katmanı eklenmez. | btc_market_context, relative_strength_vs_btc_pct_points, btc_return_correlation, btc_correlation_assessment, findings, missing_checks, risk_plan. | JSON-panel eşleşmesi, eski/eksik veri, coin seçimi, karar gerekçesi ve risk seviyeleri için regresyon; Windows ölçek/taşma kontrolü. | Kodda uygulandı; Windows testi bekliyor |
| Panel ölçüleri, tema, renkler ve kontroller — tek_motor_paneli.pyw:_build_ui | Başlat/durdur, liste güncelleme, rapor/devir ZIP, alarm, ses seviyesi/ses denemesi, aday seçimi ve seviye takibi korunur. Pencere ekran boyutuna göre ortalanır; aydınlık ayarı gri/açık aralığı düzenler. | Gerçek 1920×1080 ve %125 Windows ortamında yarım-ekran hedefi/azami yaklaşık %80 genişlik ve ekran yüksekliğinden en az %7 kısa olma kuralı henüz görsel olarak doğrulanmadı. | Mevcut Tkinter paneli ve kontrolleri korunur; koyu tema kullanılmaz, açık gri zemin ve durum renkleri korunur. | Mevcut Tkinter paneli, aday durumu, risk planı, alarm ve seviye takibi. | Windows'ta %125 ölçek, pencere boyut sınırları, kontrol etkileşimleri, renk/etiket açıklığı ve taşma regresyonu. | Kodda uygulandı; Windows testi bekliyor |
| Rapor, devir ZIP'i ve depolama bakımı — tek_motor_paneli.pyw:create_report/create_handoff_zip, veri_yasam_dongusu.py, binance_mum_arsivi.py | Rapor ve devir arşivi oluşturma, ZIP bütünlük/SHA-256 kontrolü, mum arşivi ve geçmiş kayıtların saklanması için kod bulunur. | Güncel Windows ortamında uçtan uca ZIP, yeniden açılma, arşiv ve uzun çalışma senaryoları bu turda çalıştırılarak test edilmedi. | Mevcut rapor/arsiv işlevleri korunur; yeni raporlama mekanizması ancak net bir boşluk varsa tasarlanır. | Mevcut JSON/Markdown raporu, tanı çıktısı, SHA-256 manifesti, mum arşivi ve sinyal geçmişi. | ZIP açma ve SHA-256 doğrulaması; bozuk/eksik dosya; arşiv sınırları; devir paketinde gerekli BtcTurk evreni ve raporların bulunması. | Uygulanmış; çalıştırılmadı |

**İnceleme sınırı ve güncel çalışma durumu:** Bu matris `main` dalındaki kaynak kodun statik incelemesini ve bazı geliştirme/test işlerini listeler. Eski bir Actions çalıştırmasının başarısız olması veya testlerin çalışmış olması, bugünkü uçtan uca çalışmanın tek başına kanıtı değildir. 27 Ekim 2026 itibarıyla kullanıcı tarafından doğrulanan güncel durum şudur: program piyasa verisini Render geçidi üzerinden alabiliyor; analiz/günlük/sorun giderme raporları buluta gönderilebiliyor ve bulut okuma uçlarından ChatGPT tarafından okunabiliyor. Bu işleyişle çelişen eski “veri bağlantısı doğrulanmadı” veya “rapor akışı doğrulanmadı” kayıtları güncel durum olarak kullanılmamalıdır. Tarihsel backtest ve Windows masaüstünde görsel/etkileşim testi ise ayrı açık işler olarak kalır.

Bu matris, Sürüm 00'ın başlangıç davranışını, doğrulanmış eksiklerini ve sonraki geliştirme/test işlerini birbirinden ayıran temel kayıt olarak kullanılır.

### 8. Hesaplamaların korunması ve karar gereksinimleri

Program sekiz zaman dilimindeki mumları ve mevcut teknik göstergeleri zaten değerlendirir. EMA (üstel hareketli ortalama), MACD (hareketli ortalamaların yakınsama-ıraksama göstergesi), RSI (Göreceli Güç Endeksi), ADX (ortalama yönsel endeks), DMI (yönsel hareket göstergeleri) ve ATR (ortalama gerçek aralık) hesapları gereksiz yere kopyalanmaz. Destek/direnç ve kırılım değerlendirmeleri, mevcut hesaplamalar ve sonuçlar üzerinden geliştirilir.

Ortak karar sistemi, mevcut teknik çıktıları birbirinden kopuk ham değerler olarak sunmak yerine şu bağlamlarla birlikte değerlendirir:

- BTC'nin ana yönü, piyasa rejimi ve genel risk koşulları.
- Coinin kendi teknik aşaması, fiyat yapısı ve kırılım/geri test durumu.
- Coinin BTC'ye göre performansı ve BTC ile korelasyonu (birlikte hareket ilişkisi).
- Yakın ve önemli destek/direnç bölgeleri, yatay kanal sınırları ve olası kırılım veya seviye kaybı.
- Giriş bölgesi, zarar durdurma seviyesi, teknik hedefe kalan getiri ve stop seviyesine kadar olan risk.
- Veri güncelliği, eksik veri, eksik teyit ve işlemin geçersizleşeceği koşullar.

Program her aday için en az şu sorulara cevap üretebilmelidir:

- Önündeki ilk önemli direnç veya olası kâr alma bölgesi nerede?
- Olası girişten bu bölgeye kadar ne kadar getiri alanı bulunuyor?
- Girişten zarar durdurma seviyesine kadar fiyat bazında ve yüzde olarak ne kadar risk var?
- Hedefe kalan alan risk karşısında yeterli mi; hedef çok yakınsa fırsat düşük kaliteli olarak mı sınıflandırılmalı, yoksa değerlendirme dışı mı bırakılmalı?
- Eksik veri, geçersizleşme koşulu veya sonucu zayıflatan başka bir engel var mı?

Yakın direnç, teknik bulgulara dayalı olası kâr alma bölgesidir; kesin fiyat tahmini veya otomatik satış emri değildir. Teknik hedefler, gerçek destek/direnç ve fiyat yapısıyla gerekçelendirilir. Sadece matematiksel risk katları kullanılarak teknik hedef belirlenmiş gibi gösterilmez diğer fonksiyonlarada bakılır.

Mevcut README'de kayıtlı başlangıç davranışı korunarak dikkate alınır: güçlü fırsat kapısı, en yakın teknik hedef için brüt teknik risk/getiri oranının en az 1,5 olmasını ister; spread ayrı likidite filtresinde değerlendirilir. Bu mevcut kural sessizce değiştirilmez. Eşiğin veya düşük kaliteli fırsatları dışlama koşullarının değiştirilmesi gerekiyorsa kod incelemesi, gerekçeli tasarım ve geçmiş verilerle doğrulama gerekir. Mevcut `ayarlar.json` komisyon/kayma ayarlarını içermez ve mevcut sürüm bu maliyetleri hesaplamaz. Masraflar sonrası net risk/getiri gereksinimi, maliyet varsayımları açıkça tanımlanıp uygulanıp test edilene kadar mevcut özellikmiş gibi gösterilmez.

### 9. Panel yerleşimi ve gösterilecek bilgiler

Panel bütün analizleri aynı anda ekrana yığmak yerine karar için gerekli bilgileri öne çıkarır; ayrıntılar kaybolmaz, gerektiğinde incelenebilir. Mevcut alanlar ve davranışlar, aşağıdaki yeni yerleşimle uyumlu biçimde korunur.

#### Kullanıcının kesinleştirdiği görünüm ve mevcut kontroller

- Hedef çalışma ortamı Windows, ekran çözünürlüğü 1920×1080 ve Windows ölçeklendirmesi %125'tir. Panel başlangıçta ekran genişliğinin yaklaşık yarısına sığacak şekilde tasarlanır; okunabilirlik gerektirirse genişlik en fazla ekranın yaklaşık %80'ine çıkarılabilir. Pencere yüksekliği ekran yüksekliğinden en az %10 daha kısa olmalıdır.
- Koyu tema temel alınır. Açık/normal görünümde kırmızı, sarı, mavi, yeşil, açık mor, lila, turkuaz ve lacivert gibi durum renkleri kullanılabilir; yazıların arka planı siyah tonlarında, ayırıcı çizgiler beyaz olur. Renk tek başına karar gerekçesi sayılmazsada; renkli durumun anlaşılır metinsel karşılığı bulunur.
- Ses seviyesi kontrolüne benzer bir parlaklık/aydınlık ayarı eklenmesi planlanır. Mümkünse ses kontrollerinin yakınında yer alır. Bu kontrol  mevcut özelliklerde var; kodlamadan önce nihai yerleşim içinde gösterimi netleştirilir.
- Mevcut yararlı kontroller korunur veya aynı işlev açık kalacak şekilde uyarlanır: parite listesini güncelleme, rapor devir ZIP'i oluşturma, Başlat, Durdur, Alarm Açık/Kapalı, ses seviyesi, sesi testi ve seçilen coin için giriş/hedef seviyelerini izleme. Kontrol etiketleri tasarım onayında tutarlılaştırılır.
- Adayların mevcut A/B/C aşamaları ve anlamları korunur: A hazırlık, B yapı/kırılım, C devamlılık. Kapalı mumda katılım, geri test ve devamlılık teyitleri kaybolmaz. Eski/eksik veri için mavi renk yazı uyarı korunur.
- Karar alanları mevcut işlevler üzerinden düzenlenir: **Adaylar** listesi; **Giriş Kontrolü** içinde senaryo zaman dilimi, kırılım seviyesi, zarar durdurma ve olası giriş; **Seçilen Coin** içinde kırılım seviyesi, zarar durdurma ve teknik hedefler. Bunlar ham hesap çıktıları yığınına çevrilmez; hızlı karar bilgisi öne çıkarılır, ayrıntılar erişilebilir kalır sunulmayabilir.
- Yerleşim ve ölçüler için tasarım kararı kod değişikliğinden önce gözden geçirilir. Bu maddeler arayüzün gereksinimidir; mevcut panelin bunları uyguladığı veya ekran üzerinde sınandığı anlamına gelmez.

#### A. Üst bölüm — BTC ve genel piyasa

Mevcut motor durumu, bağlantı bilgileri, alarmlar ve parite evreni bilgileri korunur. Mevcut **“Piyasa ve parite ”** alanı kaldırılmaz; BTC piyasa bağlamıyla genişletilir. Burada kısa ve anlaşılır biçimde şunlar gösterilir vurgulanması gereken kelime rakamlar büyük harf ve farklı renklerde anlam bütünlüğünde olur:

- BTC ana yönü ve genel piyasa risk durumu.
- Güçlü destek ve direnç bölgeleri.
- Yatay kanal varsa alt ve üst sınırları.
- Önemli kırılım veya önemli seviye kaybı.
- Verinin güncel olup olmadığı ve varsa veri eksikliği.

BTC özeti nedeniyle mevcut parite evreninin kapsamı veya durumu kaybolmaz.

#### B. Orta bölüm — öncelikli adaylar

Mevcut aday tablosu korunur. A/B/C aşamaları, fiyat, veri durumu, zaman dilimi ve keşif yolu bilgileri kaybolmaz. Tabloyu gereksiz kalabalıklaştırmadan coin için kısa bir **BTC'ye göre durum** bilgisi eklenir; adayın BTC'den daha güçlü veya daha zayıf performans gösterip göstermediği ilk bakışta anlaşılabilir.vurgulanması gereken kelime rakamlar büyük harf ve farklı renklerde anlam bütünlüğünde olur:

Ayrıntılı korelasyon değerleri aday tablosunu doldurmak yerine seçilen coin bölümünde gösterilir. Yeni hesaplamaların gösterimi mevcut aday sıralamasını veya aşama sınıflandırmasını sessizce değiştirmez. Sıralama veya sınıflandırma mantığında yapılacak değişiklik ayrı olarak gerekçelendirilip test edilir.

#### C. Seçilen coin — hızlı karar özeti ve teknik ayrıntılar

Mevcut **“Seçilen adayın özeti”** alanı, hızlı karar özeti ile ayrıntılı analiz olmak üzere iki bölüme ayrılır.

**Sol bölüm — hızlı karar özeti:**

- Coinin mevcut teknik aşaması.
- BTC ile ilişkisi, BTC'ye göre performansı ve BTC koşullarının aday üzerindeki etkisi.
- Ana fiyat yapısı: yükseliş, düşüş veya yatay kanal.
- En önemli yakın destek ve direnç bölgeleri.
- Fırsatın önündeki temel engel veya eksik teyit.
- Açıklanabilir genel durum: “izlemeye değer”, “teyit bekleniyor”, “risk yüksek” veya “veri yetersiz” gibi sonuçlar.vurgulanması gereken kelime rakamlar büyük harf ve farklı renklerde anlam bütünlüğünde olur.

**Sağ bölüm — mevcut ayrıntılı analiz:**

- EMA, MACD, RSI, ADX, DMI ve ATR gibi mevcut teknik bulgular.
- Sekiz zaman diliminin değerlendirmeleri.
- A/B/C aşamasının gerekçeleri.
- Mevcut analiz ve kontrollerin sonuçları, eksik kontroller ve veri güncelliği.

Hızlı özet, ayrıntılı analizin yerine geçmez; mevcut teknik bulguları anlaşılır bir karar görünümünde birleştirir. Renkler ve etiketler sonucu özetleyebilir, ancak bir rengin kendisi karar gerekçesi olamaz. Her önemli uyarının anlaşılır bir nedeni bulunur. Gösterilen durumlar otomatik alım-satım kararı değil öngörü içindir.vurgulanması gereken kelime rakamlar büyük harf ve farklı renklerde anlam bütünlüğünde olur.

#### D. Alt bölüm — giriş, hedef ve risk kontrolü

Mevcut giriş kontrolü alanı korunur. Bilgiler birbirinden açıkça ayrılır:

| Gösterim | İçerik |
|---|---|
| Giriş | Mevcut koşullu giriş bölgesi ve kırılım seviyesi |
| Zarar durdurma | Stop seviyesi ve girişe göre fiyat/yüzde riski |
| Teknik hedef | Gerçek direnç bölgesine ve fiyat yapısına dayanan olası hedef/kâr alma bölgesi |
| Net risk/getiri | Hedefe kalan getiri ile stop riski; masraflar sonrası karşılaştırma yalnızca masraf varsayımları hesaplanıp doğrulandığında gösterilir |
| Matematiksel hedefler | Mevcut 1R/2R/3R risk katı projeksiyonları |
| Son durum | Giriş koşulu, geçersizleşme şartı, eksik veri ve teyit uyarıları |

Gerçek teknik hedef ile matematiksel hedef aynı şeymiş gibi gösterilmez. Teknik hedefe ulaşmak için kalan getiri yetersizse bu, hızlı özette açıkça belirtilir ve fırsat kalitesi kuralları uygulanır. Teknik hedef otomatik emir değildir.vurgulanması gereken kelime rakamlar büyük harf ve farklı renklerde anlam bütünlüğünde olur

### 10. Aşamalı uygulama, doğrulama ve sürüm geçişi

Bu yol haritası, üzerinde çalışılıp doğrulanacak **tasarım planıdır**. Listelenen bir özellik, kodda uygulanıp test edilmeden tamamlanmış olarak raporlanmaz. Her aşamanın sonucu doğrulanmadan sonraki aşamada o sonuç gerçekleşmiş kabul edilmez.

1. **Mevcut sistemi güvenceye alma:** Kod, fonksiyonlar ve testler incelenir; mevcut davranışlar kayıt altına alınır ve mevcut–eksik–geliştirme–test matrisi hazırlanır.
2. **Hesaplama altyapısını geliştirme:** Ortak veri kullanımının, BTC değerlendirmesinin ve teknik yapı hesaplarının mevcut modüllere nasıl bağlanacağı belirlenir.
3. **Hedef ve risk katmanını tamamlama:** Gerçek direnç hedefleri, masraf varsayımları ve net risk/getiri koşulları tanımlanır. Mevcut davranış ile planlanan geliştirme ayrı tutulur.
4. **Ortak sonuç yapısını kurma:** BTC raporu ve coin bazındaki sonuçlar tek, tutarlı bir veri akışında birleştirilir; mevcut hesaplamaların yinelenmesi önlenir.
5. **Panel yerleşimini uygulama:** Önce üst bölümde genel BTC görünümü, ardından aday tablosu ve seçilen coin özeti/ayrıntıları, son olarak alt giriş-hedef-risk alanı düzenlenir.
6. **Doğrulama:** Hesaplamalar için birim testleri, önceki işlevlerin bozulmadığını kontrol etmek için regresyon testleri ve geçmiş piyasa verileriyle kontroller yapılır.
7. **Paket ve son kontrol:** Hesaplamalar, panel davranışları, mevcut işlevler ve raporlama birlikte test edilir. Raporlama, alarm davranışı, veri güncelliği ve panel sonuçlarının tutarlılığı; paket bütünlüğü ve sürüm kayıtları doğrulanır.

#### Son doğrulama ve sürüm 00 → sürüm 1 geçişi

- Son doğrulama aşamasında yeni özellikler tek başına değil, mevcut sistemin bütünüyle birlikte değerlendirilir.
- Test sonucu, kod ve sürüm kayıtlarıyla kanıtlanmayan hiçbir iş tamamlandı diye işaretlenmez. Başarısız testler çözülmeden sürüm hazır kabul edilmez.
- Paket bütünlüğü ve sürüm kayıtları doğrulanmadan dağıtıma hazır paket ilan edilmez.
- Sürüm 00, başlangıç tabanı olarak main dalında tutulur. Bu başlangıç hazırlığındaki README tutarlılık düzeltmesi ve APP_VERSION = "00" etiketi, yalnızca başlangıç noktasını tanımlar; tasarlanan yeni özelliklerin uygulanması veya test edilmesi değildir.
- Sürüm 00 başlangıç tabanı `main` üzerinde korunur. Sürüm 1 için bir dal ancak kullanıcı önceden açıkça onay verdikten sonra açılır ve adı `1.surum-readme-gereksinimler` olur. Bu dalda yapılacak değişiklikler, gerekli hesaplama, regresyon, geçmiş veri, panel, raporlama ve paket kontrolleri tamamlanmadan ve kullanıcı onayı alınmadan `main` dalına aktarılmaz. Dal açma onayı, kodlama veya birleştirme onayı sayılmaz.
- **Yeni sürüm 1**, yalnızca gerekli kontroller tamamlandıktan ve sonuçları doğrulandıktan sonra hazırlanır. README'ye tasarım planının kaydedilmesi veya sürüm etiketinin değiştirilmesi, özelliklerin tamamlandığı ya da ZIP paketinin hazır olduğu anlamına gelmez.

Bu gereksinimlerin README'ye kaydedilmesi tek başına kod değişikliği değildir. İlk uygulama işi, mevcut kodun kanıtlarla incelenmesi ve fonksiyon bazında matrisin doldurulmasıdır; sonuçlara göre her eksikliğin hangi mevcut modüle bağlanacağı, hangi hesaplamayı yeniden kullanacağı ve nasıl doğrulanacağı belirlenecektir.

## Sürüm 00 — son uygulama kaydı (25 Ekim 2026)

### Bu düzeltme grubunda uygulanan kod değişiklikleri

- Sürüm etiketi `APP_VERSION = "00"` olarak korunmuştur. Programın tek motorlu mimarisi ve mevcut hesaplamaları baştan yazılmamıştır.
- `radar_core.py` içinde BTC korelasyonu, tek başına yön sinyali veya pozitif puan sayılmaz. Yalnızca eşzamanlı kapanmış mumlardan yeterli 1h/4h korelasyonu varsa, BTC bağlamı tam ve riskliyse aday puanına risk düzeltmesi eklenir: ortalama korelasyon ≥0,80 için -6 puan; ≥0,60 için -3 puan. Eski/eksik BTC bağlamında, ölçüm örnek sayısı yetersizse, BTC bağlamı sağlıklıysa veya ortalama korelasyon 0,60'ın altındaysa ceza uygulanmaz. Negatif korelasyon ayrıca olumlu puan getirmez.
- `tek_motor_paneli.pyw` içinde BTC 1h/4h piyasa bağlamı özeti, aday listesinde BTC'ye göre 1h getiri farkı ve BTC 1h korelasyonu; seçilen coin alanında karar gerekçesi, korelasyon düzeltmesi, yakın destek/direnç, koşullu giriş, zarar durdurma, ilk teknik hedef ve eksik teyitlerin özeti eklenmiştir. Ayrıntılı mevcut metrikler, risk planı ve kontrol alanları korunmuştur.
- Pencere boyutu ekran ölçülerine göre hesaplanıp ortalanır. Ses kontrollerine yakın, ayarları kaydedilen açık-gri aralıkta aydınlık kontrolü eklenmiştir.
- Durum raporunun aday tablosuna BTC göreceli güç/korelasyon sütunları eklenmiştir. Motorun `important_note` açıklaması korelasyon düzeltmesini yansıtacak şekilde güncellenmiştir.
- Aday tablosunda karar sınıflarını yeşil/kırmızı/sarı/mavi/lila/turkuaz ve A/B/C aşamalarını ayırt eden renk etiketleri eklenmiştir; eski/eksik veri gri uyarı olarak kalır.
- `tests/test_btc_correlation_adjustment.py` içine eşik, riskli/sağlıklı BTC, eski veri, yetersiz örnek, negatif korelasyon ve puan bileşeni için otomatik testler eklendi. `.github/workflows/validate-and-package.yml`, kaynak derleme ve otomatik testler için `ubuntu-slim` kullanır; ayrıca ayar JSON'ları doğrulanır. Bu 25 Ekim tarihli kayıtta o dönemki iş akışının her `main` gönderiminde paket oluşturduğu belirtiliyordu. 27 Ekim 2026 tarihli politika düzeltmesiyle olağan `main` gönderimleri yalnızca doğrulama yapar. Açıkça istenen son paketlemede program ZIP'i, SHA-256 doğrulama dosyası ve Actions artefaktı hazırlanır. Bunların tamamını indirmen gerekmez; program için ZIP yeterlidir. Bu kaynak doğrulaması, Windows masaüstü arayüzünün görsel veya canlı çalıştırma testi değildir.
- Önceki iş akışı sürümünde ZIP ve SHA-256 dosyası her `main` push çalıştırmasında üretiliyordu. 27 Ekim 2026 itibarıyla olağan gönderimler yalnızca test ve doğrulama yapar; kullanıcı son paketlemeyi istediğinde program ZIP'i ve teknik doğrulama çıktıları oluşturulur. Programı kullanmak için yalnızca ZIP'i indirmen yeterlidir.

### Doğrulama durumu — dikkat

- **Tarihsel CI notu:** Önceki bazı Actions denemelerinde çalıştırıcı atanmamış ve komut adımları başlamamıştı. Bu, o denemelerin sonucunu açıklar; 27 Ekim 2026 itibarıyla güncel çalışma durumunu tanımlamaz. Programın Render üzerinden veri alması ve raporların buluttan okunabilmesi sonraki gerçek kullanımda doğrulandı. Eski Python/JavaScript test sonuçları güncel işlevin yerine geçen bir kanıt olarak kullanılmamalı; gerektiğinde yalnızca kod değişiklikleri için regresyon kontrolü sayılmalıdır. [Sürüm 00 doğrulama geçmişi](https://github.com/erdaly1947-max/matrix/actions/workflows/validate-and-package.yml?query=branch%3Amain).
- Olağan `main` gönderimleri ZIP'i veya kalıcı GitHub Release indirme dosyasını güncellemez. Program ZIP'i yalnızca kullanıcı tarafından başlatılan son paketleme çalıştırmasında güncellenir. Render üzerinden programın piyasa verisi alması güncel çalışma durumunda doğrulanmıştır. Tarihsel backtest ve gerçek Windows masaüstünde panel taşma/etkileşim kontrolü ayrı açık işlerdir.
- Komisyon ve kayma sonrası net getiri hesabı eklenmedi ve bilerek eklenmeyecektir. Teknik risk/getiri brüt kalır; emir gönderimi veya otomatik alım-satım bulunmaz.
- Programın dağıtım ZIP'i kalıcı bağlantıdan indirilebilir: https://github.com/erdaly1947-max/matrix/releases/download/surum-00/Firsat-Kontrol-Paneli-Surum-00.zip . Programı kullanmak için yalnızca bu dosyayı indirmen yeterlidir. Olağan `main` gönderimlerinde ZIP yenilenmez; yalnızca açıkça başlatılan ve başarılı son paketleme işleminde güncellenir.
- **25 Ekim 2026 tarihli ağ/TLS tanısı (tarihsel):** O gün kullanıcının ev internetinden doğrudan Binance/BtcTurk REST adreslerine erişimde `TLS WRONG_VERSION_NUMBER` ve Windows `curl.exe` için `SEC_E_INVALID_TOKEN` görüldü. O bulgu doğrudan ağ yolunu tanımlıyordu. Daha sonra piyasa verisi Render geçidi üzerinden alınacak şekilde kuruldu; 27 Ekim 2026 güncel durumunda programın Render üzerinden veri aldığı kullanıcı tarafından doğrulandı. Dolayısıyla eski doğrudan TLS hatası, mevcut Render veri akışının başarısız olduğu anlamına gelmez. CI/Python/JavaScript test kayıtları bu güncel çalışma durumunun yerine geçmez; yalnızca tarihsel teknik kayıttır.
- Kullanıcının yerel canlı test sonucu gelene kadar Sürüm 1 çalışmasına geçilmez. Dal açılması gerekirse kullanıcıdan önceden açık onay alınır; Sürüm 1 dalı adı ancak onaydan sonra `1.surum-readme-gereksinimler` olur.



## Ağ bağımsız piyasa verisi geçidi — kalıcı teknik kayıt( bu kısım kullanıcıya danışılacak sorunlar çözüldü)

### Sorunun kaynağı ve tanılama bulgusu

- 25 Ekim 2026 tarihli Windows tanılamasında, bilgisayar evdeki TurkTelekom_ZWR3J ağına bağlıyken data-api.binance.vision:443 için TLS ClientHello sonrasında TLS yanıtı yerine düz HTTP 307 Temporary Redirect alındı. Yönlendirme guvenliinternet.turktelekom.com.tr alan adına gidiyordu ve yanıtta Via başlığı vardı. Bu, söz konusu ağ bağlantısında Türk Telekom Güvenli İnternet filtre/yönlendirmesiyle uyumludur.
- Aynı ev Wi-Fi bağlantısında telefondan borsa siteleri açılırken, bilgisayar telefonun mobil erişim noktasına bağlandığında programın ve tarayıcının çalışması; sorunun masaüstü programının temel veri işleme kodundan ziyade bilgisayarın ev interneti üzerindeki HTTPS/TLS yolunda olduğunu gösteren karşılaştırmalı kanıttır.
- Windows ortam değişkenleri, Windows Internet Settings ve WinHTTP kontrollerinde yapılandırılmış proxy bulunmadı. Bu nedenle bu sorun için proxy kurulması veya proxy ayarlarının değiştirilmesi çözüm olarak kaydedilmemelidir.
- Doğrudan ağ yolundaki yönlendirme yerel program tarafından güvenli biçimde düzeltilemeyeceğinden, halka açık piyasa verisinin ayrı bir bulut sunucusundan alınması ve uygulamaya HTTPS/WebSocket üzerinden iletilmesi yaklaşımı seçildi. 

### Cloudflare Workers denemesi — sonuç ve korunacak bilgi( bu kısmı kullanıcıya danış)

- Ücretsiz Cloudflare Worker oluşturulup dağıtıldı. Worker sağlık uç noktası ve BtcTurk halka açık USDT ticker isteği çalıştı.
- Aynı Worker üzerinden Binance REST istekleri denendi; Cloudflare çıkışından yapılan istekler Binance tarafında HTTP 403/451 ile engellendi. Birden fazla resmî Binance API ana makinesini denemek de sorunu çözmedi. Bu nedenle Cloudflare Worker, Binance piyasa verisi için uygun aktif geçit olarak doğrulanmadı.
- Sonuç: Cloudflare denemesi boşa gitmiş bir kod değişikliği değildir; sorunun kaynağını ayıran ve hangi ücretsiz altyapının bu kullanımda çalışmadığını kanıtlayan bir deneydir. Cloudflare Worker kaynakları cloudflare_worker/ içinde tarihsel/teknik kayıt olarak tutulur; güncel masaüstü ZIP'i artık Cloudflare adresine bağımlı değildir.
- Cloudflare hesabındaki Worker'ı silmek gerekmez. Güncel uygulama için geçerli adres, ZIP'e yazılan market_data_relay.json dosyasındaki Render adresidir. Eski Cloudflare dağıtımını yeniden etkinleştirmek, Binance veri akışının çalıştığı anlamına gelmez.

### Aktif geçit — Render Frankfurt

- Aktif hizmet adı: firsat-kontrol-market-relay.
- Bölge ve plan: Frankfurt, Render Free Web Service.
- Genel adres: https://firsat-kontrol-market-relay.onrender.com
- Sağlık kontrolü: https://firsat-kontrol-market-relay.onrender.com/healthz
- Render yönetim ekranı: https://dashboard.render.com/web/srv-dbf3n80n74is73beeeog
- Kaynak kod: render_relay/server.js, render_relay/package.json, render_relay/test/server.test.js ve render_relay/smoke-check.mjs.
- Hizmet yalnızca izin listesine alınmış halka açık piyasa verisi uç noktalarını ve Binance genel mum WebSocket akışlarını iletir. Borsa hesabı girişi, API anahtarı, bakiye/pozisyon erişimi, emir oluşturma veya işlem yürütme özelliği yoktur. Rastgele URL'lere vekil isteği göndermeye izin verilmez.
- GitHub deposunun main dalına bağlı otomatik dağıtım açıktır. Yeni commit geldiğinde Render hizmeti kaynak koddan tekrar oluşturulup dağıtılır.

### Canlı bağlantı doğrulaması — 25 Ekim 2026

GitHub Actions çalıştırması [40216714717 — canlı Render piyasa verisi testi](https://github.com/erdaly1947-max/matrix/actions/runs/40216714717) aşağıdaki kontrolleri başarıyla tamamladı:

1. Render /healthz uç noktası HTTP 200 döndürdü.
2. Binance exchangeInfo yanıtı alındı; 3.736 sembol listelendi ve BTCUSDT etkin Spot paritesi doğrulandı.
3. Binance BTCUSDT 5 dakikalık mum uç noktasından mum verisi alındı.
4. BtcTurk halka açık USDT ticker yanıtı alındı.
5. Binance WebSocket bağlantı el sıkışması tamamlandı ve gerçek bir kline/mum mesajı alındı.
6. Python kaynak derleme, Python otomatik testleri, Cloudflare geçidi JavaScript testleri, Render geçidi testleri, canlı piyasa verisi kontrolleri, ZIP bütünlüğü, SHA-256 üretimi ve Release dosyalarının güncellenmesi başarılı oldu.

Bu sonuç, bulut sunucusunun ilgili uç noktalara test anında erişebildiğini kanıtlar; gelecekteki kesintisiz erişim garantisi değildir. Ücretsiz Render hizmeti 15 dakika boyunca gelen HTTP isteği veya açık WebSocket bağlantısından gelen mesaj almazsa uykuya geçebilir. Sonraki istek/bağlantı hizmeti uyandırır ve ilk yanıt gecikebilir. Bu ücretsiz plan sınırı nedeniyle program ilk bağlantıda bekleme veya yeniden bağlanma yaşayabilir. Güncel davranış için [Render ücretsiz hizmet sınırları](https://render.com/docs/free) incelenebilir.

### Program ZIP'ini indirme ve paketleme

- Güncel ve sabit indirme adresi: [Fırsat-Kontrol-Paneli-Surum-00.zip](https://github.com/erdaly1947-max/matrix/releases/download/surum-00/Firsat-Kontrol-Paneli-Surum-00.zip)
- Release sayfası: https://github.com/erdaly1947-max/matrix/releases/tag/surum-00
- Otomatik doğrulama geçmişi: https://github.com/erdaly1947-max/matrix/actions/workflows/validate-and-package.yml?query=branch%3Amain

Her `main` gönderiminde GitHub Actions Python 3.14.8 ortamında kaynak derlemesini ve otomatik testleri, Node.js 22 ortamında geçit testlerini ve canlı Render/Binance/BtcTurk REST + WebSocket kontrollerini çalıştırır. Yalnızca kullanıcı son paketlemeyi açıkça başlattığında program ZIP'i oluşturulur ve ZIP bütünlüğü kontrol edilir; SHA-256 doğrulama dosyası, `surum-00` Release dosyaları ve 14 gün saklanan Actions artefaktı da bu aşamada yayımlanır. Programı kullanmak için bunların tamamını indirmen gerekmez; ZIP yeterlidir. Sabit indirme bağlantısı olağan kod gönderimlerinde değişmez.

Programa ait dağıtım ZIP'ine gerekli masaüstü dosyaları ve `market_data_relay.json` eklenir. Sunucunun Node.js kaynakları (`render_relay/`) masaüstü ZIP'ine konmaz; Render bunları GitHub deposundan kendisi oluşturur. Paket içindeki `market_data_relay.json` aktif Render adresini göstermelidir. ZIP'in bütünlüğü paketleme sırasında kontrol edilir; ayrıca indirilecek bir özet dosyasına gerek yoktur.

### Tekrarlanabilir çözüm / gelecekteki bakım

1. Bilgisayarın doğrudan HTTPS erişimi tekrar bozulursa önce mevcut tanılama sonuçları ve ağdaki yönlendirme hedefi incelenir; doğrulanmış Türk Telekom filtre bulgusu unutulup yeniden proxy ayarı aranmamalıdır.
2. Bulut geçidi değiştirilecekse önce sunucu sağlık kontrolü, gerçek Binance REST mum verisi, BtcTurk USDT ticker'ı ve gerçek Binance WebSocket mum mesajı ayrı ayrı doğrulanır. Sadece sunucunun live olması yeterli değildir.
3. Yeni geçidin adresi kaynak market_data_relay.json dosyasına yazılır; GitHub Actions içinde güncel paket adresi ve canlı smoke-test adresi aynı tutulur. Bu iki adresin tutarsız kalmasına izin verilmez.
4. Kod veya yapılandırma `main` dalına kaydedildiğinde otomatik doğrulama sonuçları kontrol edilir. Program ZIP'i ve Release indirme bağlantısı yalnızca kullanıcı son paketlemeyi istediğinde güncellenir; bağlantı ancak bu paketleme başarılıysa güncel kabul edilir.
5. Render ücretsiz hizmeti kullanım dışı kaldığında uykuya geçebileceği için, taramaya yeniden başlanırken ilk bağlantı gecikmesi ve WebSocket yeniden bağlanma durumu normalleştirilmeden canlı piyasa verisi güncel kabul edilmez.

## ChatGPT bağlantısı — Analiz Raporu

Paneldeki **Analiz Raporu** butonu, motor tanı raporlarından ayrı bir teknik analiz özeti üretir. Aday puanları ve kararları, zaman dilimi bulguları, seçilmiş teknik göstergeler, BTC piyasa bağlamı, veri yeterliliği ve koşullu giriş/stop/hedef planları rapora dahil edilir. Ham mum dizileri ve motor tanılama alanları bu rapora dahil edilmez.

Analiz raporu JSON olarak hazırlanır ve gzip ile sıkıştırılır. Yerel kopya sabit `reports/analiz_raporu.json.gz` dosyasına yazılır; her yeni rapor aynı dosyanın üzerine kaydedilir, tarihli yeni dosya oluşturulmaz. Günlük durum raporunun JSON, Markdown ve tanı dosyaları da sabit dosya adlarıyla gzip biçiminde saklanır ve her üretimde öncekinin üzerine yazılır; Markdown metni kolay inceleme için panoya normal metin olarak kopyalanır. Devir paketi `reports/firsat_kontrol_devir.zip` sabit adıyla oluşturulur ve önceki paketin üzerine yazılır. Sunucu bağlantısı yapılandırılmamışsa panel yalnızca yerel dosyaları üretir; piyasa taramasını etkilemez. Yapılandırılmışsa rapor HTTPS üzerinden, yetkilendirilmiş yükleme uç noktasına arka planda gönderilir.

Bağlantı mimarisi: [Cloudflare rapor Worker kılavuzu](cloudflare/report-worker/README.md). Worker adresi programda sabittir; yükleme anahtarı Windows Kimlik Bilgileri Yöneticisi'nde saklanır. İlk güncellemede ZIP'i mevcut program klasörüne ayıklayın ve eski chatgpt_baglanti.local.json dosyasını önceden silmeyin. Programın ilk açılışında yalnızca bilinen Worker adresi kabul edilir; anahtar Windows kasasına taşınır, geri okunarak doğrulanır ve bundan sonra eski dosya silinir. Kayıt başarısızsa dosya korunur.

**Güvenlik:** Kod commitleri Worker dağıtımını veya Cloudflare gizli anahtarının (UPLOAD_TOKEN) kurulumunu değiştirmez; mevcut Worker ve anahtar ayrı kalır. Tüm yükleme uç noktaları Bearer anahtarını doğrular. Okuma adresleri bağlantıyı bilenlere açıktır; raporlara parola veya başka gizli bilgi koymayın. ChatGPT sohbetine otomatik mesaj gönderilmez; rapor bağlantısı ayrıca açılarak okunur.


## Aday tablosu

Aday tablosu Binance fiyatının yanında BtcTurk fiyatını ve fırsat puanını da gösterir. BtcTurk fiyatı yalnızca görüntüleme içindir; Binance analiz motorunun karar girdisi değildir. Fiyat alınamazsa “veri yok”, son başarılı örnek 90 saniyeden eskiyse “veri eski” yazılır. Fiyat farkı sütunu eklenmez.vurgulanması gereken kelime rakamlar büyük harf ve farklı renklerde anlam bütünlüğünde olur.


## Üç raporlama düğmesi

- **Günlük Rapor Oluştur:** Programın genel durumunu ve çalışma özetini üç gzip dosyası olarak yerel reports klasörüne kaydeder: `.json.gz`, `.md.gz` ve `_tani.json.gz`. Markdown metni ayrıca panoya okunabilir metin olarak kopyalanır.
- **Sorun Giderme ve Devir Paketi (ZIP):** Sıkıştırılmış günlük raporları, gzip biçimindeki tanı özeti ve sınırlı günlük kaydını, bütünlük manifestiyle birlikte tek ZIP dosyasında toplar.
- **Analiz Raporu Gönder:** Radarın coin analiz sonuçlarını `.json.gz` biçiminde yerel dosyaya kaydeder ve bağlantı ayarlanmışsa aynı sıkıştırılmış içeriği sunucuya gönderir. Bu rapor motor tanılamasını veya günlük kayıtlarını içermez.

Bu üç düğme farklı amaçlara hizmet eder; birbirlerinin yerine geçmez.
