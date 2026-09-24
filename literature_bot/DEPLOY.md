# Literatür Botu'nu internete yayınlama (ücretsiz) — adım adım

Bu belge, `literature_bot` klasöründeki web uygulamasını (webapp.py) hem masaüstü
hem de telefon tarayıcınızdan girebileceğiniz gerçek bir internet adresine
(`https://....onrender.com` gibi) **tamamen ücretsiz** olarak nasıl
yayınlayacağınızı anlatır.

## Genel bakış — neden 3 ayrı ücretsiz hesap gerekiyor?

Gerçek, kalıcı ve internetten erişilebilir bir uygulama için 3 parça gerekiyor,
her biri ayrı bir ücretsiz servisten:

1. **GitHub** — kodun duracağı yer (Render'ın oradan okuyup çalıştırması için).
   Sadece bir hesap + dosyaları sürükle-bırak ile yüklemeniz yeterli, hiç
   komut satırı/git bilgisi gerekmiyor.
2. **Render** — uygulamayı gerçekten çalıştıran ücretsiz sunucu.
3. **Turso** — kaydettiğiniz kaynakların (kütüphanenizin) kalıcı olarak
   saklandığı ücretsiz veritabanı. Bu ayrı bir servis olmasının sebebi: Render'ın
   ücretsiz planında sunucunun kendi diski her yeniden başlatmada silinir, o
   yüzden kütüphanenizi orada tutamayız — Turso hem ücretsiz hem de kalıcı.

Hepsi bittiğinde: NVIDIA API anahtarınızı (ve diğer ayarları) SADECE Render'a,
sunucu tarafına gireceksiniz — tarayıcıya, koda ya da GitHub'a hiçbir anahtar
girmeyeceksiniz.

Toplam süre: yaklaşık 15-20 dakika, hepsi tarayıcıdan.

---

## Adım 1 — Turso (veritabanı) hesabı ve veritabanı oluşturma

1. https://app.turso.tech adresine gidin, **Sign up** ile ücretsiz bir hesap
   açın (GitHub veya e-posta ile).
2. Panelde **Create Database** (veya benzeri) butonuna tıklayın, veritabanına
   bir isim verin (örn. `literatur-botu`), bölge olarak size yakın birini
   seçin, oluşturun.
3. Veritabanının detay sayfasında:
   - **Database URL**'i kopyalayın — `libsql://literatur-botu-kullaniciadi.turso.io`
     gibi görünür. Bunu bir yere not edin.
   - **Create Token** (ya da "Auth Tokens" sekmesi) ile yeni bir token oluşturun
     ve onu da kopyalayıp not edin. Bu token bir daha gösterilmeyebilir, kaybetmeyin.

Bu ikisi (`TURSO_DATABASE_URL` ve `TURSO_AUTH_TOKEN`) az sonra Render'a
gireceğiniz iki ortam değişkeni olacak.

---

## Adım 2 — Kodu GitHub'a yükleme

1. https://github.com adresinde ücretsiz bir hesabınız yoksa **Sign up** ile
   açın.
2. Sağ üstteki **+** işaretinden **New repository** seçin.
   - Repository adı: `literatur-botu` (istediğiniz bir isim olabilir)
   - **Public** seçili kalsın (Render'ın hesabınızı bağlamadan doğrudan
     okuyabilmesi için repo herkese açık olmalı — içinde hiçbir API anahtarı
     YOK, sadece kod var, bu yüzden güvenli).
   - **Create repository** butonuna basın.
3. Açılan boş repo sayfasında **"uploading an existing file"** linkine
   tıklayın (ya da **Add file → Upload files**).
4. Size verilen `literature-bot-web.zip` dosyasını bilgisayarınızda açın
   (sağ tık → "Tümünü Çıkart" / "Extract All"), açılan klasörün İÇİNDEKİ
   tüm dosya ve klasörleri (webapp.py, static/, literature_bot/, requirements.txt,
   Procfile, `dergipark_cache.sqlite3.gz`, .gitignore, ...) seçip GitHub'daki
   yükleme alanına sürükleyip bırakın.
   - `.env` dosyası zip'in içinde YOK — bu bilinçli, hiçbir anahtar GitHub'a
     gitmeyecek.
   - DergiPark indeksi `dergipark_cache.sqlite3.gz` olarak (sıkıştırılmış,
     ~10 MB) geliyor — GitHub'ın tarayıcıdan yükleme özelliği dosya başına
     25 MB ile sınırlı olduğu için böyle paketledik. Uygulama bunu ilk
     çalıştığında kendisi otomatik açar, sizin ekstra bir şey yapmanız
     gerekmiyor.
   - Yükleme birden fazla dosya olduğu için tarayıcınız "tek tek mi yoksa
     hepsi bir arada mı" diye sormayabilir, hepsini aynı anda sürükleyip
     bırakmanız yeterli; büyükçe bir yükleme olduğu için birkaç dakika
     sürebilir, sayfayı kapatmadan bekleyin.
5. Sayfanın altındaki **Commit changes** butonuna basın.
6. Yüklenen repo sayfasının URL'sini not edin, örn:
   `https://github.com/kullaniciadi/literatur-botu`

---

## Adım 3 — Render (sunucu) hesabı ve Web Service oluşturma

1. https://render.com adresinde ücretsiz bir hesap açın (GitHub ile giriş
   yapmanız en hızlısı, ama GitHub hesabınızı Render'a "bağlamanıza" GEREK
   YOK — bir sonraki adımda "Public Git Repository" seçeneğini kullanacağız).
2. Panelde **New +** → **Web Service** seçin.
3. Deployment kaynağı sorulduğunda **"Public Git Repository"** (hesap
   bağlamadan, sadece URL ile) seçeneğini seçin ve Adım 2'de not ettiğiniz
   GitHub repo adresini yapıştırın.
4. Servis ayarları:
   - **Name**: istediğiniz bir isim (bu, adresinizin bir parçası olacak:
     `https://isim.onrender.com`)
   - **Region**: size yakın biri
   - **Branch**: `main`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn webapp:app --timeout 120`
   - **Instance Type**: **Free**
5. **Environment Variables** (ortam değişkenleri) bölümüne şunları tek tek
   ekleyin (Key / Value):

   | Key | Value |
   |---|---|
   | `NVIDIA_API_KEY` | (NVIDIA anahtarınız, `nvapi-...`) |
   | `TURSO_DATABASE_URL` | (Adım 1'de kopyaladığınız `libsql://...` adresi) |
   | `TURSO_AUTH_TOKEN` | (Adım 1'de kopyaladığınız token) |
   | `UNPAYWALL_EMAIL` | `kzenbil10@gmail.com` |
   | `OPENALEX_EMAIL` | `kzenbil10@gmail.com` |
   | `DERGIPARK_DB` | `dergipark_cache.sqlite3` |
   | `APP_PASSWORD` | *(isteğe bağlı — bir şifre yazarsanız uygulamanın adresini bulan başkaları kullanamaz; boş bırakırsanız herkese açık olur)* |

6. **Create Web Service** butonuna basın. Render otomatik olarak kodu çekip
   kuracak ve çalıştıracak — bu ilk dağıtım birkaç dakika sürebilir (loglardan
   izleyebilirsiniz).
7. Kurulum bitince sayfanın üstünde adresiniz görünecek:
   `https://isim.onrender.com` — bu adres hem masaüstünüzden hem telefonunuzdan
   (aynı adresi yazarak) açılır, kurulum gerektirmez.

**Not (ücretsiz planın sınırı):** Render'ın ücretsiz Web Service'i 15 dakika
boyunca hiç istek gelmezse "uyur"; bir sonraki ziyarette ilk açılış ~30-60
saniye sürebilir (sonrasında normal hızda çalışır). Bu ücretsiz planın
doğal bir özelliği, bir hata değildir.

---

## Adım 4 — Test edin

1. Adresi telefonunuzda ve bilgisayarınızda açın.
2. "Ara" sekmesinde bir konu yazıp arayın, birkaç kaynak seçin.
3. Bir sonucu "Kütüphaneye Kaydet" ile kaydedin (isterseniz "tam metni indir"
   kutucuğunu işaretleyin).
4. "Kütüphanem" sekmesinden kaydettiğinizi görün.
5. "Taslak Oluştur" sekmesinden bir taslak üretin ve indirin.

---

## Sorun giderme

- **Sayfa hiç açılmıyor / "Application failed to respond"**: Render
  panelinde servisinizin **Logs** sekmesine bakın — genelde eksik bir ortam
  değişkeni ya da `requirements.txt` kurulum hatasıdır.
- **Arama çalışıyor ama "DergiPark uyarı" çıkıyor**: `dergipark_cache.sqlite3.gz`
  dosyasının GitHub reposuna gerçekten yüklendiğinden emin olun (repo sayfasında
  görünmeli, ~10 MB). Görünüyorsa ama uyarı hâlâ çıkıyorsa Render'ın Logs
  sekmesine bakın — dosyanın açılması (decompress) sırasında bir hata olup
  olmadığı orada görünür.
- **Çeviri/derin sentez/taslak bazen "LLM yapılandırılmadı" ya da kural
  tabanlı bir sonuca düşüyor**: NVIDIA'nın ücretsiz katmanı zaman zaman yavaş/
  yanıtsız kalabiliyor (bu, projenin başından beri bilinen bir durum) — birkaç
  dakika sonra tekrar deneyin. Model kaldırılmış/değişmiş olabilir; Render'ın
  ortam değişkenlerine `LLM_MODEL` ekleyip güncel bir model adı yazabilir,
  hangi modellerin şu an çalıştığını görmek için yerel makinenizde
  `python -m literature_bot.llm_probe` çalıştırabilirsiniz.
- **Kütüphanem her deploy'da boşalıyor**: `TURSO_DATABASE_URL` ortam
  değişkeninin doğru girildiğinden emin olun — girilmemişse uygulama sessizce
  yerel (kalıcı olmayan) bir dosyaya düşer.
- **Kodda bir düzeltme/güncelleme yapmam gerekirse**: GitHub reposundaki
  dosyayı düzenleyip commit edin (GitHub'ın kendi web düzenleyicisiyle de
  olur) — Render "Auto-Deploy" açıksa otomatik yeniden dağıtır; kapalıysa
  Render panelinden **Manual Deploy** ile tetikleyin.
