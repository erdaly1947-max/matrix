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

Başlangıç kodunda Python sözdizimi ve depolama bakımının arşivleme/SHA-256 akışı daha önce kontrol edilmiştir. Komisyon/kayma hesabının kaldırılması kaynak kod üzerinden statik olarak gözden geçirilmiştir. Sürüm 00 hazırlığında README kuralları ve APP_VERSION etiketi tutarlılaştırılır; bu işlemler sonrasında yerel Python derleyicisiyle yeniden derleme ve Windows üzerinde canlı Binance/BtcTurk uçtan uca çalışma testi yapılmış sayılmaz. **Bu kaynak durumu bitmiş/dağıtıma hazır ZIP olarak değerlendirilmemelidir.**

`ayarlar.json` komisyon/kayma ayarlarını içermez. Program bu oranları hesaplamaz ve karar/alarmlarda kullanmaz. Güçlü fırsat kapısı, en yakın teknik hedef için brüt teknik risk/getiri oranının en az 1,5 olmasını ister; spread ayrı likidite filtresinde değerlendirilir.

## Sürüm 00 — başlangıç noktası ve geçerli durum

- **Sürüm 00, geliştirmelerin başlangıç tabanıdır.** Bu aşamada amaç, mevcut tek motorlu programı ve işlevlerini inceleyip başlangıç noktasını tutarlı ve doğrulanabilir hâle getirmektir; programı baştan yazmak değildir.
- Kaynak koddaki program sürüm etiketi, radar_core.py içinde APP_VERSION = "00" olarak tutulur.
- Bu başlangıç hazırlığında README çalışma kuralları ve sürüm etiketi düzeltilir. Bu değişiklik, aşağıda tasarlanan yeni özelliklerin uygulanmış olduğu veya programın son ZIP paketinin dağıtıma hazır olduğu anlamına gelmez.
- main, sürüm 00'ın temel kodunu korur. Bu başlangıç hazırlığı tamamlandıktan sonra yeni özelliklerin kod değişiklikleri ayrı, sürüm/iş kapsamı açık yan dallarda yürütülür.
- **Dal açma yetkisi kullanıcı onayına bağlıdır:** Kullanıcı önceden açıkça onay vermeden hiçbir nedenle yeni dal açılmaz. Sürüm 00 düzeltmeleri `main` üzerinde yapılır. Sürüm 1 için kullanıcı onay verirse kullanılacak dal adı `1.surum-readme-gereksinimler` olacaktır.
- Geliştirme dalındaki değişiklikler, gerekli testler ve bütünlük kontrolleri tamamlanmadan ve kullanıcı onayı alınmadan main dalına aktarılmaz. Sürüm 1, sürüm 00'ın başlangıç hazırlığıyla karıştırılmaz ve yalnızca belirlenmiş son doğrulama kapısı geçildikten sonra oluşturulur.

## Kalıcı çalışma kuralları

Bu bölüm, proje boyunca uygulanacak çalışma düzenini tanımlar. Kullanıcının sonradan bildirdiği yeni kurallar bu bölüme eklenir; tekrar eden hükümler birleştirilir, hiçbir kuralın anlamı değiştirilmez. Buradaki kurallar, çelişen eski çalışma notlarına göre önceliklidir ve kullanıcı aksini belirtmedikçe geçerlidir.

### 1. Çalışma alanı ve kayıtların yeri

- Program yazımı, kod düzenleme ve bunlarla ilgili bütün çalışmalar yalnızca GitHub üzerinde yürütülür.
- **Kesin dal kuralı:** Kullanıcıya önceden haber vermeden ve açık onayını almadan yeni Git dalı açılmaz. Bu kural tüm aşamalarda geçerlidir.
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

### 4. Gereksinim kaydı, kodlama, test ve durum güncellemesi

- Gereksinimler, kabul edilmiş tasarım kararları ve uygulama yöntemi kodlamadan önce README'ye kaydedilir. Tasarım onayı alınmadan ilgili kodda değişiklik yapılmaz.
- Birbiriyle ilişkili kodlama işleri anlamlı ve işlevsel gruplar hâlinde tamamlanır; işler gereksiz yere küçük parçalara ayrılmaz.
- Bir kodlama grubu için belirlenen kapsam bitmeden o gruba ait test turu başlatılmaz. Kodlama tamamlanınca ilgili testler topluca, ardından gerekli genel regresyon testleri çalıştırılır.
- Testlerde başarısız sonuç varsa gerekli düzeltmeler yapılır ve etkilenen testler yeniden çalıştırılır. Başarısız testleri bulunan bir grup veya sürüm tamamlanmış sayılmaz.
- **Gereksinim ve tasarım kaydı ile uygulama durumu kaydı birbirinden ayrıdır:** Gereksinimler ve planlanan davranış önceden yazılır; uygulamanın tamamlandığı, test edildiği veya başarılı olduğu bilgileri yalnızca gerçek kod ve test kanıtları görüldükten sonra güncellenir.
- İlgili uygulama ve test grubu tamamlandığında sonuçlar, kalan eksikler ve sürüm kayıtları README'de gerçeğe uygun biçimde güncellenir. Uygun olduğunda ilgili kod, test ve durum kayıtları tek commit altında toplanır.
- Tamamlanmış işler tekrar uygulanmaz. Her yeni değişiklik doğrulanmış bir eksiğe veya kullanıcı tarafından onaylanmış yeni bir gereksinime dayanır.

### 5. Dal, sürüm, aşamalar arası aktarım ve son ZIP paketi

- Sürüm 00 başlangıç tabanıdır. Bu başlangıç hazırlığında README ve kaynak koddaki APP_VERSION etiketi "00" olarak tutarlılaştırılır. Bu hazırlık, planlanan yeni özelliklerin uygulanmış olduğu anlamına gelmez.
- **Dal açılmadan önce açık kullanıcı onayı zorunludur.** Onay olmadan dal oluşturulmaz, yeniden adlandırılmaz veya başka bir dal geliştirme alanı olarak seçilmez. Sürüm 00'a ait başlangıç/düzeltme işleri `main` üzerinde yürütülür. Kullanıcı Sürüm 1 dalı açılmasını onaylarsa dal adı tam olarak `1.surum-readme-gereksinimler` olur. Bu dalda geliştirme yapılması da yalnızca onaylanan kapsamla sınırlıdır.
- Yan dalda yapılan değişiklikler gerekli hesaplama, regresyon, geçmiş veri, panel, raporlama ve paket kontrolleri tamamlanmadan main dalına aktarılmaz. Sürüm 1 ancak bu kontroller ve ilgili kullanıcı onayı sonrasında hazırlanır.
- Her aşamanın sonunda, yeni sohbet odasında kesintisiz devam edilebilmesi için kesinleşmiş kararlar, tamamlanan işler, doğrulanmış eksikler ve sıradaki aşamanın amacı birlikte aktarılır.
- Bağlam aktarımı tamamlanmış sayılmadan önce güncel README kontrol edilir; aktarım README'deki gerçek durumla tutarlı olmalıdır.
- ZIP paketi hazırlanırken aktarılan dosyalar arasında BtcTurk evreni bulunur.
- Nihai ZIP paketi oluşturulmadan önce son paket aşaması kullanıcıya bildirilir ve açık onayı alınır. Bu bildirim ve onay olmadan son ZIP paketi oluşturulmaz.

## Geliştirme hedefi ve ortak karar sistemi

### 6. Ana karar: mevcut tek motoru koru, üzerine geliştir

Programın amacı, mevcut tek motorlu sistemi koruyarak hızlı yükseliş potansiyeli taşıyan coinleri daha erken ve daha isabetli değerlendirmektir. İlk hedef, mevcut motorun yaptığı hesaplamaları yeniden yazmak değil; eksik kalan yönlerini mevcut işlevler üzerinden geliştirmek ve sonuçlarını ortak bir karar yapısında birleştirmektir.

- Mevcut program baştan yazılmaz; çalışan ve gerekli işlevler korunur.
- Aynı gösterge, piyasa verisi veya teknik seviye hesabı farklı yerlerde gereksiz yere tekrarlanmaz. Mevcut hesaplamaların çıktıları yeniden kullanılır ve ihtiyaç duyulan geliştirmeler uygun mevcut modüle bağlanır.
- Yeni bir fonksiyon veya modül ancak mevcut işlevin geliştirilmesiyle ihtiyacın karşılanamayacağı kod incelemesiyle gösterildiğinde değerlendirilir.
- Yeni özelliklerin aday sıralamasını, A/B/C aşama sınıflandırmasını, alarmları veya mevcut panel davranışını değiştirmesi tasarımda açıkça belirtilir; sessiz ve doğrulanmamış davranış değişikliği yapılmaz.
- Amaç, ilk bakışta piyasanın durumunu, hangi coinlerin neden öne çıktığını ve seçilen coindeki olası getirinin riskine değip değmediğini anlamayı sağlamaktır. Ayrıntılı analizler ve mevcut işlevler erişilebilir kalır.
- Program halka açık piyasa verilerini okuyan bir analiz ve karar destek aracıdır. Bu gereksinimler kendi başına borsa hesabına bağlanma, emir gönderme veya otomatik alım-satım yetkisi oluşturmaz.

### 7. İlk somut iş: mevcut–eksik–geliştirme–test matrisi

Yeni kod yazmadan önce mevcut sistemin gerçek durumu güvence altına alınır. Kod, mevcut fonksiyonlar, veri akışı ve testler incelenir; hâlihazırda çalışan, kısmen çalışan ve eksik olan işlevler birbirinden kesin biçimde ayrılır. Bir davranış yalnızca tasarım belgesinde yer aldığı için uygulanmış kabul edilmez.

Her mevcut fonksiyon için şu üç soru yanıtlanır:

1. **Şimdi ne yapıyor?** Kodda gerçekten bulunan işlev ve ürettiği sonuç nedir?
2. **Nerede yetersiz kalıyor?** İstenen davranışın hangi parçası eksik, kısmi veya testlerle doğrulanmamış?
3. **Mevcut fonksiyon nasıl geliştirilirse ihtiyaç karşılanır?** Hangi mevcut modülde, hangi hesaplama ve sonuçlar yeniden kullanılarak geliştirme yapılabilir?

Matris en az şu sütunları içerir:

| Fonksiyon/modül | Şu anki davranış ve kod kanıtı | Eksik veya yetersiz kalan yön | Mevcut yapı üzerinden geliştirme | Yeniden kullanılacak hesaplama/veri | Doğrulama testi | Durum |
|---|---|---|---|---|---|---|
| Ortak USDT parite evreni — ortak_piyasa.py:fetch_common_usdt_symbols, tek_motor_evreni.py:build_single_engine_universe | Binance ve BtcTurk Spot USDT çiftlerini eşleştirir; veri kaynağı/cache modu, parite sayıları ve uyarılar döndürülür. | Canlı borsa uç noktaları ve cache geri dönüşleri bu incelemede çalıştırılarak doğrulanmadı. | Mevcut ortak evren ve cache akışı korunur; yeni bir paralel evren hesabı yazılmaz. | pairs, evren modu, kaynak zaman damgası ve mevcut eşleştirme sonuçları. | Canlı ve cache modu, boş/uyumsuz evren, aktif olmayan pariteler ve USDT eşleşmesi için test. | Uygulanmış; çalıştırılmadı |
| Mum akışı, veri güncelliği ve 8 zaman dilimi — binance_erken_firsat_radari.py:TIMEFRAMES, BinanceRadar; radar_core.py:valid_bars | Motor 5m, 15m, 30m, 1h, 4h, 1d, 1w ve 1M zaman dilimlerini tanımlar; kapanmış ve zaman hizalı mumları, akış tazeliğini ve eksik/kesintili geçmişi kontrol eden yapılar içerir. | Sekiz zaman diliminde canlı akış, boşluk onarımı, zaman hizası ve eski veri davranışı bu turda çalıştırılarak test edilmedi. | Mevcut WebSocket/REST, arşiv ve geçerlilik kontrolleri üzerinde ilerlenir; ikinci bir mum/veri katmanı açılmaz. | Mevcut mum arşivi, valid_bars, zaman dilimi sabitleri ve akış yaşları. | Her zaman dilimi için kapanmış/açık mum, zaman boşluğu, eski akış, onarım ve veri yok senaryoları. | Uygulanmış; çalıştırılmadı |
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

**İnceleme sınırı:** Bu matris main üzerindeki mevcut kaynak kodun statik okunmasına dayanır. Bu çalışmada Python derlemesi, birim/regresyon testi, canlı Binance/BtcTurk bağlantısı, tarihsel backtest veya Windows panel testi çalıştırılmadı. Depoda bu incelemede görülen ağaçta ayrı bir test dizini/suite'i de bulunmuyor. Bu nedenle “uygulanmış” kodun testten geçtiği anlamına gelmez; tüm satırlarda doğrulama işi açık kalır.

Bu matris, Sürüm 00 için ilk düzeltme grubunu

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

Yakın direnç, teknik bulgulara dayalı olası kâr alma bölgesidir; kesin fiyat tahmini veya otomatik satış emri değildir. Teknik hedefler, gerçek destek/direnç ve fiyat yapısıyla gerekçelendirilir. Sadece matematiksel risk katları kullanılarak teknik hedef belirlenmiş gibi gösterilmez.

Mevcut README'de kayıtlı başlangıç davranışı korunarak dikkate alınır: güçlü fırsat kapısı, en yakın teknik hedef için brüt teknik risk/getiri oranının en az 1,5 olmasını ister; spread ayrı likidite filtresinde değerlendirilir. Bu mevcut kural sessizce değiştirilmez. Eşiğin veya düşük kaliteli fırsatları dışlama koşullarının değiştirilmesi gerekiyorsa kod incelemesi, gerekçeli tasarım ve geçmiş verilerle doğrulama gerekir. Mevcut `ayarlar.json` komisyon/kayma ayarlarını içermez ve mevcut sürüm bu maliyetleri hesaplamaz. Masraflar sonrası net risk/getiri gereksinimi, maliyet varsayımları açıkça tanımlanıp uygulanıp test edilene kadar mevcut özellikmiş gibi gösterilmez.

### 9. Panel yerleşimi ve gösterilecek bilgiler

Panel bütün analizleri aynı anda ekrana yığmak yerine karar için gerekli bilgileri öne çıkarır; ayrıntılar kaybolmaz, gerektiğinde incelenebilir. Mevcut alanlar ve davranışlar, aşağıdaki yeni yerleşimle uyumlu biçimde korunur.

#### Kullanıcının kesinleştirdiği görünüm ve mevcut kontroller

- Hedef çalışma ortamı Windows, ekran çözünürlüğü 1920×1080 ve Windows ölçeklendirmesi %125'tir. Panel başlangıçta ekran genişliğinin yaklaşık yarısına sığacak şekilde tasarlanır; okunabilirlik gerektirirse genişlik en fazla ekranın yaklaşık %80'ine çıkarılabilir. Pencere yüksekliği ekran yüksekliğinden en az %7 daha kısa olmalıdır.
- Koyu tema temel alınmaz. Açık/normal görünümde kırmızı, sarı, mavi, yeşil, lila, turkuaz ve lacivert gibi durum renkleri kullanılabilir; yazıların arka planı gri tonlarında, ayırıcı çizgiler beyaz olur. Renk tek başına karar gerekçesi sayılmaz; renkli durumun anlaşılır metinsel karşılığı bulunur.
- Ses seviyesi kontrolüne benzer bir parlaklık/aydınlık ayarı eklenmesi planlanır. Mümkünse ses kontrollerinin yakınında yer alır. Bu kontrol henüz mevcut özellik sayılmaz; kodlamadan önce nihai yerleşim içinde gösterimi netleştirilir.
- Mevcut yararlı kontroller korunur veya aynı işlev açık kalacak şekilde uyarlanır: parite/harita listesini güncelleme, rapor ve devir ZIP'i oluşturma, Başlat, Durdur, Alarm Açık/Kapalı, ses seviyesi, sesi denetleme ve seçilen coin için giriş/hedef seviyelerini izleme. Kontrol etiketleri tasarım onayında tutarlılaştırılır.
- Adayların mevcut A/B/C aşamaları ve anlamları korunur: A hazırlık, B yapı/kırılım, C devamlılık. Kapalı mumda katılım, geri test ve devamlılık teyitleri kaybolmaz. Eski/eksik veri için mavi uyarı korunur.
- Karar alanları mevcut işlevler üzerinden düzenlenir: **Adaylar** listesi; **Giriş Kontrolü** içinde senaryo zaman dilimi, kırılım seviyesi, zarar durdurma ve olası giriş; **Seçilen Coin** içinde kırılım seviyesi, zarar durdurma ve teknik hedefler. Bunlar ham hesap çıktıları yığınına çevrilmez; hızlı karar bilgisi öne çıkarılır, ayrıntılar erişilebilir kalır.
- Yerleşim ve ölçüler için tasarım kararı kod değişikliğinden önce gözden geçirilir. Bu maddeler arayüzün gereksinimidir; mevcut panelin bunları uyguladığı veya ekran üzerinde sınandığı anlamına gelmez.

#### A. Üst bölüm — BTC ve genel piyasa

Mevcut motor durumu, bağlantı bilgileri, alarmlar ve parite evreni bilgileri korunur. Mevcut **“Piyasa ve parite evreni”** alanı kaldırılmaz; BTC piyasa bağlamıyla genişletilir. Burada kısa ve anlaşılır biçimde şunlar gösterilir:

- BTC ana yönü ve genel piyasa risk durumu.
- Güçlü destek ve direnç bölgeleri.
- Yatay kanal varsa alt ve üst sınırları.
- Önemli kırılım veya önemli seviye kaybı.
- Verinin güncel olup olmadığı ve varsa veri eksikliği.

BTC özeti nedeniyle mevcut parite evreninin kapsamı veya durumu kaybolmaz.

#### B. Orta bölüm — öncelikli adaylar

Mevcut aday tablosu korunur. A/B/C aşamaları, fiyat, veri durumu, zaman dilimi ve keşif yolu bilgileri kaybolmaz. Tabloyu gereksiz kalabalıklaştırmadan coin için kısa bir **BTC'ye göre durum** bilgisi eklenir; adayın BTC'den daha güçlü veya daha zayıf performans gösterip göstermediği ilk bakışta anlaşılabilir.

Ayrıntılı korelasyon değerleri aday tablosunu doldurmak yerine seçilen coin bölümünde gösterilir. Yeni hesaplamaların gösterimi mevcut aday sıralamasını veya aşama sınıflandırmasını sessizce değiştirmez. Sıralama veya sınıflandırma mantığında yapılacak değişiklik ayrı olarak gerekçelendirilip test edilir.

#### C. Seçilen coin — hızlı karar özeti ve teknik ayrıntılar

Mevcut **“Seçilen adayın özeti”** alanı, hızlı karar özeti ile ayrıntılı analiz olmak üzere iki bölüme ayrılır.

**Sol bölüm — hızlı karar özeti:**

- Coinin mevcut teknik aşaması.
- BTC ile ilişkisi, BTC'ye göre performansı ve BTC koşullarının aday üzerindeki etkisi.
- Ana fiyat yapısı: yükseliş, düşüş veya yatay kanal.
- En önemli yakın destek ve direnç bölgeleri.
- Fırsatın önündeki temel engel veya eksik teyit.
- Açıklanabilir genel durum: “izlemeye değer”, “teyit bekleniyor”, “risk yüksek” veya “veri yetersiz” gibi sonuçlar.

**Sağ bölüm — mevcut ayrıntılı analiz:**

- EMA, MACD, RSI, ADX, DMI ve ATR gibi mevcut teknik bulgular.
- Sekiz zaman diliminin değerlendirmeleri.
- A/B/C aşamasının gerekçeleri.
- Mevcut analiz ve kontrollerin sonuçları, eksik kontroller ve veri güncelliği.

Hızlı özet, ayrıntılı analizin yerine geçmez; mevcut teknik bulguları anlaşılır bir karar görünümünde birleştirir. Renkler ve etiketler sonucu özetleyebilir, ancak bir rengin kendisi karar gerekçesi olamaz. Her önemli uyarının anlaşılır bir nedeni bulunur. Gösterilen durumlar otomatik alım-satım kararı değildir.

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

Gerçek teknik hedef ile matematiksel hedef aynı şeymiş gibi gösterilmez. Teknik hedefe ulaşmak için kalan getiri yetersizse bu, hızlı özette açıkça belirtilir ve fırsat kalitesi kuralları uygulanır. Teknik hedef otomatik emir değildir.

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
- `tests/test_btc_correlation_adjustment.py` içine eşik, riskli/sağlıklı BTC, eski veri, yetersiz örnek, negatif korelasyon ve puan bileşeni için otomatik testler eklendi. `.github/workflows/validate-and-package.yml` kaynak derleme, birim test ve ZIP/SHA-256 üretimini tarif eder.

### Doğrulama durumu — dikkat

- Bu oturum boyunca GitHub Actions doğrulama iş akışı birden fazla kez tetiklendi; denemeler çalışma adımlarına ulaşmadan başarısız oldu. İş kayıtlarında çalıştırıcı atanmadı (`runner_id=0`, `runner_name` boş) ve adım listesi boş döndü. Bu nedenle Python derlemesi, otomatik testler ve iş akışıyla ZIP üretimi **çalıştırılmış veya başarılı sayılmaz**.
- Bu oturumda yerel Python çalıştırıcısıyla derleme, birim/regresyon testleri, canlı Binance/BtcTurk bağlantısı veya Windows/Tkinter ekran testi yapılamadı. Kod değişiklikleri kaynakta okunarak doğrulandı; bu, çalışan uygulama testi değildir.
- Komisyon ve kayma sonrası net getiri hesabı eklenmedi ve bilerek eklenmeyecektir. Teknik risk/getiri brüt kalır; emir gönderimi veya otomatik alım-satım bulunmaz.
- Sürüm 00 kaynak arşivini indirmek için GitHub'ın `main` dalı ZIP bağlantısı kullanılabilir: https://github.com/erdaly1947-max/matrix/archive/refs/heads/main.zip . Bu, GitHub'ın ürettiği kaynak arşividir; çalıştırıcı başarısızlığı nedeniyle bu oturumda bağımsız bir derleme/artifact ZIP'i oluşturulmuş gibi raporlanmaz.
- Kullanıcının yerel canlı test sonucu gelene kadar Sürüm 1 çalışmasına geçilmez. Dal açılması gerekirse kullanıcıdan önceden açık onay alınır; Sürüm 1 dalı adı ancak onaydan sonra `1.surum-readme-gereksinimler` olur.
