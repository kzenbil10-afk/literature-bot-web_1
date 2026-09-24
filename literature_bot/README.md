# literature-bot

Makale/tez yazımında kullanılmak üzere hazırlanmış, çok kaynaklı **literatür taraması,
kaynak bulma, derinlemesine araştırma (deep research) ve taslak yazımı** aracı. Tek bir
konu sorgusu verirsiniz; bot birden fazla akademik veritabanını aynı anda tarar,
sonuçları tekilleştirip alaka/atıf/güncellik skoruna göre sıralar, tematik olarak
gruplar ve size doğrudan **APA formatlı kaynakça + BibTeX dosyası** içeren bir Markdown
rapor üretir. Beğendiğiniz kaynakları kişisel **kütüphanenize kaydedebilir**, isterseniz
gerçek PDF'lerini de indirebilir, ve oradan tek komutla **sentezlenmiş bir makale/tez
taslağı** oluşturabilirsiniz.

Genel amaçlıdır — herhangi bir disiplinde (mühendislik, tıp, sosyal bilimler, fen
bilimleri vb.) kullanılabilir.

## İki kullanım şekli

1. **Web uygulaması (önerilen — masaüstü + telefon)**: `webapp.py`, aynı mantığı
   tarayıcıdan (kurulum gerektirmeden, herhangi bir cihazdan) kullanmanızı sağlayan
   bir Flask uygulamasıdır. Ücretsiz olarak internete yayınlamak için **[DEPLOY.md](DEPLOY.md)**
   dosyasındaki adım adım kılavuzu izleyin. Yerelde denemek isterseniz:
   ```
   pip install -r requirements.txt
   python webapp.py
   ```
   sonra tarayıcıda `http://localhost:5000` adresini açın.
2. **Komut satırı (CLI)**: aşağıda anlatılan `search`/`save`/`library`/`remove`/`draft`
   komutları, kendi makinenizde terminalden kullanım içindir.

Aşağıdaki bölümler CLI kullanımını anlatır; web uygulamasının aynı özellikleri
tarayıcı arayüzünden sunduğunu unutmayın.

## Beş komut, tek akış

Araç beş alt komuttan oluşur; tipik kullanım sırasıyla soldan sağa ilerler:

```
search  →  save  →  library  →  draft
                        ↑  ↓
                     remove
```

| Komut | Ne yapar |
|---|---|
| `search` | Konuyu birden fazla kaynakta arar, rapor + BibTeX üretir, isterseniz her sonuç için geçici bir tam metin **önizlemesi** gösterir |
| `save` | Bir aramadan beğendiğiniz kaynak(lar)ı numarayla kişisel kütüphanenize kaydeder; isteğe bağlı olarak PDF'i de kalıcı olarak indirir |
| `library` | Kütüphanenizde kayıtlı kaynakları listeler |
| `remove` | Kütüphaneden bir kaydı siler |
| `draft` | Kütüphanenizdeki (veya bir koleksiyondaki) kaynaklardan sentezlenmiş bir makale/tez taslağı üretir |

## Neler yapar?

1. **Literatür taraması / kaynak bulma** (`search`) — aynı anda altı kaynağı sorgular:
   - [OpenAlex](https://openalex.org/) — disiplinler arası geniş kapsam, ~250M+ kayıt
   - [Crossref](https://www.crossref.org/) — DOI kayıt otoritesi, çoğu dergi/konferans
   - [arXiv](https://arxiv.org/) — fizik, bilgisayar bilimi, matematik, istatistik ön baskıları
   - [Semantic Scholar](https://www.semanticscholar.org/) — zengin özet + atıf grafiği
   - [PubMed](https://pubmed.ncbi.nlm.nih.gov/) — tıp / yaşam bilimleri
   - **[DergiPark](https://dergipark.org.tr/)** — TÜBİTAK ULAKBİM'in Türkçe akademik
     dergi platformu (bkz. aşağıdaki "DergiPark nasıl çalışır?" bölümü — diğerlerinden
     farklı olarak önce yerel bir indeks oluşturmanız gerekir)
2. **Tekilleştirme** — aynı makale birden fazla kaynaktan geldiğinde (çoğunlukla olur)
   DOI eşleşmesi ve başlık benzerliğiyle tek kayda indirger, kaynakları birleştirir.
3. **Sıralama** — sorgu terimi eşleşmesi, atıf sayısı ve yayın yılı ağırlıklandırılarak
   hesaplanan bir skora göre sıralar (`--sort relevance|citations|year`).
4. **Tematik gruplandırma** — sonuçları otomatik olarak anahtar kelime kümelerine ayırır.
5. **Otomatik Türkçe çeviri (varsayılan olarak açık)** — yabancı dildeki (çoğunlukla
   İngilizce) başlık ve özetleri otomatik olarak Türkçeye çevirip raporda hem orijinal
   hem çevrilmiş hâlde gösterir. Türkçe kaynaklar zaten Türkçe olduğu için otomatik
   atlanır. **Atıf bütünlüğü için APA/BibTeX kaynakçasında her zaman orijinal başlık
   kullanılır** — çeviri yalnızca okuma kolaylığı sağlar. `ANTHROPIC_API_KEY`
   tanımlıysa en yüksek kaliteli çeviriyi (Claude) kullanır; yoksa otomatik olarak
   ücretsiz/anahtarsız bir motora (Google/MyMemory) düşer. `--no-translate` ile
   kapatılabilir.
6. **Derinlemesine araştırma (opsiyonel, `--deep-research`)** — bir LLM sağlayıcısı
   (Claude için `ANTHROPIC_API_KEY`, ya da NVIDIA NIM için `NVIDIA_API_KEY` — bkz.
   aşağıdaki "NVIDIA API ile kurulum" bölümü) tanımlıysa, toplanan kaynakların
   özetlerini modele vererek gerçek bir sentez ürettirir: temalar, kaynaklar arası
   ortak bulgular/çelişkiler ve araştırma boşlukları. Anahtar yoksa, çıkarımsal
   (extractive) bir özetle otomatik olarak devam eder — asla çökmez.
7. **Kaynakça üretimi** — her kayıt için APA7 atıf metni ve doğrudan Zotero/Mendeley/
   Overleaf'e aktarılabilir bir `.bib` dosyası üretir.
8. **Tam metin önizlemesi (opsiyonel, `search --preview-fulltext`)** — sadece bir link
   vermek yerine, bulunabildiği durumlarda kaynağın gerçek PDF'ini **geçici olarak**
   indirip kısa bir metin önizlemesi (ilk birkaç yüz karakter) çıkarır ve rapora ekler.
   PDF, önizleme çıkarılır çıkarılmaz **diskten silinir** — hiçbir şey kalıcı olarak
   saklanmaz. Amaç, `save` ile hangi kaynağı gerçekten kaydetmeye/indirmeye değeceğine
   karar vermenize yardımcı olmaktır.
9. **Kalıcı indirme (opsiyonel, `save --download`)** — bir kaynağı kütüphanenize
   kaydederken `--download` verirseniz, PDF'i çözümler (önce kaynağın kendi verdiği
   doğrudan PDF linkine, yoksa DOI üzerinden [Unpaywall](https://unpaywall.org)'a, o da
   yoksa makale sayfasındaki standart `citation_pdf_url` etiketine — Google Scholar'ın
   da kullandığı yöntem — bakar), indirir ve metnini çıkarır; metin katmanı bozuk
   çıkarsa (bazı DergiPark PDF'lerinde font kodlaması bozuk olduğu için sıkça olur) ve
   bilgisayarınızda Tesseract OCR kuruluysa otomatik olarak OCR'a düşer. PDF ve
   çıkarılan tam metin, kütüphane klasörünüzde kalıcı olarak saklanır ve `draft`
   komutu bu tam metinleri sentez için kullanabilir.
10. **Kütüphane ve taslak yazımı (`save`, `library`, `draft`)** — beğendiğiniz kaynakları
    adlandırılmış koleksiyonlarda saklayın (ör. `tez-bolum2`), istediğiniz zaman
    `library` ile görün, ve `draft` ile bu koleksiyondaki kaynaklardan **sentezlenmiş,
    bölüm başlıklı bir makale/tez taslağı** üretin. Bir LLM sağlayıcısı tanımlıysa
    (Claude ya da NVIDIA), model kaynakların (varsa tam metinlerini, yoksa özetlerini) gerçekten okuyup
    akıcı, kaynaklar arası karşılaştırma yapan bir taslak yazar; anahtar yoksa
    kural tabanlı bir **iskelet taslak** (bölüm başlıkları + yazar notları + kaynak
    gruplandırması) üretilir — asla çökmez, ama gerçek bir sentez değildir.

## Kurulum

```bash
cd literature-bot
python3 -m venv .venv && source .venv/bin/activate   # opsiyonel ama önerilir
pip install -r requirements.txt

# Derinlemesine araştırma, en kaliteli otomatik çeviri ve gerçek taslak sentezi için,
# İKİSİNDEN BİRİNİ kurun (ikisini de kurmanıza gerek yok):
pip install anthropic      # Claude kullanacaksanız
pip install openai         # NVIDIA NIM kullanacaksanız (NVIDIA'nın API'si OpenAI
                            # istemcisiyle konuşuyor, "openai" paketi sadece bu yüzden gerekiyor)

# Tam metin önizleme / indirme için (PDF indirme + metin çıkarma):
pip install pypdf pymupdf pytesseract pillow

# OCR fallback'in gerçekten çalışması için (opsiyonel ama DergiPark PDF'lerinin
# çoğunda gerekiyor -- bkz. aşağıdaki not), sisteme Tesseract kurun:
#   macOS:   brew install tesseract tesseract-lang
#   Ubuntu:  sudo apt install tesseract-ocr tesseract-ocr-tur
#   Windows: https://github.com/UB-Mannheim/tesseract/wiki adresinden kurup PATH'e ekleyin
```

## NVIDIA API ile kurulum (adım adım)

Claude yerine (ya da Claude hiç yoksa) NVIDIA'nın (build.nvidia.com / NIM) verdiği
API anahtarını kullanmak isterseniz, aşağıdaki adımları takip edin. Bu anahtar
`nvapi-` ile başlar ve OpenAI'nin "chat completions" protokolüyle konuşur; araç bu
yüzden `anthropic` yerine `openai` Python paketini kullanır — ikisi birbirinden
bağımsızdır, sadece hangi sağlayıcıyı kullanacaksanız o paket kurulu olmalı.

1. **Paketleri kurun** (henüz kurmadıysanız):
   ```bash
   cd literature-bot
   python3 -m venv .venv && source .venv/bin/activate   # zaten yaptıysanız atlayın
   pip install -r requirements.txt
   pip install openai
   ```

2. **API anahtarınızı ortam değişkeni olarak tanımlayın.** Terminalde:
   ```bash
   export NVIDIA_API_KEY="nvapi-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
   ```
   (Kendi anahtarınızla değiştirin.) Bu, sadece o terminal oturumu için geçerlidir;
   her yeni terminal açtığınızda tekrar çalıştırmanız gerekir. Kalıcı olsun
   isterseniz `.env.example` dosyasını `.env` olarak kopyalayıp içine
   `NVIDIA_API_KEY=nvapi-...` satırını ekleyin ve her çalıştırmadan önce
   `export $(grep -v '^#' .env | xargs)` ile yükleyin (ya da `python-dotenv` gibi
   bir araçla otomatikleştirin).

3. **Araç, anahtarı gördüğü an otomatik olarak NVIDIA'yı kullanır** -- ekstra bir
   bayrak vermenize gerek yok (`--provider` varsayılanı `auto`, ve `ANTHROPIC_API_KEY`
   tanımlı değilse `NVIDIA_API_KEY` varsa onu seçer). Varsayılan model
   `mistralai/mistral-nemotron`'dır (Türkçe dahil talimat takibi test edilip
   doğrulanmıştır). Test edin:
   ```bash
   python3 -m literature_bot search "eğitimde teknoloji kullanımı" \
     --sources dergipark --dergipark-db dergipark_cache.sqlite3 \
     --max-results 5 --deep-research \
     --output rapor.md --bibtex kaynaklar.bib
   ```
   Konsolda `[bilgi] LLM sağlayıcısı: nvidia (model: mistralai/mistral-nemotron)`
   satırını görmelisiniz. `rapor.md` dosyasındaki "## Sentez" bölümü artık
   NVIDIA tarafından üretilmiş gerçek bir sentez içerir.

4. **NVIDIA'nın ücretsiz kataloğu sık değişiyor** -- modeller zaman zaman
   kullanımdan kaldırılıyor (bu durumda araç "410 Gone" hatası alıp otomatik
   olarak ücretsiz çeviri/iskelet taslak moduna düşer, çökmez, ama gerçek LLM
   sentezi de almazsınız). Varsayılan model artık çalışmıyorsa, hangi
   modellerin şu an aktif olduğunu kendi anahtarınızla test etmek için:
   ```bash
   python3 -m literature_bot.llm_probe
   ```
   Bu komut bilinen büyük/genel amaçlı NVIDIA modellerinden bir listeyi tek
   tek dener ve hangilerinin gerçekten çalıştığını (`CALISIYOR`) gösterir.
   Çalışan bir model bulduğunuzda, iki yoldan biriyle kullanabilirsiniz:
   ```bash
   # tek seferlik, komut satırında:
   python3 -m literature_bot search "..." --deep-research --model <calisan-model-adi>

   # ya da kalıcı olarak, ortam değişkeniyle:
   export LLM_MODEL=<calisan-model-adi>
   ```

5. **Hem Claude hem NVIDIA anahtarınız varsa** ve hangisinin kullanılacağını
   zorlamak isterseniz `--provider anthropic` / `--provider nvidia` (her komutta,
   ya da `export LLM_PROVIDER=nvidia` ile kalıcı olarak) kullanabilirsiniz. Hiçbiri
   verilmezse ve ikisi de tanımlıysa Claude önceliklidir.

6. **`save`, `draft` gibi diğer komutlarda da aynı şekilde çalışır** -- ekstra bir
   ayar gerekmez, `NVIDIA_API_KEY` ortamda tanımlı olduğu sürece `draft` komutu da
   otomatik olarak NVIDIA/Llama ile gerçek bir sentez taslağı üretir:
   ```bash
   python3 -m literature_bot draft --collection tez-bolum2 --type thesis --output taslak.md
   ```

Anahtarınız geçersizse veya çağrı başka bir nedenle başarısız olursa (kota, ağ
hatası vb.), araç **çökmez** -- çeviri ücretsiz motora, sentez ise çıkarımsal
özete/iskelet taslağa otomatik olarak düşer; konsolda bunu belirten bir uyarı
görürsünüz.

## DergiPark nasıl çalışır? (önce okuyun)

DergiPark'ın diğer kaynaklardan farkı: canlı bir arama API'si yok. Web sitesindeki
arama sayfası bot doğrulaması arkasında, resmi olarak sundukları API ise
[OAI-PMH](https://dergipark.org.tr/api/public/oai/) — bu, "şu dergideki tüm
kayıtları ver" diyebildiğiniz bir *metadata toplama* protokolü, "şu kelimeyi
içeren kayıtları ver" diyebileceğiniz bir arama API'si değil. Bu yüzden:

1. Önce ilgi alanınızdaki dergileri bulun:
   ```bash
   python3 -m literature_bot.dergipark_cli list-sets --query "tıp"
   ```
2. Bulduğunuz dergileri yerel bir önbelleğe (SQLite + tam metin arama indeksi) indirin:
   ```bash
   python3 -m literature_bot.dergipark_cli index --sets tıpder1,tıpder2
   ```
   (Bu proje **10 farklı disiplinden (hukuk, tıp, eğitim, sosyal bilimler,
   mühendislik, ilahiyat, ziraat, anatomi...) ~7800 makaleyle hazır bir başlangıç
   önbelleğiyle** (`dergipark_cache.sqlite3`) birlikte geliyor, hemen deneyebilirsiniz.)
3. Artık normal aramalarda `--sources ...,dergipark` kullanabilirsiniz — DergiPark
   sonuçları bu yerel önbellekten anında (tamamen çevrimdışı) gelir.

DergiPark'ın OAI-PMH ucu şu anda toplam **~100 dergiyi** kapsıyor (DergiPark'ın
barındırdığı ~3000 derginin tamamı değil — bu, DergiPark'ın kendi API'sinin bir
sınırı, bu aracın değil). Tüm 100 dergiyi indekslemek isterseniz:
```bash
python3 -m literature_bot.dergipark_cli index --all   # ~50-80 bin kayıt, ~25-30 dakika sürebilir
```
Hangi dergilerin mevcut olduğunu görmek için `list-sets` komutunu `--query` vermeden
çalıştırabilirsiniz.

## Tipik akış (baştan sona örnek)

```bash
# 1) Ara, ve en alakalı sonuçlar için geçici bir tam metin önizlemesi al
python3 -m literature_bot search "eğitimde teknoloji kullanımı" \
  --sources dergipark,openalex,crossref --dergipark-db dergipark_cache.sqlite3 \
  --max-results 20 --preview-fulltext --preview-limit 8 \
  --output rapor.md --bibtex kaynaklar.bib

# Konsol çıktısı, her sonucun başında bir #numara ile birlikte küçük bir tablo gösterir.
# 2) Beğendiğiniz kaynakları numarayla kütüphanenize kaydedin (virgülle birden fazla)
python3 -m literature_bot save 1,3,7 --collection tez-bolum2

# Aralarından birinin gerçek PDF'ini de kalıcı olarak indirmek isterseniz:
python3 -m literature_bot save 4 --collection tez-bolum2 --download \
  --unpaywall-email sizin@epostaniz.com

# 3) Kütüphanenizi istediğiniz zaman görüntüleyin
python3 -m literature_bot library --collection tez-bolum2

# 4) Bu koleksiyondan sentezlenmiş bir taslak üretin
export ANTHROPIC_API_KEY=sk-ant-...   # gerçek sentez için önerilir (yoksa iskelet taslak üretilir)
python3 -m literature_bot draft --collection tez-bolum2 --type thesis --language tr \
  --output taslak.md --bibtex taslak_kaynaklar.bib

# Bir kaydı kütüphaneden çıkarmak isterseniz (id'yi 'library' çıktısından alın):
python3 -m literature_bot remove 4
```

### `search` — arama ve önizleme

```bash
python3 -m literature_bot search "makine öğrenmesi ile erken kanser teşhisi" \
  --sources openalex,crossref,arxiv,semanticscholar,pubmed \
  --year-min 2018 \
  --max-results 40 \
  --output rapor.md \
  --bibtex kaynaklar.bib
```

Derinlemesine sentezle birlikte:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 -m literature_bot search "iklim değişikliğinin kentsel planlamaya etkisi" \
  --deep-research --language tr \
  --output rapor.md --bibtex kaynaklar.bib
```

Tam metin önizlemesiyle birlikte (hiçbir şey diske kalıcı yazılmaz):

```bash
python3 -m literature_bot search "eğitimde yapay zeka kullanımı" \
  --sources dergipark,crossref,openalex \
  --preview-fulltext --preview-limit 15 \
  --unpaywall-email sizin@epostaniz.com \
  --output rapor.md --bibtex kaynaklar.bib
```

Önemli parametreler:

| Parametre | Açıklama | Varsayılan |
|---|---|---|
| `query` (konumsal) | Araştırma konusu / arama sorgusu | — |
| `--sources` | Virgülle ayrılmış kaynak listesi (`openalex,crossref,arxiv,semanticscholar,pubmed,dergipark`) | hepsi |
| `--limit-per-source` | Her kaynaktan çekilecek maksimum kayıt | 20 |
| `--max-results` | Rapora dahil edilecek toplam (tekil) kaynak sayısı | 40 |
| `--year-min` / `--year-max` | Yayın yılı filtresi | — |
| `--sort` | `relevance` \| `citations` \| `year` | relevance |
| `--dergipark-db` | DergiPark yerel önbellek veritabanı yolu | `dergipark_cache.sqlite3` |
| `--no-translate` | Otomatik Türkçe çeviriyi kapat | çeviri açık (varsayılan) |
| `--translate-engine` | `auto` \| `claude` \| `nvidia` \| `mymemory` \| `google` \| `none` | auto |
| `--deep-research` | LLM tabanlı genel sentez üret (Claude ya da NVIDIA anahtarı gerektirir) | kapalı |
| `--provider` | `auto` \| `anthropic` \| `nvidia` — hangi LLM sağlayıcısı kullanılsın | auto |
| `--model` | Kullanılacak model adı (boşsa sağlayıcıya göre makul bir varsayılan seçilir) | — |
| `--language` | Sentez çıktı dili (`tr`/`en`) | tr |
| `--preview-fulltext` | En alakalı sonuçlar için PDF'i **geçici** indirip kısa bir metin önizlemesi göster (kalıcı kayıt yok) | kapalı |
| `--preview-limit` | En fazla kaç sonuç için önizleme denensin | 5 |
| `--preview-chars` | Önizlemede gösterilecek maksimum karakter | — |
| `--unpaywall-email` | Unpaywall için iletişim e-postası (önerilir) | — |
| `--ocr-max-pages` | Önizlemede OCR gereken PDF'lerde işlenecek maksimum sayfa | — |
| `--session-file` | Sonuçların yazılacağı oturum dosyası (`save` bunu okur) | `.literature_bot_last_search.json` |
| `--output` | Markdown rapor dosya yolu | `literatur_raporu.md` |
| `--bibtex` | BibTeX çıktı dosya yolu | `kaynaklar.bib` |
| `--json` | (opsiyonel) ham sonuçları JSON olarak da kaydet | — |

### `save` — kütüphaneye kaydet (+ isteğe bağlı indirme)

`search` her çalıştığında sonuçları bir oturum dosyasına (`.literature_bot_last_search.json`)
yazar; `save` bu dosyayı okuyarak numarayla referans vermenizi sağlar — aramayı
tekrarlamanıza gerek yoktur.

```bash
# Sadece bilgileri (başlık, yazar, özet, DOI/link...) kaydet -- indirme yok
python3 -m literature_bot save 1,3,7 --collection tez-bolum2

# Aynı zamanda gerçek PDF'i de kalıcı olarak indir ve metnini çıkar
python3 -m literature_bot save 4 --collection tez-bolum2 --download \
  --unpaywall-email sizin@epostaniz.com
```

| Parametre | Açıklama | Varsayılan |
|---|---|---|
| `refs` (konumsal) | Son aramadan numara(lar), virgülle ayrılmış (ör. `1,3,7`) | — |
| `--collection` | Kaydedilecek koleksiyon adı | `genel` |
| `--download` | Bu kaynak(lar) için gerçek PDF'i **kalıcı** indir ve metnini çıkar | kapalı (sadece bilgiler kaydedilir) |
| `--session-file` | Okunacak oturum (son arama) dosyası | `.literature_bot_last_search.json` |
| `--library-db` | Kütüphane veritabanı dosyası | `library.sqlite3` |
| `--library-dir` | `--download` ile indirilen PDF/metin dosyalarının klasörü | `kutuphane` |
| `--unpaywall-email` | Unpaywall için iletişim e-postası | — |
| `--ocr-max-pages` | OCR gereken PDF'lerde işlenecek maksimum sayfa | — |

### `library` — kütüphaneyi listele

```bash
python3 -m literature_bot library                        # hepsi
python3 -m literature_bot library --collection tez-bolum2 # sadece bir koleksiyon
```

Her satırda kayıt id'si, koleksiyon, yazar (yıl), tam metin durumu ve başlık gösterilir.
Id, `remove` komutunda kullanılır.

### `draft` — sentezlenmiş taslak üret

```bash
python3 -m literature_bot draft --collection tez-bolum2 --type thesis \
  --title "Eğitimde Teknoloji Kullanımının Etkileri" --language tr \
  --output taslak.md --bibtex taslak_kaynaklar.bib
```

| Parametre | Açıklama | Varsayılan |
|---|---|---|
| `--collection` | Yalnızca bu koleksiyondaki kaynakları kullan | kütüphanedeki hepsi |
| `--title` | Taslağın başlığı | koleksiyon adından türetilir |
| `--type` | `article` (makale) \| `thesis` (tez bölümü) | article |
| `--language` | `tr` \| `en` | tr |
| `--output` | Taslak Markdown dosya yolu | — |
| `--bibtex` | Taslağın kaynakçası için BibTeX dosya yolu | `taslak_kaynaklar.bib` |
| `--provider` | `auto` \| `anthropic` \| `nvidia` — hangi LLM sağlayıcısı kullanılsın | auto |
| `--model` | Kullanılacak model adı (boşsa sağlayıcıya göre makul bir varsayılan seçilir) | — |
| `--library-db` | Kütüphane veritabanı dosyası | `library.sqlite3` |
| `--max-source-chars` | Tam metni olan kaynaklarda sentez için kullanılacak maksimum karakter | — |

`ANTHROPIC_API_KEY` tanımlıysa Claude, kütüphanedeki kaynakları (varsa indirilmiş tam
metinleriyle, yoksa özetleriyle) gerçekten okuyarak akıcı, bölüm başlıklı (Öz/Giriş/
Literatür Taraması/Tartışma/Sonuç) ve kaynaklar arası karşılaştırma içeren bir taslak
yazar. Anahtar yoksa, aynı bölüm yapısında ama **[YAZAR NOTU: ...]** işaretleriyle
belirtilen kural tabanlı bir iskelet + kaynakların otomatik anahtar-kelime
gruplandırması üretilir — gerçek bir sentez değildir, ama başlamak için bir çerçeve
sunar.

**Önemli:** `draft` çıktısı, tez/makale için doğrudan kullanılabilecek nihai bir metin
değildir — bir taslaktır. Her iddiayı ve atfı orijinal kaynaklarla karşılaştırarak
doğrulamanız, akademik dürüstlük kurallarına (intihal, doğru atıf) uygun şekilde kendi
cümlelerinizle yeniden yazmanız gerekir.

### `remove` — kütüphaneden bir kaydı sil

```bash
python3 -m literature_bot remove 4
```

| Parametre | Açıklama | Varsayılan |
|---|---|---|
| `id` (konumsal) | Kütüphaneden silinecek kaydın id'si (`library` komutuyla görün) | — |
| `--library-db` | Kütüphane veritabanı dosyası | `library.sqlite3` |
| `--library-dir` | İndirilmiş PDF/metin dosyalarının klasörü | `kutuphane` |

Tüm komutlar ve parametreleri için: `python3 -m literature_bot <komut> --help`

## Çıktı formatı

### `search` raporu

Üretilen Markdown raporu şu bölümleri içerir:

- **Yöntem** — hangi kaynaklar tarandı, kaç ham/tekil sonuç bulundu, önizleme
  istatistikleri, ve `save` ile nasıl kaydedileceğinin hatırlatması
- **Sentez** — derin sentez (LLM) veya çıkarımsal özet
- **Tematik Gruplandırma** — sonuçların anahtar kelimelere göre gruplanmış hâli
- **Tam Metin Önizlemesi** *(yalnızca `--preview-fulltext` ile)* — her kaynak için kısa
  bir metin alıntısı; hiçbiri kalıcı olarak saklanmaz
- **Tam Kaynakça (APA)** — her kaynağın başındaki **#numara** ile birlikte, atıf
  sayısı ve kaynak bilgisiyle APA formatında tam liste + özetten kısa bir alıntı
  (+ varsa TR çevirisi)

Ayrıca ayrı bir `.bib` dosyası, referans yöneticinize (Zotero, Mendeley) veya
LaTeX/Overleaf projenize doğrudan içe aktarabileceğiniz şekilde üretilir.

### `draft` çıktısı

Öz/Özet, Giriş, Literatür Taraması (kaynaklar arası tematik gruplandırmayla),
Tartışma, Sonuç bölümlerinden oluşan bir Markdown taslağı + ayrı bir `.bib` dosyası.

## API anahtarları hakkında

Hiçbir anahtar olmadan da çalışır (OpenAlex, Crossref, arXiv, PubMed, Semantic
Scholar'ın ücretsiz/anahtarsız kotalarıyla; çeviri de ücretsiz motorlarla; `draft`
komutu da iskelet-taslak moduna düşerek çalışır). Ancak:

- Paylaşımlı/bulut IP'lerden yoğun kullanımda OpenAlex, Semantic Scholar ve ücretsiz
  çeviri motorlarının (Google/MyMemory) anahtarsız günlük kotası hızla dolabilir (429 /
  "çevrilemedi" hatası). Kendi bilgisayarınızdan çalıştırdığınızda bu genellikle sorun
  olmaz; yine de ücretsiz bir anahtar almak isterseniz `.env.example` dosyasına bakın.
- `--deep-research`, en güvenilir/kaliteli otomatik çeviri ve **gerçek** (iskelet değil)
  taslak sentezi için bir LLM sağlayıcı anahtarı önerilir — ya `ANTHROPIC_API_KEY`
  ([console.anthropic.com](https://console.anthropic.com/)), ya da `NVIDIA_API_KEY`
  ([build.nvidia.com](https://build.nvidia.com/) — adım adım kurulum için yukarıdaki
  "NVIDIA API ile kurulum" bölümüne bakın). Hangisini ayarlarsanız, aynı anahtar
  çeviri + derin sentez + taslak yazımı üçü için de otomatik olarak kullanılır.
- Ücretsiz çeviri motoru `mymemory`, kaynak dili belirtmeniz gereken bir servis olduğu
  için yalnızca İngilizce olduğu tahmin edilen metinlerde kullanılır; İngilizce/Türkçe
  dışındaki (ör. Fransızca, Almanca) özetler önce otomatik dil algılayan `google`
  motoruyla denenir, o da başarısız olursa çevrilmeden orijinal hâliyle bırakılır —
  yanlış dil varsayımıyla anlamsız bir çeviri üretmektense çevirmemeyi tercih eder.

`.env.example` dosyasını `.env` olarak kopyalayıp doldurabilir, ya da ortam
değişkeni olarak (`export ANTHROPIC_API_KEY=...`) tanımlayabilirsiniz.

## Proje yapısı

```
literature_bot/
  models.py           # Paper veri modeli (arama, önizleme, tam metin, çeviri alanları)
  sources/            # Her API için ayrı adaptör (openalex, crossref, arxiv, dergipark, ...)
  search.py           # Kaynakları paralel sorgulayan orkestratör
  dedupe.py           # DOI + başlık benzerliğine dayalı tekilleştirme
  ranking.py          # Alaka/atıf/güncellik skorlaması
  synthesis.py        # Tematik gruplandırma + opsiyonel LLM genel sentezi + taslak üretimi
  translation.py      # Otomatik Türkçe çeviri (LLM / Google / MyMemory)
  llm_client.py        # LLM sağlayıcı soyutlaması (Claude / NVIDIA NIM ortak arayüzü)
  llm_probe.py         # `python -m literature_bot.llm_probe` -- hangi NVIDIA/Claude modellerinin şu an çalıştığını test eder
  fulltext.py         # PDF çözümleme + geçici önizleme + kalıcı indirme/metin çıkarma (+ OCR)
  library.py          # Kişisel kütüphane (SQLite): kaydetme, listeleme, silme
  session_cache.py    # 'search' sonuçlarını 'save' komutunun numarayla okuyabilmesi için ara katman
  citations.py        # APA / BibTeX üretimi
  report.py           # 'search' için nihai Markdown raporunu birleştirir
  cli.py              # Ana komut satırı arayüzü (search / save / library / remove / draft)
  dergipark_cache.py  # DergiPark için yerel SQLite/FTS5 önbellek
  dergipark_cli.py    # DergiPark indeksleme komut satırı arayüzü

dergipark_cache.sqlite3  # Hazır başlangıç önbelleği (10 dergi, ~7800 kayıt)
```

## Sınırlamalar ve doğrulama uyarısı

- Bu araç size **gerçek, doğrulanabilir kaynaklar** (DOI/URL ile) getirir — bir LLM'in
  kaynak "uydurmasına" karşı en iyi savunma budur. Yine de bir tez/makalede
  kullanmadan önce her kaynağın başlık/yazar/yıl bilgisini orijinal DOI bağlantısından
  teyit etmeniz önerilir.
- `--deep-research` ve `draft` ile üretilen sentez/taslak metinleri, verilen özet/tam
  metinlere dayanır; yine de akademik bir editör gözüyle gözden geçirilmelidir — LLM
  sentezleri bazen aşırı genelleme yapabilir veya nüansı kaçırabilir. `draft` çıktısı
  bir başlangıç noktasıdır, kopyala-yapıştır bir final metin değil.
- Bazı disiplinlerde (ör. hukuk, sanat tarihi) bu kaynakların kapsamı sınırlı
  kalabilir; gerekirse alana özel bir veritabanı (ör. HeinOnline, JSTOR) elle
  taranmalıdır.
- Tam metin önizleme/indirme en iyi çaba (best-effort) bir özelliktir: birçok büyük
  yayınevi (MDPI, Elsevier, Springer vb.) doğrudan PDF indirme isteklerini
  bot-koruması (Akamai/Cloudflare) ile engeller; bu durumda kaynak "bulunamadı" olarak
  işaretlenir ama link/DOI'si yine de raporda kalır. DergiPark, arXiv ve açık erişim
  (Unpaywall üzerinden bulunan) kaynaklarda başarı oranı genellikle çok daha yüksektir.
  Bir yayınevi sitesini kendi tarayıcınızdan normal şekilde açabiliyorsanız, PDF'i elle
  indirmeniz her zaman mümkündür.
- OCR gerektiren PDF'lerde (bazı DergiPark makaleleri) `tesseract-ocr` ve
  `tesseract-ocr-tur` paketleri kurulu değilse, metin bozuk çıkabilir; rapor bu
  durumu `⚠️ metin bozuk çıkmış olabilir` notuyla açıkça belirtir — böyle bir uyarı
  görürseniz PDF'in kendisine güvenin, çıkarılan metne değil (ya da Tesseract'ı kurup
  tekrar deneyin).
